"""Rutas de reembolsos (RF-7.5): devolver todo o parte de un pago y listar sus reembolsos."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.db import SesionDeBase
from app.core.idempotencia import ClaveDeIdempotencia
from app.core.paginacion import ParametrosDePagina
from app.core.seguridad import Usuario, requiere, requiere_modulo_u_operador
from app.schemas.pagos import PaginaReembolsos, Reembolso, ReembolsoNuevo
from app.services import reembolsos as servicio

router = APIRouter(prefix="/api/v1/pagos/{pago_id}/reembolsos", tags=["Reembolsos"])

LeePagos = Annotated[Usuario, Depends(requiere("pagos:read"))]
# Reembolsan M9 y los operadores: un cliente no.
Reembolsa = Annotated[Usuario, Depends(requiere_modulo_u_operador("pagos:write"))]


@router.post(
    "",
    status_code=201,
    response_model=Reembolso,
    operation_id="reembolsarPago",
    summary="Reembolsar todo o parte de un pago",
)
def reembolsar_pago(
    usuario: Reembolsa,
    pago_id: uuid.UUID,
    datos: ReembolsoNuevo,
    clave: ClaveDeIdempotencia,
    sesion: SesionDeBase,
    response: Response,
):
    """Reembolso total o parcial de un pago aprobado o reembolsado en parte; si el
    pago está en otro estado, 409. Sin `monto`, se reembolsa todo lo que queda. Si el
    monto supera lo que queda, 422."""
    reembolso, es_nuevo = servicio.reembolsar(sesion, clave, pago_id, datos, usuario)
    if es_nuevo:
        # No hay una ruta para un reembolso solo: se encuentra en la lista del pago.
        response.headers["Location"] = f"/api/v1/pagos/{pago_id}/reembolsos"
    else:
        response.status_code = 200
    return reembolso


@router.get(
    "",
    response_model=PaginaReembolsos,
    operation_id="listarReembolsos",
    summary="Listar los reembolsos de un pago",
)
def listar_reembolsos(
    usuario: LeePagos, pago_id: uuid.UUID, sesion: SesionDeBase, paginacion: ParametrosDePagina
):
    """Un CLIENTE solo ve los de sus propios pagos."""
    return servicio.listar(sesion, pago_id, paginacion, usuario)
