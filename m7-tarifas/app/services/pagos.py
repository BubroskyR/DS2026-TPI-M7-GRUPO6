"""Pagos (RF-7.2, RF-7.3, RF-7.4, RF-7.6 y RF-7.7): el cobro de un viaje, el cargo
por una cancelación, el aviso de la pasarela y el historial de cada pago."""

import uuid
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import ahora
from app.core.errores import ErrorDeDominio, NoEncontrado
from app.core.idempotencia import ejecutar_una_vez
from app.core.paginacion import Paginacion, paginar
from app.core.seguridad import Usuario, exigir_que_sea_suyo, solo_lo_suyo
from app.models.medios_pago import MedioPago
from app.models.pagos import MovimientoPago, Pago
from app.models.tarifas import TarifaFinal
from app.schemas import pagos as esquemas
from app.services import medios_pago, pasarela
from app.services.tarifas import regla_activa

# Así figura en el historial lo que llega por el aviso de la pasarela.
ACTOR_PASARELA = "pasarela"


def registrar_pago(
    sesion: Session, clave: str, datos: esquemas.PagoNuevo, usuario: Usuario
) -> tuple[dict, bool]:
    """Registra el pago de un viaje terminado, una sola vez por Idempotency-Key.
    Devuelve (pago, es_nuevo)."""
    return ejecutar_una_vez(
        sesion,
        "crearPago",
        clave,
        datos.model_dump(mode="json"),
        lambda: _registrar_pago(sesion, datos, usuario),
    )


def _registrar_pago(sesion: Session, datos: esquemas.PagoNuevo, usuario: Usuario) -> dict:
    # M7 calcula los importes y no acepta totales ajenos (filmina DS-04): el
    # monto tiene que ser el total de la tarifa final del viaje.
    tarifa = sesion.get(TarifaFinal, datos.viaje_id)
    if tarifa is None:
        raise ErrorDeDominio(
            422,
            "/errores/viaje-sin-tarifa-final",
            "El viaje no tiene tarifa final",
            detail="Primero se registra la tarifa final del viaje y después su pago.",
        )
    if datos.monto != tarifa.total:
        raise ErrorDeDominio(
            422,
            "/errores/monto-distinto-de-la-tarifa",
            "El monto no es el total de la tarifa final del viaje",
            detail=f"La tarifa final del viaje es de {tarifa.total} pesos.",
        )
    if _tiene_uno_vigente(sesion, "viaje", viaje_id=datos.viaje_id):
        raise _pago_ya_registrado()

    # El medio de pago lo elige el cliente en M7 (RF-7.2). Si el pedido trae
    # `metodo`, se usa ese; si no, el predeterminado del cliente y, si no
    # tiene ninguno, efectivo.
    if datos.metodo is not None:
        metodo = datos.metodo
        medio = medios_pago.elegir(sesion, datos.cliente_id, (metodo,))
    else:
        medio = medios_pago.predeterminado(sesion, datos.cliente_id)
        metodo = medio.tipo if medio is not None else "efectivo"

    pago = Pago(
        id=uuid.uuid4(),
        concepto="viaje",
        viaje_id=datos.viaje_id,
        reserva_id=datos.reserva_id,
        cliente_id=datos.cliente_id,
        beneficiario_id=datos.beneficiario_id,
        monto=tarifa.total,
        metodo=metodo,
        medio_pago_id=medio.id if medio is not None else None,
        estado="pendiente",
    )
    _guardar_nuevo(sesion, pago, _pago_ya_registrado)
    anotar(sesion, pago, "registro", usuario.sub)
    if metodo == "efectivo":
        # En efectivo, el conductor cobra en mano: queda aprobado en el acto.
        pago.estado = "aprobado"
        anotar(sesion, pago, "aprobacion", usuario.sub, detalle="Cobrado en efectivo")
    else:
        _pedir_a_la_pasarela(pago, medio)
    sesion.flush()
    return respuesta(pago)


