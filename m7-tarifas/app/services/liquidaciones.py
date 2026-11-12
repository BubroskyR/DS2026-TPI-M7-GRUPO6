"""Liquidaciones (RF-7.8): cuánto se le transfiere a cada beneficiario (el conductor o
el dueño del vehículo) por los viajes de un período, y su saldo."""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import ahora
from app.core.errores import ErrorDeDominio, NoEncontrado
from app.core.paginacion import Paginacion, paginar
from app.core.seguridad import Usuario, exigir_que_sea_suyo, solo_lo_suyo
from app.models.liquidaciones import Liquidacion
from app.models.pagos import Pago
from app.schemas.liquidaciones import LiquidacionNueva, TransferenciaNueva
from app.services.tarifas import al_centavo

# Los días del período son los de la Argentina (UTC-3, sin horario de verano):
# un viaje del 31 a las 22 h va en ese mes, aunque en UTC ya sea el día 1.
HORA_ARGENTINA = timezone(timedelta(hours=-3))
# Se liquida lo cobrado: los pagos aprobados y los reembolsados en parte.
COBRADOS = ("aprobado", "reembolsado_parcial")


def generar(sesion: Session, datos: LiquidacionNueva) -> Liquidacion:
    """Agrupa los pagos de viajes del beneficiario que están cobrados, se crearon
    dentro del período y todavía no están en una liquidación."""
    if datos.periodo_hasta < datos.periodo_desde:
        raise ErrorDeDominio(
            422,
            "/errores/periodo-invalido",
            "El período termina antes de empezar",
            detail="periodo_hasta tiene que ser igual o posterior a periodo_desde.",
        )
    # Se bloquean los pagos hasta terminar: si dos operadores liquidan a la vez
    # al mismo beneficiario, cada pago queda en una sola liquidación.
    a_liquidar = sesion.scalars(
        select(Pago)
        .where(
            Pago.concepto == "viaje",
            Pago.beneficiario_id == datos.beneficiario_id,
            Pago.estado.in_(COBRADOS),
            Pago.creado_en >= _comienzo_del_dia(datos.periodo_desde),
            Pago.creado_en < _comienzo_del_dia(datos.periodo_hasta + timedelta(days=1)),
            Pago.liquidacion_id.is_(None),
        )
        .order_by(Pago.creado_en, Pago.id)
        .with_for_update()
    ).all()
    if not a_liquidar:
        raise ErrorDeDominio(
            422,
            "/errores/sin-pagos-para-liquidar",
            "No hay pagos para liquidar",
            detail="El beneficiario no tiene pagos cobrados sin liquidar en el período.",
        )

    # Lo cobrado, sin lo reembolsado.
    bruto = sum((pago.monto - pago.monto_reembolsado for pago in a_liquidar), Decimal("0"))
    comision = al_centavo(bruto * settings.comision_plataforma)
    # En efectivo, el conductor cobró en mano todo el viaje: si después se le
    # reembolsó una parte al cliente, la puso la plataforma.
    en_efectivo = sum(
        (pago.monto for pago in a_liquidar if pago.metodo == "efectivo"), Decimal("0")
    )
    liquidacion = Liquidacion(
        id=uuid.uuid4(),
        beneficiario_id=datos.beneficiario_id,
        periodo_desde=datos.periodo_desde,
        periodo_hasta=datos.periodo_hasta,
        pago_ids=[str(pago.id) for pago in a_liquidar],
        monto_bruto=bruto,
        comision_plataforma=comision,
        cobrado_en_efectivo=en_efectivo,
        monto_neto=bruto - comision - en_efectivo,
        estado="pendiente",
    )
    sesion.add(liquidacion)
    # Primero se guarda la liquidación y después se anota en cada pago.
    sesion.flush()
    for pago in a_liquidar:
        pago.liquidacion_id = liquidacion.id
    sesion.commit()
    return liquidacion


def listar(
    sesion: Session,
    paginacion: Paginacion,
    usuario: Usuario,
    beneficiario_id: uuid.UUID | None,
    estado: str | None,
) -> dict:
    """Un conductor solo ve sus liquidaciones; si pide las de otro, 403."""
    beneficiario_id = solo_lo_suyo(usuario, beneficiario_id)
    consulta = select(Liquidacion).order_by(Liquidacion.creada_en, Liquidacion.id)
    if beneficiario_id is not None:
        consulta = consulta.where(Liquidacion.beneficiario_id == beneficiario_id)
    if estado is not None:
        consulta = consulta.where(Liquidacion.estado == estado)
    return paginar(sesion, consulta, paginacion)


