"""Pasarela de pago simulada (RF-7.3: "simular o integrar la autorización y captura").

M7 le pide que cobre los pagos con tarjeta o billetera virtual. Como es una
simulación, no cobra nada: responde en el acto con el número de la operación
(la referencia externa) y el pago queda `pendiente`. El resultado llega
después, cuando la pasarela avisa a `POST /api/v1/pagos/webhooks/pasarela` si
lo aprobó o lo rechazó. Para simular ese aviso se llama a esa ruta con el
secreto `X-Webhook-Secret` (el README tiene un ejemplo).

Una pasarela real puede no responder: entonces M7 contesta 503 con
Retry-After y nunca se queda esperando (contrato). Si algún día se conecta una
pasarela real, esta función es la única que cambia.
"""

import uuid
from decimal import Decimal

from app.core.errores import ErrorDeDominio


class PasarelaNoDisponible(Exception):
    """La pasarela no respondió a tiempo."""


def pedir_cobro(pago_id: uuid.UUID, monto: Decimal, metodo: str, token_pasarela: str | None) -> str:
    """Le pide a la pasarela que cobre `monto` y devuelve la referencia de la operación.

    Con la tarjeta o la billetera, M7 solo le pasa el token que la pasarela le
    dio a la aplicación del cliente: nunca el número de la tarjeta (RNF-19).
    """
    return f"pas-{uuid.uuid4().hex}"


def no_disponible() -> ErrorDeDominio:
    """El error que devuelve M7 cuando la pasarela no respondió: 503 con su propio type."""
    return ErrorDeDominio(
        503,
        "/errores/pasarela-no-disponible",
        "La pasarela de pago no respondió a tiempo",
        detail="No se cobró nada: se puede reintentar con la misma Idempotency-Key.",
        headers={"Retry-After": "5"},
    )
