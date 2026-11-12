"""Conexión a la base de datos propia de M7 (RNF-05)."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, Numeric, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.core.config import settings


def _opciones_de_conexion(url: str) -> dict:
    # Con PostgreSQL, si la base no contesta en 3 segundos se la da por caída,
    # para no dejar esperando a quien llama.
    if url.startswith("postgresql"):
        return {"connect_timeout": 3}
    return {}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_opciones_de_conexion(settings.database_url),
)
SesionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Clase madre de las tablas de M7, que se definen en app/models."""


# Importes en pesos, con dos decimales: el contrato redondea al centavo.
# Llegan hasta 9.999.999.999,99 (IMPORTE_MAXIMO, en app/schemas/comunes.py).
IMPORTE = Numeric(12, 2)


def ahora() -> datetime:
    """Fecha y hora actual en UTC, para las columnas que registran cuándo pasó algo."""
    return datetime.now(timezone.utc)


class FechaHora(TypeDecorator):
    """Fecha y hora que siempre se guarda y se lee en UTC.

    SQLite (el de las pruebas) no guarda la zona horaria y PostgreSQL la
    devuelve en la de su configuración: así las dos responden lo mismo.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialect) -> datetime | None:
        # Una fecha en otra zona (por ejemplo, la de la Argentina) se pasa a UTC
        # antes de guardarla o compararla: SQLite no sabe de zonas horarias.
        if valor is not None and valor.tzinfo is not None:
            return valor.astimezone(timezone.utc)
        return valor

    def process_result_value(self, valor: datetime | None, dialect) -> datetime | None:
        if valor is None:
            return None
        if valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(timezone.utc)


def obtener_sesion() -> Iterator[Session]:
    """Una sesión de base por solicitud, que se cierra sola al terminar."""
    with SesionLocal() as sesion:
        yield sesion


# Las rutas reciben la sesión así: `sesion: SesionDeBase`.
SesionDeBase = Annotated[Session, Depends(obtener_sesion)]


def base_disponible() -> bool:
    """Devuelve True si la base responde a una consulta simple."""
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def crear_tablas() -> None:
    """Crea las tablas que falten, como hace `ddl-auto=update` en el ejemplo de la cátedra."""
    Base.metadata.create_all(engine)
