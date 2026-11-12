"""Rutas de los medios de pago del cliente (RF-7.2)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.db import SesionDeBase
from app.core.paginacion import ParametrosDePagina
from app.core.seguridad import Usuario, requiere
from app.schemas.medios_pago import MedioPago, MedioPagoCambios, MedioPagoNuevo, PaginaMediosPago
from app.services import medios_pago as servicio

PREFIJO = "/api/v1/medios-pago"
router = APIRouter(prefix=PREFIJO, tags=["Medios de pago"])

# Los clientes tienen pagos:read y pagos:write sobre sus propios medios de pago.
LeeMedios = Annotated[Usuario, Depends(requiere("pagos:read"))]
CambiaMedios = Annotated[Usuario, Depends(requiere("pagos:write"))]


@router.post(
    "",
    status_code=201,
    response_model=MedioPago,
    response_model_exclude_none=True,
    operation_id="registrarMedioPago",
    summary="Registrar un medio de pago del cliente",
)
def registrar_medio_pago(
    usuario: CambiaMedios, datos: MedioPagoNuevo, sesion: SesionDeBase, response: Response
):
    """Con tarjeta o billetera virtual, M7 recibe solo el `token_pasarela`, nunca el
    número de la tarjeta (RNF-19). El primer medio del cliente queda como
    predeterminado. Un CLIENTE solo registra medios propios; si no, 403."""
    medio = servicio.registrar(sesion, datos, usuario)
    response.headers["Location"] = f"{PREFIJO}/{medio.id}"
    return medio


@router.get(
    "",
    response_model=PaginaMediosPago,
    response_model_exclude_none=True,
    operation_id="listarMediosPago",
    summary="Listar los medios de pago",
)
def listar_medios_pago(
    usuario: LeeMedios,
    sesion: SesionDeBase,
    paginacion: ParametrosDePagina,
    cliente_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Los medios vigentes (no los dados de baja), primero el predeterminado. Con un
    token de CLIENTE, solo los suyos; si pide los de otro, 403."""
    return servicio.listar(sesion, paginacion, usuario, cliente_id)


@router.patch(
    "/{medio_pago_id}",
    response_model=MedioPago,
    response_model_exclude_none=True,
    operation_id="actualizarMedioPago",
    summary="Elegir el medio predeterminado o cambiar su alias",
)
def actualizar_medio_pago(
    usuario: CambiaMedios,
    medio_pago_id: uuid.UUID,
    cambios: MedioPagoCambios,
    sesion: SesionDeBase,
):
    """Con `predeterminado: true`, este medio pasa a ser el que M7 usa en los próximos
    cobros y el anterior deja de serlo. Un medio dado de baja, 404."""
    return servicio.actualizar(sesion, medio_pago_id, cambios, usuario)


@router.delete(
    "/{medio_pago_id}",
    status_code=204,
    operation_id="eliminarMedioPago",
    summary="Dar de baja un medio de pago",
)
def eliminar_medio_pago(usuario: CambiaMedios, medio_pago_id: uuid.UUID, sesion: SesionDeBase):
    """M7 no lo borra: lo da de baja, para que los pagos ya hechos conserven su
    historia. Si era el predeterminado, el cliente queda sin predeterminado (sus
    viajes se pagan en efectivo) hasta que elija otro."""
    servicio.dar_de_baja(sesion, medio_pago_id, usuario)
