import os
import tempfile
from pathlib import Path

# Las pruebas usan su propia base, nunca la de desarrollo. Si está definida
# PRUEBAS_DATABASE_URL, usan esa (PostgreSQL: pruebas de integración, RNF-07).
# Si no, usan un archivo SQLite temporal, así corren sin Docker.
_SQLITE_DE_PRUEBA = Path(tempfile.gettempdir()) / "m7-pruebas.db"
_SQLITE_DE_PRUEBA.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = os.environ.get(
    "PRUEBAS_DATABASE_URL", f"sqlite:///{_SQLITE_DE_PRUEBA.as_posix()}"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import db  # noqa: E402
from app.main import app  # noqa: E402

# Al empezar, las tablas se crean de cero con su forma actual.
db.Base.metadata.drop_all(db.engine)
db.Base.metadata.create_all(db.engine)


@pytest.fixture(autouse=True)
def base_vacia():
    """Cada prueba empieza con las tablas vacías."""
    with db.engine.begin() as conexion:
        for tabla in reversed(db.Base.metadata.sorted_tables):
            conexion.execute(tabla.delete())
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def sesion():
    with db.SesionLocal() as sesion:
        yield sesion
