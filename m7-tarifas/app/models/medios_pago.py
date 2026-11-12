"""Tabla de los medios de pago que registra cada cliente (RF-7.2)."""

import uuid
from datetime import datetime

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, FechaHora, ahora


class MedioPago(Base):
    """Una tarjeta, una billetera virtual o el efectivo de un cliente."""

    __tablename__ = "medios_pago"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cliente_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # tarjeta, efectivo o billetera_virtual.
    tipo: Mapped[str] = mapped_column(String(20))
    # Lo que devolvió la pasarela cuando la aplicación le dio la tarjeta o la
    # billetera: con esto M7 le pide los cobros. Nunca se devuelve y nunca se
    # guarda el número de la tarjeta (RNF-19).
    token_pasarela: Mapped[str | None] = mapped_column(String(255))
    ultimos_4: Mapped[str | None] = mapped_column(String(4))
    alias: Mapped[str | None] = mapped_column(String(50))
    # El que M7 usa en los próximos cobros.
    predeterminado: Mapped[bool] = mapped_column(default=False)
    # False: dado de baja. No se borra, para que los pagos que se hicieron con
    # este medio conserven su historia (RF-7.7).
    vigente: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHora, default=ahora)
    dado_de_baja_en: Mapped[datetime | None] = mapped_column(FechaHora)


# Como máximo un medio predeterminado por cliente: la base no deja guardar un segundo.
Index(
    "un_predeterminado_por_cliente",
    MedioPago.cliente_id,
    unique=True,
    postgresql_where=MedioPago.predeterminado,
    sqlite_where=MedioPago.predeterminado,
)