def registrar_cargo(
    sesion: Session, clave: str, datos: esquemas.CargoCancelacionNuevo, usuario: Usuario
) -> tuple[dict, bool]:
    """Registra el cargo por una cancelación (RF-7.4), una sola vez por
    Idempotency-Key. Devuelve (cargo, es_nuevo)."""
    return ejecutar_una_vez(
        sesion,
        "registrarCargoCancelacion",
        clave,
        datos.model_dump(mode="json"),
        lambda: _registrar_cargo(sesion, datos, usuario),
    )


def _registrar_cargo(
    sesion: Session, datos: esquemas.CargoCancelacionNuevo, usuario: Usuario
) -> dict:
    # El importe lo calcula M7: el monto fijo de la regla activa del tipo de vehículo.
    regla = regla_activa(sesion, datos.tipo_vehiculo)
    if regla.cargo_cancelacion == 0:
        raise ErrorDeDominio(
            422,
            "/errores/sin-cargo-de-cancelacion",
            "La regla de tarifa activa no tiene cargo por cancelación",
            detail=f"El cargo_cancelacion de la regla activa de {datos.tipo_vehiculo} es 0.",
        )
    if _tiene_uno_vigente(
        sesion, "cargo_cancelacion", viaje_id=datos.viaje_id, reserva_id=datos.reserva_id
    ):
        raise _cargo_ya_registrado()

    # Solo con tarjeta o billetera virtual. Si el pedido no trae `metodo`, el
    # predeterminado del cliente si es uno de esos; si no, la última tarjeta o
    # billetera que registró. Si no tiene ninguna, el cargo espera sin `metodo`.
    tipos = (datos.metodo,) if datos.metodo is not None else medios_pago.PARA_CARGOS
    medio = medios_pago.elegir(sesion, datos.cliente_id, tipos)
    metodo = datos.metodo or (medio.tipo if medio is not None else None)

    cargo = Pago(
        id=uuid.uuid4(),
        concepto="cargo_cancelacion",
        viaje_id=datos.viaje_id,
        reserva_id=datos.reserva_id,
        cliente_id=datos.cliente_id,
        monto=regla.cargo_cancelacion,
        metodo=metodo,
        medio_pago_id=medio.id if medio is not None else None,
        estado="pendiente",
    )
    _guardar_nuevo(sesion, cargo, _cargo_ya_registrado)
    anotar(sesion, cargo, "registro", usuario.sub, detalle=datos.motivo)
    if metodo is not None:
        _pedir_a_la_pasarela(cargo, medio)
    sesion.flush()
    return respuesta(cargo)


def procesar_aviso(sesion: Session, aviso: esquemas.AvisoPasarela) -> dict:
    """La pasarela avisa si aprobó o rechazó un pago `pendiente` (RF-7.3).

    Las pasarelas repiten los avisos: si el pago ya no está pendiente, no cambia
    nada y lo devuelve como está.
    """
    # Se bloquea el pago hasta terminar, por si llegan dos avisos a la vez.
    pago = sesion.get(Pago, aviso.pago_id, with_for_update=True)
    if pago is None:
        raise NoEncontrado(f"No existe el pago {aviso.pago_id}.")
    if pago.referencia_externa != aviso.referencia_externa:
        raise NoEncontrado(
            f"El pago {aviso.pago_id} no tiene la referencia {aviso.referencia_externa}."
        )
    if pago.estado == "pendiente":
        if aviso.estado == "aprobado":
            pago.estado = "aprobado"
            anotar(sesion, pago, "aprobacion", ACTOR_PASARELA)
        else:
            pago.estado = "rechazado"
            anotar(sesion, pago, "rechazo", ACTOR_PASARELA)
        sesion.commit()
    return respuesta(pago)


def listar(
    sesion: Session,
    paginacion: Paginacion,
    usuario: Usuario,
    *,
    viaje_id: uuid.UUID | None = None,
    cliente_id: uuid.UUID | None = None,
    beneficiario_id: uuid.UUID | None = None,
    estado: str | None = None,
) -> dict:
    """Un cliente solo ve sus pagos; si pide los de otro, 403."""
    cliente_id = solo_lo_suyo(usuario, cliente_id)
    consulta = select(Pago).order_by(Pago.creado_en, Pago.id)
    if viaje_id is not None:
        consulta = consulta.where(Pago.viaje_id == viaje_id)
    if cliente_id is not None:
        consulta = consulta.where(Pago.cliente_id == cliente_id)
    if beneficiario_id is not None:
        consulta = consulta.where(Pago.beneficiario_id == beneficiario_id)
    if estado is not None:
        consulta = consulta.where(Pago.estado == estado)
    return paginar(sesion, consulta, paginacion)


