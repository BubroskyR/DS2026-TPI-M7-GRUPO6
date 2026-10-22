"""Punto de entrada de la API de M7: Tarifas, Pagos y Liquidaciones."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401  (registra las tablas antes de crearlas)
from app.core import db
from app.core.errores import registrar_manejadores
from app.core.request_id import RequestIdMiddleware
from app.routers import salud

log = logging.getLogger("m7")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Al arrancar se crean las tablas que falten. Si la base todavía no
    # responde, la API arranca igual y /health avisa con 503.
    try:
        db.crear_tablas()
    except SQLAlchemyError:
        log.exception("No se pudieron crear las tablas al arrancar")
    yield


app = FastAPI(
    title="M7: Tarifas, Pagos y Liquidaciones",
    version="0.1.0",
    lifespan=ciclo_de_vida,
)
app.add_middleware(RequestIdMiddleware)
registrar_manejadores(app)
app.include_router(salud.router)
