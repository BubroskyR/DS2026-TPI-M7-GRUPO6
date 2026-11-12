"""Tabla de liquidaciones (RF-7.8): lo que se le transfiere a cada beneficiario por período."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import IMPORTE, Base, FechaHora, ahora


class Liquidacion(Base):
    __tablename__ = "liquidaciones"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # El conductor (o el dueño del vehículo) que recibe la liquidación.
    beneficiario_id: Mapped[uuid.UUID] = mapped_column(index=True)
    periodo_desde: Mapped[date]
    periodo_hasta: Mapped[date]
    # Los pagos que incluye. Quedan anotados aunque se anule la liquidación.
    pago_ids: Mapped[list[str]] = mapped_column(JSON)
    monto_bruto: Mapped[Decimal] = mapped_column(IMPORTE)
    comision_plataforma: Mapped[Decimal] = mapped_column(IMPORTE)
    cobrado_en_efectivo: Mapped[Decimal] = mapped_column(IMPORTE)
    # Puede ser negativo: el beneficiario le debe esa diferencia a la plataforma.
    monto_neto: Mapped[Decimal] = mapped_column(IMPORTE)
    # pendiente, transferida o anulada.
    estado: Mapped[str] = mapped_column(String(20))
    referencia_transferencia: Mapped[str | None] = mapped_column(String(100))
    creada_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
    actualizada_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
