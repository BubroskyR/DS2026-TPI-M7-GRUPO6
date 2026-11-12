"""Ruta del cargo por cancelación (RF-7.4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.db import SesionDeBase
from app.core.idempotencia import ClaveDeIdempotencia
from app.core.seguridad import Usuario, requiere_modulo_u_operador
from app.schemas.pagos import CargoCancelacionNuevo, Pago
from app.services import pagos as servicio

router = APIRouter(tags=["Cancelaciones"])

# Lo registran M6 y M9: un cliente no.
RegistraCargos = Annotated[Usuario, Depends(requiere_modulo_u_operador("pagos:write"))]


@router.post(
    "/api/v1/cargos-cancelacion",
    status_code=201,
    response_model=Pago,
    response_model_exclude_none=True,
    operation_id="registrarCargoCancelacion",
    summary="Registrar el cargo fijo por una cancelación",
)
def registrar_cargo_cancelacion(
    usuario: RegistraCargos,
    datos: CargoCancelacionNuevo,
    clave: ClaveDeIdempotencia,
    sesion: SesionDeBase,
    response: Response,
):
    """M6 o M9 lo llaman cuando, según sus reglas, una cancelación lleva cargo. El
    importe es el `cargo_cancelacion` de la regla activa. Se cobra con una tarjeta o
    billetera virtual del cliente; si no tiene ninguna, queda pendiente y sin
    `metodo` hasta que registre una. Si no hay una regla activa o su cargo es 0, 422."""
    cargo, es_nuevo = servicio.registrar_cargo(sesion, clave, datos, usuario)
    if es_nuevo:
        response.headers["Location"] = f"/api/v1/pagos/{cargo['id']}"
    else:
        response.status_code = 200
    return cargo