def obtener(sesion: Session, pago_id: uuid.UUID, usuario: Usuario) -> Pago:
    """Un cliente solo puede consultar sus propios pagos; si no, 403."""
    pago = sesion.get(Pago, pago_id)
    if pago is None:
        raise NoEncontrado(f"No existe el pago {pago_id}.")
    exigir_que_sea_suyo(usuario, pago.cliente_id)
    return pago


def listar_movimientos(
    sesion: Session, pago_id: uuid.UUID, paginacion: Paginacion, usuario: Usuario
) -> dict:
    """El historial del pago, del movimiento más antiguo al más nuevo (RF-7.7)."""
    obtener(sesion, pago_id, usuario)
    consulta = (
        select(MovimientoPago)
        .where(MovimientoPago.pago_id == pago_id)
        .order_by(MovimientoPago.numero)
    )
    return paginar(sesion, consulta, paginacion)


def anotar(
    sesion: Session,
    pago: Pago,
    tipo: str,
    actor: str,
    *,
    monto: Decimal | None = None,
    detalle: str | None = None,
) -> None:
    """Suma un movimiento al historial del pago y anota cuándo cambió el pago."""
    sesion.add(
        MovimientoPago(
            id=uuid.uuid4(),
            pago_id=pago.id,
            tipo=tipo,
            monto=pago.monto if monto is None else monto,
            actor=actor,
            detalle=detalle,
        )
    )
    pago.actualizado_en = ahora()


def respuesta(pago: Pago) -> dict:
    """El pago como lo devuelve la API, listo para JSON. Sin los campos vacíos:
    en el contrato, los que pueden faltar no admiten null."""
    return esquemas.Pago.model_validate(pago).model_dump(mode="json", exclude_none=True)


def _tiene_uno_vigente(
    sesion: Session,
    concepto: str,
    *,
    viaje_id: uuid.UUID | None = None,
    reserva_id: uuid.UUID | None = None,
) -> bool:
    """True si el viaje (o la reserva) ya tiene un pago de ese concepto que no fue rechazado."""
    del_mismo = []
    if viaje_id is not None:
        del_mismo.append(Pago.viaje_id == viaje_id)
    if reserva_id is not None:
        del_mismo.append(Pago.reserva_id == reserva_id)
    for condicion in del_mismo:
        existente = sesion.scalar(
            select(Pago.id)
            .where(condicion, Pago.concepto == concepto, Pago.estado != "rechazado")
            .limit(1)
        )
        if existente is not None:
            return True
    return False


def _guardar_nuevo(
    sesion: Session, pago: Pago, error_si_ya_hay: Callable[[], ErrorDeDominio]
) -> None:
    # Se guarda el pago antes que su historial. Si llegaron dos pedidos a la vez
    # con distinta Idempotency-Key, la base rechaza el segundo (índice único).
    sesion.add(pago)
    try:
        sesion.flush()
    except IntegrityError:
        raise error_si_ya_hay() from None


def _pedir_a_la_pasarela(pago: Pago, medio: MedioPago | None) -> None:
    # Con tarjeta o billetera virtual, el pago queda pendiente hasta el aviso de la pasarela.
    token = medio.token_pasarela if medio is not None else None
    try:
        pago.referencia_externa = pasarela.pedir_cobro(pago.id, pago.monto, pago.metodo, token)
    except pasarela.PasarelaNoDisponible:
        raise pasarela.no_disponible() from None


def _pago_ya_registrado() -> ErrorDeDominio:
    return ErrorDeDominio(
        409,
        "/errores/pago-ya-registrado",
        "El viaje ya tiene un pago que no fue rechazado",
    )


def _cargo_ya_registrado() -> ErrorDeDominio:
    return ErrorDeDominio(
        409,
        "/errores/cargo-ya-registrado",
        "El viaje o la reserva ya tiene un cargo por cancelación que no fue rechazado",
    )