def obtener(sesion: Session, liquidacion_id: uuid.UUID, usuario: Usuario) -> Liquidacion:
    """Un conductor solo puede consultar sus propias liquidaciones; si no, 403."""
    liquidacion = sesion.get(Liquidacion, liquidacion_id)
    if liquidacion is None:
        raise NoEncontrado(f"No existe la liquidación {liquidacion_id}.")
    exigir_que_sea_suyo(usuario, liquidacion.beneficiario_id)
    return liquidacion


def transferir(
    sesion: Session, liquidacion_id: uuid.UUID, datos: TransferenciaNueva
) -> Liquidacion:
    """Registra que se le transfirió el neto al beneficiario (o que él pagó la
    diferencia, si el neto es negativo): pasa de `pendiente` a `transferida`."""
    liquidacion = _pendiente(sesion, liquidacion_id)
    liquidacion.estado = "transferida"
    liquidacion.referencia_transferencia = datos.referencia_transferencia
    liquidacion.actualizada_en = ahora()
    sesion.commit()
    return liquidacion


def anular(sesion: Session, liquidacion_id: uuid.UUID) -> Liquidacion:
    """Anula una liquidación pendiente y libera sus pagos para una nueva liquidación."""
    liquidacion = _pendiente(sesion, liquidacion_id)
    liquidacion.estado = "anulada"
    liquidacion.actualizada_en = ahora()
    sesion.execute(
        update(Pago).where(Pago.liquidacion_id == liquidacion.id).values(liquidacion_id=None)
    )
    sesion.commit()
    return liquidacion


def saldo(sesion: Session, beneficiario_id: uuid.UUID, usuario: Usuario) -> dict:
    """Lo que el beneficiario tiene por liquidar, por cobrar y ya cobrado. Un
    conductor solo puede consultar el suyo; si no, 403."""
    exigir_que_sea_suyo(usuario, beneficiario_id)
    sin_liquidar = sesion.scalar(
        select(func.sum(Pago.monto - Pago.monto_reembolsado)).where(
            Pago.concepto == "viaje",
            Pago.beneficiario_id == beneficiario_id,
            Pago.estado.in_(COBRADOS),
            Pago.liquidacion_id.is_(None),
        )
    )
    return {
        "beneficiario_id": beneficiario_id,
        "saldo_pendiente_liquidar": _en_pesos(sin_liquidar),
        "liquidado_pendiente_transferir": _neto_de(sesion, beneficiario_id, "pendiente"),
        "total_transferido": _neto_de(sesion, beneficiario_id, "transferida"),
        "moneda": "ARS",
    }


def _neto_de(sesion: Session, beneficiario_id: uuid.UUID, estado: str) -> Decimal:
    total = sesion.scalar(
        select(func.sum(Liquidacion.monto_neto)).where(
            Liquidacion.beneficiario_id == beneficiario_id, Liquidacion.estado == estado
        )
    )
    return _en_pesos(total)


def _en_pesos(total) -> Decimal:
    # Sin filas, la suma da NULL: es 0.
    return al_centavo(Decimal(str(total or 0)))


def _pendiente(sesion: Session, liquidacion_id: uuid.UUID) -> Liquidacion:
    # Se bloquea la liquidación hasta terminar, por si llegan dos pedidos a la vez.
    liquidacion = sesion.get(Liquidacion, liquidacion_id, with_for_update=True)
    if liquidacion is None:
        raise NoEncontrado(f"No existe la liquidación {liquidacion_id}.")
    if liquidacion.estado != "pendiente":
        raise ErrorDeDominio(
            409,
            "/errores/liquidacion-no-pendiente",
            "La liquidación no está pendiente",
            detail=f"La liquidación está {liquidacion.estado}.",
        )
    return liquidacion


def _comienzo_del_dia(dia: date) -> datetime:
    """Las 0 h de ese día en la Argentina."""
    return datetime.combine(dia, time.min, tzinfo=HORA_ARGENTINA)
