"""Tablas de tarifas (RF-7.1): las reglas de tarifa y la tarifa final de cada viaje."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import IMPORTE, Base, FechaHora, ahora


class ReglaTarifa(Base):
    """Los parámetros configurables de RF-7.1, que administra un operador."""

    __tablename__ = "reglas_tarifa"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tipo_vehiculo: Mapped[str] = mapped_column(String(10))
    tarifa_base: Mapped[Decimal] = mapped_column(IMPORTE)
    precio_por_km: Mapped[Decimal] = mapped_column(IMPORTE)
    precio_por_minuto: Mapped[Decimal] = mapped_column(IMPORTE)
    tarifa_minima: Mapped[Decimal] = mapped_column(IMPORTE)
    cargo_cancelacion: Mapped[Decimal] = mapped_column(IMPORTE, default=Decimal("0"))
    activa: Mapped[bool] = mapped_column(default=True)
    creada_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)


# Como máximo una regla activa por tipo de vehículo: la base no deja guardar una segunda.
Index(
    "una_regla_activa_por_tipo",
    ReglaTarifa.tipo_vehiculo,
    unique=True,
    postgresql_where=ReglaTarifa.activa,
    sqlite_where=ReglaTarifa.activa,
)


class TarifaFinal(Base):
    """Lo que cuesta un viaje terminado, calculado con su distancia y su tiempo reales."""

    __tablename__ = "tarifas_finales"

    # Hay una sola tarifa final por viaje: el viaje es la clave primaria.
    viaje_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    regla_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reglas_tarifa.id"))
    tarifa_base: Mapped[Decimal] = mapped_column(IMPORTE)
    cargo_distancia: Mapped[Decimal] = mapped_column(IMPORTE)
    cargo_tiempo: Mapped[Decimal] = mapped_column(IMPORTE)
    # Sin redondear: se guarda el mismo multiplicador con el que se calculó el total.
    multiplicador_demanda: Mapped[Decimal] = mapped_column(Numeric())
    total: Mapped[Decimal] = mapped_column(IMPORTE)
    calculada_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
