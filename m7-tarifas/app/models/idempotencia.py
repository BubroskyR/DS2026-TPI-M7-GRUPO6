"""Claves de idempotencia: cada POST que cobra o reembolsa guarda acá su clave y su respuesta."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, ahora


class ClaveIdempotencia(Base):
    __tablename__ = "claves_idempotencia"

    # La misma clave en dos operaciones distintas son dos solicitudes distintas.
    operacion: Mapped[str] = mapped_column(String(50), primary_key=True)
    clave: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Huella (SHA-256) del cuerpo: si una repetición trae otro cuerpo, cambia.
    huella: Mapped[str] = mapped_column(String(64))
    # Respuesta original. Mientras está vacía, la primera solicitud se está procesando.
    respuesta: Mapped[dict | None] = mapped_column(JSON)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
