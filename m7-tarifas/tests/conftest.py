import os

# Estas pruebas usan una base SQLite en memoria, así corren sin Docker. Las
# pruebas de integración con PostgreSQL llegan con los endpoints que guardan datos.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def cliente():
    with TestClient(app) as cliente:
        yield cliente
