"""Medios de pago del cliente (RF-7.2): el cliente registra sus tarjetas, billeteras
virtuales o el efectivo, y elige cuál usa M7 en los próximos cobros."""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import ahora
from app.core.errores import NoEncontrado
from app.core.paginacion import Paginacion, paginar
from app.core.seguridad import Usuario, exigir_que_sea_suyo, solo_lo_suyo
from app.models.medios_pago import MedioPago
from app.models.pagos import Pago
from app.schemas.medios_pago import MedioPagoCambios, MedioPagoNuevo
from app.services import pasarela

log = logging.getLogger("m7")

# Los medios con los que se puede cobrar un cargo por cancelación: el efectivo no,
# porque el cargo es para la plataforma y en efectivo lo cobraría el conductor.
PARA_CARGOS = ("tarjeta", "billetera_virtual")


def predeterminado(sesion: Session, cliente_id: uuid.UUID) -> MedioPago | None:
    """El medio que el cliente eligió para sus cobros, si tiene uno."""
    return sesion.scalar(
        select(MedioPago).where(
            MedioPago.cliente_id == cliente_id,
            MedioPago.vigente.is_(True),
            MedioPago.predeterminado.is_(True),
        )
    )


def elegir(sesion: Session, cliente_id: uuid.UUID, tipos: tuple[str, ...]) -> MedioPago | None:
    """El medio de alguno de esos tipos con el que se cobra: el predeterminado si
    es de esos tipos; si no, el último que registró el cliente."""
    return sesion.scalar(
        select(MedioPago)
        .where(
            MedioPago.cliente_id == cliente_id,
            MedioPago.vigente.is_(True),
            MedioPago.tipo.in_(tipos),
        )
        .order_by(MedioPago.predeterminado.desc(), MedioPago.creado_en.desc(), MedioPago.id.desc())
        .limit(1)
    )


def registrar(sesion: Session, datos: MedioPagoNuevo, usuario: Usuario) -> MedioPago:
    """Registra un medio. El primero del cliente queda como predeterminado; si el
    nuevo llega como predeterminado, el anterior deja de serlo."""
    exigir_que_sea_suyo(usuario, datos.cliente_id)
    return _con_un_reintento(sesion, lambda: _registrar(sesion, datos))


def _registrar(sesion: Session, datos: MedioPagoNuevo) -> MedioPago:
    tiene_otros = sesion.scalar(
        select(
            exists().where(MedioPago.cliente_id == datos.cliente_id, MedioPago.vigente.is_(True))
        )
    )
    sera_predeterminado = datos.predeterminado or not tiene_otros
    if sera_predeterminado:
        _quitar_predeterminado(sesion, datos.cliente_id)
    medio = MedioPago(
        id=uuid.uuid4(),
        cliente_id=datos.cliente_id,
        tipo=datos.tipo,
        token_pasarela=datos.token_pasarela,
        ultimos_4=datos.ultimos_4,
        alias=datos.alias,
        predeterminado=sera_predeterminado,
    )
    sesion.add(medio)
    # Se guarda antes de hablar con la pasarela: si la base lo rechaza, no se le pidió nada.
    sesion.flush()
    if medio.tipo in PARA_CARGOS:
        _cobrar_cargos_que_esperaban_un_medio(sesion, medio)
    sesion.commit()
    return medio


def _cobrar_cargos_que_esperaban_un_medio(sesion: Session, medio: MedioPago) -> None:
    """Un cargo por cancelación de un cliente sin tarjeta ni billetera queda
    `pendiente` y sin `metodo`. Cuando registra una, M7 se lo pide a la pasarela."""
    cargos = sesion.scalars(
        select(Pago)
        .where(
            Pago.cliente_id == medio.cliente_id,
            Pago.concepto == "cargo_cancelacion",
            Pago.estado == "pendiente",
            Pago.metodo.is_(None),
        )
        .with_for_update()
    ).all()
    for cargo in cargos:
        try:
            referencia = pasarela.pedir_cobro(
                cargo.id, cargo.monto, medio.tipo, medio.token_pasarela
            )
        except pasarela.PasarelaNoDisponible:
            # El medio se registra igual: el cargo sigue esperando y se vuelve a
            # pedir cuando el cliente registre otro medio.
            log.warning("La pasarela no respondió: el cargo %s sigue sin cobrarse", cargo.id)
            continue
        cargo.metodo = medio.tipo
        cargo.medio_pago_id = medio.id
        cargo.referencia_externa = referencia
        cargo.actualizado_en = ahora()


