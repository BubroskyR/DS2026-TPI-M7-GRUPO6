"""Esquemas de tarifas (RF-7.1), con los nombres y los campos del contrato."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.core.paginacion import Pagina
from app.schemas.comunes import Cambios, Importe, Moneda, Multiplicador, Positivo, TipoVehiculo


class Desglose(BaseModel):
    """Cómo se llegó al total, con la fórmula de RF-7.1."""

    tarifa_base: Importe
    cargo_distancia: Importe
    cargo_tiempo: Importe
    multiplicador_demanda: Multiplicador
    total: Importe


class EstimacionNueva(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo_vehiculo: TipoVehiculo
    # Distancia y tiempo estimados del recorrido, que M5 o M9 obtienen de M4.
    distancia_km: Positivo
    duracion_estimada_min: Positivo
    # Fecha y hora del viaje, si es una reserva (RF-9.1). Por ahora no cambia el precio.
    fecha_hora: datetime | None = None
    multiplicador_demanda: Multiplicador = Decimal("1")


class Estimacion(BaseModel):
    regla_id: uuid.UUID
    moneda: Moneda
    desglose: Desglose


class TarifaFinalNueva(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo_vehiculo: TipoVehiculo
    # Distancia y tiempo reales, que informa M6 al terminar el viaje (RF-6.5).
    distancia_real_km: Positivo
    duracion_real_min: Positivo
    multiplicador_demanda: Multiplicador = Decimal("1")


class TarifaFinal(BaseModel):
    viaje_id: uuid.UUID
    regla_id: uuid.UUID
    moneda: Moneda
    desglose: Desglose
    calculada_en: datetime


class ReglaTarifaNueva(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo_vehiculo: TipoVehiculo
    tarifa_base: Importe
    precio_por_km: Importe
    precio_por_minuto: Importe
    # Precio mínimo de un viaje. Con 0 no hay mínimo.
    tarifa_minima: Importe
    # Monto fijo que se cobra por una cancelación con cargo (RF-7.4).
    cargo_cancelacion: Importe = Decimal("0")
    activa: bool = True


class ReglaTarifaCambios(Cambios):
    """Solo los campos que cambian. El tipo de vehículo no se puede cambiar."""

    tarifa_base: Importe | None = None
    precio_por_km: Importe | None = None
    precio_por_minuto: Importe | None = None
    tarifa_minima: Importe | None = None
    cargo_cancelacion: Importe | None = None
    activa: bool | None = None


class ReglaTarifa(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tipo_vehiculo: TipoVehiculo
    tarifa_base: Importe
    precio_por_km: Importe
    precio_por_minuto: Importe
    tarifa_minima: Importe
    cargo_cancelacion: Importe
    activa: bool


class PaginaReglas(Pagina[ReglaTarifa]):
    """Página de reglas de tarifa."""
