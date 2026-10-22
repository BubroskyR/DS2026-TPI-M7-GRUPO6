"""Errores en formato application/problem+json (RFC 9457), como pide el contrato."""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

log = logging.getLogger("m7")

TIPO_PROBLEMA = "application/problem+json"

# Títulos de los errores genéricos (esquema ProblemaGenerico del contrato).
TITULOS = {
    400: "Solicitud inválida",
    401: "No autenticado",
    403: "Sin permiso",
    404: "No encontrado",
    405: "Método no permitido",
    413: "Cuerpo demasiado grande",
    415: "Tipo de contenido no soportado",
    500: "Error interno",
    503: "Servicio no disponible",
}


def respuesta_problema(
    status: int,
    *,
    title: str | None = None,
    type_: str = "about:blank",
    detail: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Arma la respuesta de error. Sin `type_`, es un error genérico (`about:blank`)."""
    cuerpo = {"type": type_, "title": title or TITULOS.get(status, "Error"), "status": status}
    if detail:
        cuerpo["detail"] = detail
    return JSONResponse(cuerpo, status_code=status, media_type=TIPO_PROBLEMA, headers=headers)


class ErrorDeDominio(Exception):
    """Una regla de negocio no se cumple (409, 422 o 503 de la pasarela). Tiene su propio `type`."""

    def __init__(
        self,
        status: int,
        type_: str,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(title)
        self.status = status
        self.type_ = type_
        self.title = title
        self.detail = detail
        self.headers = headers


class ServicioNoDisponible(HTTPException):
    """La base de M7 no responde: 503 genérico con Retry-After."""

    def __init__(self, reintentar_en_segundos: int = 5):
        super().__init__(status_code=503, headers={"Retry-After": str(reintentar_en_segundos)})


class NoEncontrado(HTTPException):
    """Lo que se pide (una regla, la tarifa de un viaje) no existe: 404 genérico."""

    def __init__(self, detalle: str):
        super().__init__(status_code=404, detail=detalle)


async def _error_http(request: Request, exc: HTTPException) -> JSONResponse:
    # 404, 405 y los demás errores genéricos. El 405 ya trae el encabezado Allow.
    # Si quien lo lanzó no escribió un detalle propio, no se repite la frase en inglés.
    detalle = exc.detail if exc.detail != HTTPStatus(exc.status_code).phrase else None
    return respuesta_problema(exc.status_code, detail=detalle, headers=exc.headers)


async def _error_de_validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    # El contrato responde 400 cuando el cuerpo, los parámetros o los encabezados
    # no tienen el formato correcto. El 422 queda para las reglas de negocio.
    errores = exc.errors()
    detalle = None
    if errores:
        ubicacion = ".".join(str(parte) for parte in errores[0].get("loc", ()))
        detalle = f"{ubicacion}: {errores[0].get('msg', '')}"
    return respuesta_problema(400, detail=detalle)


async def _error_de_dominio(request: Request, exc: ErrorDeDominio) -> JSONResponse:
    return respuesta_problema(
        exc.status, title=exc.title, type_=exc.type_, detail=exc.detail, headers=exc.headers
    )


async def _base_no_disponible(request: Request, exc: OperationalError) -> JSONResponse:
    # La base se cayó o no contesta en medio de una solicitud: 503 genérico,
    # igual que /health, para que quien llama reintente más tarde.
    log.error("La base de datos no responde: %s", exc)
    return await _error_http(request, ServicioNoDisponible())


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _error_http)
    app.add_exception_handler(RequestValidationError, _error_de_validacion)
    app.add_exception_handler(ErrorDeDominio, _error_de_dominio)
    app.add_exception_handler(OperationalError, _base_no_disponible)