def listar(
    sesion: Session, paginacion: Paginacion, usuario: Usuario, cliente_id: uuid.UUID | None
) -> dict:
    """Los medios vigentes (no los dados de baja), primero el predeterminado."""
    cliente_id = solo_lo_suyo(usuario, cliente_id)
    consulta = (
        select(MedioPago)
        .where(MedioPago.vigente.is_(True))
        .order_by(
            MedioPago.cliente_id,
            MedioPago.predeterminado.desc(),
            MedioPago.creado_en,
            MedioPago.id,
        )
    )
    if cliente_id is not None:
        consulta = consulta.where(MedioPago.cliente_id == cliente_id)
    return paginar(sesion, consulta, paginacion)


def actualizar(
    sesion: Session, medio_pago_id: uuid.UUID, cambios: MedioPagoCambios, usuario: Usuario
) -> MedioPago:
    """Elige el medio como predeterminado (el anterior deja de serlo) o le cambia el alias."""
    medio = _vigente(sesion, medio_pago_id)
    exigir_que_sea_suyo(usuario, medio.cliente_id)

    def _actualizar() -> MedioPago:
        if cambios.predeterminado and not medio.predeterminado:
            _quitar_predeterminado(sesion, medio.cliente_id)
            medio.predeterminado = True
        if cambios.alias is not None:
            medio.alias = cambios.alias
        sesion.commit()
        return medio

    return _con_un_reintento(sesion, _actualizar)


def dar_de_baja(sesion: Session, medio_pago_id: uuid.UUID, usuario: Usuario) -> None:
    """No lo borra, lo da de baja. Si era el predeterminado, el cliente queda sin
    predeterminado hasta que elija otro. Darlo de baja otra vez no es un error."""
    medio = sesion.get(MedioPago, medio_pago_id)
    if medio is None:
        raise NoEncontrado(f"No existe el medio de pago {medio_pago_id}.")
    exigir_que_sea_suyo(usuario, medio.cliente_id)
    if medio.vigente:
        medio.vigente = False
        medio.predeterminado = False
        # M7 ya no lo va a usar para cobrar: no tiene por qué guardar el token.
        medio.token_pasarela = None
        medio.dado_de_baja_en = ahora()
        sesion.commit()


def _vigente(sesion: Session, medio_pago_id: uuid.UUID) -> MedioPago:
    medio = sesion.get(MedioPago, medio_pago_id)
    if medio is None or not medio.vigente:
        raise NoEncontrado(f"No existe el medio de pago {medio_pago_id} o se dio de baja.")
    return medio


def _quitar_predeterminado(sesion: Session, cliente_id: uuid.UUID) -> None:
    # Se ejecuta enseguida, antes de guardar el nuevo predeterminado: la base no
    # deja que un cliente tenga dos, ni por un instante.
    sesion.execute(
        update(MedioPago)
        .where(MedioPago.cliente_id == cliente_id, MedioPago.predeterminado.is_(True))
        .values(predeterminado=False)
    )


def _con_un_reintento(sesion: Session, hacer: Callable[[], MedioPago]) -> MedioPago:
    # Si llegan a la vez dos pedidos que eligen el predeterminado del mismo
    # cliente, la base rechaza el segundo (índice único). Se reintenta una vez,
    # ya con lo que guardó el primero.
    try:
        return hacer()
    except IntegrityError:
        sesion.rollback()
        return hacer()
