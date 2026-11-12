"""Tablas de pagos (RF-7.2 a RF-7.7): los pagos de los viajes y los cargos por
cancelación, el historial de cada pago y sus reembolsos."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import IMPORTE, Base, FechaHora, ahora


class Pago(Base):
    """Un cobro al cliente: el de un viaje o el cargo fijo por una cancelación."""

    __tablename__ = "pagos"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # viaje: el pago de un viaje. cargo_cancelacion: el cargo fijo por una cancelación.
    concepto: Mapped[str] = mapped_column(String(20))
    viaje_id: Mapped[uuid.UUID | None]
    reserva_id: Mapped[uuid.UUID | None]
    cliente_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # Quien lo recibe en la liquidación. Un cargo por cancelación no tiene: es de la plataforma.
    beneficiario_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    monto: Mapped[Decimal] = mapped_column(IMPORTE)
    monto_reembolsado: Mapped[Decimal] = mapped_column(IMPORTE, default=Decimal("0"))
    # tarjeta, efectivo o billetera_virtual. Vacío solo en un cargo por cancelación
    # que espera que el cliente registre una tarjeta o billetera virtual.
    metodo: Mapped[str | None] = mapped_column(String(20))
    # El medio de pago del cliente con el que se cobró, si tenía uno registrado.
    medio_pago_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("medios_pago.id"))
    # pendiente, aprobado, rechazado, reembolsado o reembolsado_parcial.
    estado: Mapped[str] = mapped_column(String(20))
    # El número de la operación en la pasarela. Nunca datos de la tarjeta (RNF-19).
    referencia_externa: Mapped[str | None] = mapped_column(String(100))
    # La liquidación que lo incluye. Vacío: todavía no se liquidó (o se anuló su liquidación).
    liquidacion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("liquidaciones.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)


# Un viaje tiene como máximo un pago y un cargo que no estén rechazados (RNF-08):
# la base no deja guardar un segundo, aunque lleguen los dos a la vez.
Index(
    "un_pago_vigente_por_viaje",
    Pago.viaje_id,
    Pago.concepto,
    unique=True,
    postgresql_where=Pago.estado != "rechazado",
    sqlite_where=Pago.estado != "rechazado",
)
# Lo mismo para el cargo por cancelación de una reserva.
Index(
    "un_cargo_vigente_por_reserva",
    Pago.reserva_id,
    unique=True,
    postgresql_where=(Pago.concepto == "cargo_cancelacion") & (Pago.estado != "rechazado"),
    sqlite_where=(Pago.concepto == "cargo_cancelacion") & (Pago.estado != "rechazado"),
)


class MovimientoPago(Base):
    """Un paso en la historia de un pago (RF-7.7). No se modifica ni se borra."""

    __tablename__ = "movimientos_pago"

    # Número que pone la base al guardarlo: ordena el historial aunque dos
    # movimientos tengan la misma fecha.
    numero: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    id: Mapped[uuid.UUID] = mapped_column(unique=True, default=uuid.uuid4)
    pago_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pagos.id"), index=True)
    # registro, aprobacion, rechazo o reembolso.
    tipo: Mapped[str] = mapped_column(String(20))
    monto: Mapped[Decimal] = mapped_column(IMPORTE)
    fecha: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
    # El `sub` del token de quien lo hizo, o "pasarela" si llegó por su aviso.
    actor: Mapped[str] = mapped_column(String(255))
    # Un motivo o un dato adicional, sin datos sensibles.
    detalle: Mapped[str | None] = mapped_column(String(500))


class Reembolso(Base):
    """La devolución de todo o parte de un pago (RF-7.5)."""

    __tablename__ = "reembolsos"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pago_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pagos.id"), index=True)
    monto: Mapped[Decimal] = mapped_column(IMPORTE)
    motivo: Mapped[str] = mapped_column(String(500))
    creado_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
