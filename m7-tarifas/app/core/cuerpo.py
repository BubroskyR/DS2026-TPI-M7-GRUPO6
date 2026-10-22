"""Cuerpos de las solicitudes: solo application/json (si no, 415) y hasta 1 MiB (si no, 413)."""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errores import respuesta_problema

LIMITE_EN_BYTES = 1024 * 1024  # 1 MiB, como dice el contrato


class ControlDeCuerpoMiddleware:
    """Revisa el cuerpo de cada solicitud antes de que llegue a las rutas.

    Es un middleware ASGI "puro" (no BaseHTTPMiddleware) porque tiene que
    contar los bytes del cuerpo a medida que la ruta los lee.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        encabezados = Headers(scope=scope)
        largo = int(encabezados.get("content-length", "0"))
        # Sin cuerpo (por ejemplo, un GET o la anulación de una liquidación) no hay nada que revisar.
        if largo == 0 and "transfer-encoding" not in encabezados:
            await self.app(scope, receive, send)
            return

        # Si el largo viene anunciado, se rechaza sin leer el cuerpo.
        if largo > LIMITE_EN_BYTES:
            await respuesta_problema(413)(scope, receive, send)
            return

        tipo = encabezados.get("content-type", "").split(";")[0].strip().lower()
        if tipo != "application/json":
            await respuesta_problema(415)(scope, receive, send)
            return

        # Un cuerpo enviado en partes no anuncia su largo: se cuentan los bytes
        # mientras la ruta los lee y se corta apenas pasan el límite.
        leidos = 0

        async def recibir_contando() -> Message:
            nonlocal leidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                leidos += len(mensaje.get("body", b""))
                if leidos > LIMITE_EN_BYTES:
                    raise HTTPException(status_code=413)
            return mensaje

        await self.app(scope, recibir_contando, send)
