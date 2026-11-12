"""Rutas de pagos (RF-7.2, RF-7.3, RF-7.6 y RF-7.7): el cobro de un viaje, el aviso de
la pasarela y el historial de cada pago."""

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from starlette.exceptions import HTTPException

from app.core.config import settings
from app.core.db import SesionDeBase
from app.core.idempotencia import ClaveDeIdempotencia
from app.core.paginacion import ParametrosDePagina
from app.core.seguridad import Usuario, requiere, requiere_modulo_u_operador
from app.schemas.pagos import (
    AvisoPasarela,
    EstadoPago,
    PaginaMovimientos,
    PaginaPagos,
    Pago,
    PagoNuevo,
)
from app.services import pagos as servicio

PREFIJO = "/api/v1/pagos"
router = APIRouter(prefix=PREFIJO)

# Los clientes también tienen pagos:read, pero solo ven sus pagos.
LeePagos = Annotated[Usuario, Depends(requiere("pagos:read"))]
# Registran pagos M6 y M9 (y los operadores): un cliente no.
RegistraPagos = Annotated[Usuario, Depends(requiere_modulo_u_operador("pagos:write"))]


def verificar_secreto_de_la_pasarela(
    x_webhook_secret: Annotated[
        str | None, Header(description="Secreto compartido entre la pasarela y M7.")
    ] = None,
) -> None:
    """La pasarela no usa token: manda el secreto compartido en X-Webhook-Secret.
    Si falta o no coincide (o M7 no tiene uno configurado), 401."""
    esperado = settings.pasarela_webhook_secret
    # compare_digest tarda lo mismo aunque el secreto difiera en el primer
    # carácter o en el último: así no se puede adivinar de a uno.
    if (
        not esperado
        or not x_webhook_secret
        or not hmac.compare_digest(x_webhook_secret.encode(), esperado.encode())
    ):
        raise HTTPException(status_code=401, detail="Falta X-Webhook-Secret o no coincide.")


@router.post(
    "",
    status_code=201,
    response_model=Pago,
    response_model_exclude_none=True,
    operation_id="crearPago",
    summary="Registrar el pago de un viaje",
    tags=["Pagos"],
)
def crear_pago(
    usuario: RegistraPagos,
    datos: PagoNuevo,
    clave: ClaveDeIdempotencia,
    sesion: SesionDeBase,
    response: Response,
):
    """M6 lo registra cuando el viaje termina, por el total de la tarifa final. Sin
    `metodo`, M7 usa el medio predeterminado del cliente y, si no tiene, efectivo.
    En efectivo queda aprobado; con tarjeta o billetera virtual, pendiente hasta el
    aviso de la pasarela. La misma Idempotency-Key con el mismo cuerpo devuelve el
    pago original con 200."""
    pago, es_nuevo = servicio.registrar_pago(sesion, clave, datos, usuario)
    if es_nuevo:
        response.headers["Location"] = f"{PREFIJO}/{pago['id']}"
    else:
        response.status_code = 200
    return pago


@router.get(
    "",
    response_model=PaginaPagos,
    response_model_exclude_none=True,
    operation_id="listarPagos",
    summary="Listar pagos",
    tags=["Pagos"],
)
def listar_pagos(
    usuario: LeePagos,
    sesion: SesionDeBase,
    paginacion: ParametrosDePagina,
    viaje_id: Annotated[uuid.UUID | None, Query()] = None,
    cliente_id: Annotated[uuid.UUID | None, Query()] = None,
    beneficiario_id: Annotated[uuid.UUID | None, Query()] = None,
    estado: Annotated[EstadoPago | None, Query()] = None,
):
    """Con un token de CLIENTE, M7 devuelve solo sus pagos; si pide los de otro, 403."""
    return servicio.listar(
        sesion,
        paginacion,
        usuario,
        viaje_id=viaje_id,
        cliente_id=cliente_id,
        beneficiario_id=beneficiario_id,
        estado=estado,
    )


@router.get(
    "/{pago_id}",
    response_model=Pago,
    response_model_exclude_none=True,
    operation_id="obtenerPago",
    summary="Consultar un pago",
    tags=["Pagos"],
)
def obtener_pago(usuario: LeePagos, pago_id: uuid.UUID, sesion: SesionDeBase):
    """Un CLIENTE solo puede consultar sus propios pagos; si no, 403."""
    return servicio.obtener(sesion, pago_id, usuario)


@router.get(
    "/{pago_id}/movimientos",
    response_model=PaginaMovimientos,
    response_model_exclude_none=True,
    operation_id="listarMovimientos",
    summary="Historial de un pago",
    tags=["Historial"],
)
def listar_movimientos(
    usuario: LeePagos, pago_id: uuid.UUID, sesion: SesionDeBase, paginacion: ParametrosDePagina
):
    """Su registro, su aprobación o su rechazo y cada reembolso, del más antiguo al
    más nuevo (RF-7.7). Un CLIENTE solo ve los de sus propios pagos."""
    return servicio.listar_movimientos(sesion, pago_id, paginacion, usuario)


@router.post(
    "/webhooks/pasarela",
    response_model=Pago,
    response_model_exclude_none=True,
    operation_id="webhookPasarela",
    summary="Recibir el resultado que informa la pasarela",
    tags=["Pagos"],
    dependencies=[Depends(verificar_secreto_de_la_pasarela)],
)
def webhook_pasarela(aviso: AvisoPasarela, sesion: SesionDeBase):
    """Deja aprobado o rechazado un pago pendiente. Si el pago ya no está pendiente
    (las pasarelas repiten los avisos), no cambia nada y lo devuelve como está."""
    return servicio.procesar_aviso(sesion, aviso)
