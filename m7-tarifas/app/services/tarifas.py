"""Tarifas (RF-7.1): el cálculo del precio de un viaje, las reglas de tarifa y la
tarifa final de cada viaje."""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeDominio, NoEncontrado
from app.core.paginacion import Paginacion, paginar
from app.models.tarifas import ReglaTarifa, TarifaFinal
from app.schemas.comunes import IMPORTE_MAXIMO
from app.schemas.tarifas import (
    Desglose,
    Estimacion,
    EstimacionNueva,
    ReglaTarifaCambios,
    ReglaTarifaNueva,
    TarifaFinalNueva,
)

CENTAVO = Decimal("0.01")


def al_centavo(importe: Decimal) -> Decimal:
    """Redondea al centavo, con la mitad hacia arriba: 1,005 queda 1,01."""
    return importe.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def calcular_desglose(
    regla: ReglaTarifa, distancia_km: Decimal, duracion_min: Decimal, multiplicador: Decimal
) -> Desglose:
    """Calcula el precio de un viaje con la fórmula del contrato:

    total = máximo((tarifa_base + precio_por_km × distancia + precio_por_minuto × duración)
                   × multiplicador_demanda, tarifa_minima)

    Los cargos se muestran redondeados al centavo, pero el total se calcula con
    los valores sin redondear y se redondea una sola vez, al final.
    """
    cargo_distancia = regla.precio_por_km * distancia_km
    cargo_tiempo = regla.precio_por_minuto * duracion_min
    con_demanda = (regla.tarifa_base + cargo_distancia + cargo_tiempo) * multiplicador
    total = max(con_demanda, regla.tarifa_minima)
    if total > IMPORTE_MAXIMO:
        raise ErrorDeDominio(
            422,
            "/errores/importe-demasiado-grande",
            "El importe calculado es demasiado grande",
            detail=f"El total no puede pasar de {IMPORTE_MAXIMO} pesos.",
        )
    return Desglose(
        tarifa_base=regla.tarifa_base,
        cargo_distancia=al_centavo(cargo_distancia),
        cargo_tiempo=al_centavo(cargo_tiempo),
        multiplicador_demanda=multiplicador,
        total=al_centavo(total),
    )


def regla_activa(sesion: Session, tipo_vehiculo: str) -> ReglaTarifa:
    """La regla activa del tipo de vehículo. Si no hay ninguna, 422."""
    regla = sesion.scalar(
        select(ReglaTarifa).where(
            ReglaTarifa.tipo_vehiculo == tipo_vehiculo, ReglaTarifa.activa.is_(True)
        )
    )
    if regla is None:
        raise ErrorDeDominio(
            422,
            "/errores/sin-regla-activa",
            "No hay una regla de tarifa activa para el tipo de vehículo",
            detail=f"No hay una regla activa para el tipo de vehículo {tipo_vehiculo}.",
        )
    return regla


def estimar(sesion: Session, datos: EstimacionNueva) -> Estimacion:
    """El precio de un viaje antes de confirmarlo. No se guarda nada."""
    regla = regla_activa(sesion, datos.tipo_vehiculo)
    desglose = calcular_desglose(
        regla, datos.distancia_km, datos.duracion_estimada_min, datos.multiplicador_demanda
    )
    return Estimacion(regla_id=regla.id, moneda="ARS", desglose=desglose)


def registrar_tarifa_final(
    sesion: Session, viaje_id: uuid.UUID, datos: TarifaFinalNueva
) -> TarifaFinal:
    """Calcula la tarifa final de un viaje terminado y la guarda. Hay una sola por viaje."""
    regla = regla_activa(sesion, datos.tipo_vehiculo)
    desglose = calcular_desglose(
        regla, datos.distancia_real_km, datos.duracion_real_min, datos.multiplicador_demanda
    )
    tarifa = TarifaFinal(viaje_id=viaje_id, regla_id=regla.id, **desglose.model_dump())
    sesion.add(tarifa)
    try:
        sesion.commit()
    except IntegrityError:
        # El viaje es la clave primaria de la tabla: la base no deja guardar una
        # segunda tarifa final del mismo viaje, aunque lleguen las dos a la vez.
        sesion.rollback()
        raise ErrorDeDominio(
            409,
            "/errores/tarifa-final-ya-registrada",
            "El viaje ya tiene una tarifa final",
        ) from None
    return tarifa


def obtener_tarifa_final(sesion: Session, viaje_id: uuid.UUID) -> TarifaFinal:
    tarifa = sesion.get(TarifaFinal, viaje_id)
    if tarifa is None:
        raise NoEncontrado(f"El viaje {viaje_id} todavía no tiene tarifa final.")
    return tarifa


def listar_reglas(
    sesion: Session,
    paginacion: Paginacion,
    tipo_vehiculo: str | None = None,
    solo_activas: bool = False,
) -> dict:
    consulta = select(ReglaTarifa).order_by(ReglaTarifa.creada_en, ReglaTarifa.id)
    if tipo_vehiculo is not None:
        consulta = consulta.where(ReglaTarifa.tipo_vehiculo == tipo_vehiculo)
    if solo_activas:
        consulta = consulta.where(ReglaTarifa.activa.is_(True))
    return paginar(sesion, consulta, paginacion)


def obtener_regla(sesion: Session, regla_id: uuid.UUID) -> ReglaTarifa:
    regla = sesion.get(ReglaTarifa, regla_id)
    if regla is None:
        raise NoEncontrado(f"No existe la regla de tarifa {regla_id}.")
    return regla


def crear_regla(sesion: Session, datos: ReglaTarifaNueva) -> ReglaTarifa:
    """Crea una regla. Si es activa, la que estaba activa para el mismo tipo deja de estarlo."""
    if datos.activa:
        _desactivar_la_activa(sesion, datos.tipo_vehiculo)
    regla = ReglaTarifa(**datos.model_dump())
    sesion.add(regla)
    sesion.commit()
    return regla


def actualizar_regla(
    sesion: Session, regla_id: uuid.UUID, cambios: ReglaTarifaCambios
) -> ReglaTarifa:
    """Cambia solo los campos enviados. Si la regla pasa a activa, la otra activa del
    mismo tipo deja de estarlo."""
    regla = obtener_regla(sesion, regla_id)
    nuevos = cambios.model_dump(exclude_unset=True)
    if nuevos.get("activa") and not regla.activa:
        _desactivar_la_activa(sesion, regla.tipo_vehiculo)
    for campo, valor in nuevos.items():
        setattr(regla, campo, valor)
    sesion.commit()
    return regla


def _desactivar_la_activa(sesion: Session, tipo_vehiculo: str) -> None:
    # Se ejecuta enseguida, antes de guardar la regla que pasa a activa: la base
    # no deja que haya dos activas del mismo tipo, ni por un instante.
    sesion.execute(
        update(ReglaTarifa)
        .where(ReglaTarifa.tipo_vehiculo == tipo_vehiculo, ReglaTarifa.activa.is_(True))
        .values(activa=False)
    )
