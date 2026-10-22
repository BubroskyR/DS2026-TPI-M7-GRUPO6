"""X-Request-Id: identificador de correlación de cada solicitud, como pide el contrato."""

import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.errores import respuesta_problema

ENCABEZADO = "X-Request-Id"
_FORMATO_VALIDO = re.compile(r"[A-Za-z0-9._-]{1,128}")

log = logging.getLogger("m7")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        recibido = request.headers.get(ENCABEZADO, "")
        # Si no llega o tiene un formato inválido, M7 genera uno nuevo:
        # nunca responde 400 por este encabezado.
        request_id = recibido if _FORMATO_VALIDO.fullmatch(recibido) else uuid.uuid4().hex
        request.state.request_id = request_id
        try:
            respuesta = await call_next(request)
        except Exception:
            # Error inesperado: queda en el log con su identificador y se
            # responde 500 sin detalles internos.
            log.exception("Error inesperado en la solicitud %s", request_id)
            respuesta = respuesta_problema(500)
        respuesta.headers[ENCABEZADO] = request_id
        return respuesta
