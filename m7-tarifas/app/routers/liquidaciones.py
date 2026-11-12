"""Rutas de liquidaciones y saldos (RF-7.8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.db import SesionDeBase
from app.core.paginacion import ParametrosDePagina
from app.core.seguridad import Usuario, requiere, requiere_modulo_u_operador
from app.schemas.liquidaciones import (
    EstadoLiquidacion,
    Liquidacion,
    LiquidacionNueva,
    PaginaLiquidaciones,
    Saldo,
    TransferenciaNueva,
)
from app.services import liquidaciones as servicio

PREFIJO = "/api/v1/liquidaciones"
router = APIRouter(prefix=PREFIJO, tags=["Liquidaciones"])

# Los conductores tienen liquidaciones:read, pero solo ven lo suyo.
LeeLiquidaciones = Annotated[Usuario, Depends(requiere("liquidaciones:read"))]
# Generan, transfieren y anulan los operadores.
ESCRIBE_LIQUIDACIONES = Depends(requiere_modulo_u_operador("liquidaciones:write"))


@router.post(
    "",
    status_code=201,
    response_model=Liquidacion,
    response_model_exclude_none=True,
    operation_id="generarLiquidacion",
    summary="Generar la liquidación de un beneficiario",
    dependencies=[ESCRIBE_LIQUIDACIONES],
)
def generar_liquidacion(datos: LiquidacionNueva, sesion: SesionDeBase, response: Response):
    """Agrupa los pagos de viajes del beneficiario que están cobrados, se crearon en el
    período y no están en otra liquidación. Neto = bruto - comisión - lo cobrado en
    efectivo. Si el período termina antes de empezar, o no hay pagos, 422."""
    liquidacion = servicio.generar(sesion, datos)
    response.headers["Location"] = f"{PREFIJO}/{liquidacion.id}"
    return liquidacion


@router.get(
    "",
    response_model=PaginaLiquidaciones,
    response_model_exclude_none=True,
    operation_id="listarLiquidaciones",
    summary="Listar liquidaciones",
)
def listar_liquidaciones(
    usuario: LeeLiquidaciones,
    sesion: SesionDeBase,
    paginacion: ParametrosDePagina,
    beneficiario_id: Annotated[uuid.UUID | None, Query()] = None,
    estado: Annotated[EstadoLiquidacion | None, Query()] = None,
):
    """Con un token de CONDUCTOR, solo las suyas; si pide las de otro, 403."""
    return servicio.listar(sesion, paginacion, usuario, beneficiario_id, estado)


@router.get(
    "/saldos/{beneficiario_id}",
    response_model=Saldo,
    operation_id="obtenerSaldo",
    summary="Consultar el saldo de un beneficiario",
)
def obtener_saldo(usuario: LeeLiquidaciones, beneficiario_id: uuid.UUID, sesion: SesionDeBase):
    """Un CONDUCTOR solo puede consultar su propio saldo; si no, 403. Un beneficiario
    sin pagos tiene todos los importes en 0."""
    return servicio.saldo(sesion, beneficiario_id, usuario)


@router.get(
    "/{liquidacion_id}",
    response_model=Liquidacion,
    response_model_exclude_none=True,
    operation_id="obtenerLiquidacion",
    summary="Consultar una liquidación",
)
def obtener_liquidacion(usuario: LeeLiquidaciones, liquidacion_id: uuid.UUID, sesion: SesionDeBase):
    """Un CONDUCTOR solo puede consultar sus propias liquidaciones; si no, 403."""
    return servicio.obtener(sesion, liquidacion_id, usuario)


@router.post(
    "/{liquidacion_id}/transferencia",
    response_model=Liquidacion,
    response_model_exclude_none=True,
    operation_id="confirmarTransferencia",
    summary="Registrar la transferencia al beneficiario",
    dependencies=[ESCRIBE_LIQUIDACIONES],
)
def confirmar_transferencia(
    liquidacion_id: uuid.UUID, datos: TransferenciaNueva, sesion: SesionDeBase
):
    """La liquidación pasa de pendiente a transferida. Si no está pendiente, 409."""
    return servicio.transferir(sesion, liquidacion_id, datos)


@router.post(
    "/{liquidacion_id}/anulacion",
    response_model=Liquidacion,
    response_model_exclude_none=True,
    operation_id="anularLiquidacion",
    summary="Anular una liquidación pendiente",
    dependencies=[ESCRIBE_LIQUIDACIONES],
)
def anular_liquidacion(liquidacion_id: uuid.UUID, sesion: SesionDeBase):
    """Anula una liquidación pendiente y libera sus pagos para una nueva liquidación.
    Si no está pendiente, 409. No lleva cuerpo."""
    return servicio.anular(sesion, liquidacion_id)
