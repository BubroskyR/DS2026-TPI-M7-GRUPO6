"""Rutas de tarifas (RF-7.1): estimación, tarifa final de cada viaje y reglas de tarifa."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.db import SesionDeBase
from app.core.paginacion import ParametrosDePagina
from app.core.seguridad import requiere, requiere_modulo_u_operador
from app.schemas.comunes import TipoVehiculo
from app.schemas.tarifas import (
    Desglose,
    Estimacion,
    EstimacionNueva,
    PaginaReglas,
    ReglaTarifa,
    ReglaTarifaCambios,
    ReglaTarifaNueva,
    TarifaFinal,
    TarifaFinalNueva,
)
from app.services import tarifas as servicio

PREFIJO = "/api/v1/tarifas"
router = APIRouter(prefix=PREFIJO, tags=["Tarifas"])

# Estiman M5 y M9; consultan M6 y los operadores.
LEE_TARIFAS = Depends(requiere("tarifas:read"))
# Registra la tarifa final M6; las reglas, los operadores. Un cliente o un conductor no.
ESCRIBE_TARIFAS = Depends(requiere_modulo_u_operador("tarifas:write"))


@router.post(
    "/estimaciones",
    response_model=Estimacion,
    operation_id="estimarTarifa",
    summary="Estimar la tarifa de un viaje",
    dependencies=[LEE_TARIFAS],
)
def estimar_tarifa(datos: EstimacionNueva, sesion: SesionDeBase) -> Estimacion:
    """Calcula el precio de un viaje antes de confirmarlo, con la regla activa del tipo
    de vehículo. No se guarda. Si no hay una regla activa, 422."""
    return servicio.estimar(sesion, datos)


@router.post(
    "/viajes/{viaje_id}/tarifa-final",
    status_code=201,
    response_model=TarifaFinal,
    operation_id="calcularTarifaFinal",
    summary="Calcular y registrar la tarifa final de un viaje terminado",
    dependencies=[ESCRIBE_TARIFAS],
)
def calcular_tarifa_final(
    viaje_id: uuid.UUID, datos: TarifaFinalNueva, sesion: SesionDeBase, response: Response
) -> TarifaFinal:
    """M6 la registra cuando el viaje termina, con la distancia y el tiempo reales. Hay
    una sola por viaje: un segundo intento, 409. Si no hay una regla activa, 422."""
    tarifa = servicio.registrar_tarifa_final(sesion, viaje_id, datos)
    response.headers["Location"] = f"{PREFIJO}/viajes/{viaje_id}/tarifa-final"
    return _respuesta_de_tarifa_final(tarifa)


@router.get(
    "/viajes/{viaje_id}/tarifa-final",
    response_model=TarifaFinal,
    operation_id="obtenerTarifaFinal",
    summary="Consultar la tarifa final de un viaje",
    dependencies=[LEE_TARIFAS],
)
def obtener_tarifa_final(viaje_id: uuid.UUID, sesion: SesionDeBase) -> TarifaFinal:
    """Si el viaje todavía no tiene tarifa final, 404."""
    return _respuesta_de_tarifa_final(servicio.obtener_tarifa_final(sesion, viaje_id))


@router.get(
    "/reglas",
    response_model=PaginaReglas,
    operation_id="listarReglas",
    summary="Listar las reglas de tarifa",
    dependencies=[LEE_TARIFAS],
)
def listar_reglas(
    sesion: SesionDeBase,
    paginacion: ParametrosDePagina,
    tipo_vehiculo: Annotated[
        TipoVehiculo | None, Query(description="Filtra por tipo de vehículo.")
    ] = None,
    solo_activas: Annotated[
        bool, Query(description="Si es true, devuelve solo las reglas activas.")
    ] = False,
):
    return servicio.listar_reglas(sesion, paginacion, tipo_vehiculo, solo_activas)


@router.post(
    "/reglas",
    status_code=201,
    response_model=ReglaTarifa,
    operation_id="crearRegla",
    summary="Crear una regla de tarifa",
    dependencies=[ESCRIBE_TARIFAS],
)
def crear_regla(datos: ReglaTarifaNueva, sesion: SesionDeBase, response: Response):
    """Si la regla nueva es activa, la que estaba activa para el mismo tipo de vehículo
    deja de estarlo: hay como máximo una activa por tipo."""
    regla = servicio.crear_regla(sesion, datos)
    response.headers["Location"] = f"{PREFIJO}/reglas/{regla.id}"
    return regla


@router.get(
    "/reglas/{regla_id}",
    response_model=ReglaTarifa,
    operation_id="obtenerRegla",
    summary="Consultar una regla de tarifa",
    dependencies=[LEE_TARIFAS],
)
def obtener_regla(regla_id: uuid.UUID, sesion: SesionDeBase):
    return servicio.obtener_regla(sesion, regla_id)


@router.patch(
    "/reglas/{regla_id}",
    response_model=ReglaTarifa,
    operation_id="actualizarRegla",
    summary="Modificar una regla de tarifa",
    dependencies=[ESCRIBE_TARIFAS],
)
def actualizar_regla(regla_id: uuid.UUID, cambios: ReglaTarifaCambios, sesion: SesionDeBase):
    """Actualiza solo los campos enviados. Si la regla pasa a activa, la otra activa del
    mismo tipo de vehículo deja de estarlo."""
    return servicio.actualizar_regla(sesion, regla_id, cambios)


def _respuesta_de_tarifa_final(tarifa) -> TarifaFinal:
    # En la tabla, los datos del desglose son columnas sueltas; en la respuesta
    # van agrupados en `desglose`, como pide el contrato.
    return TarifaFinal(
        viaje_id=tarifa.viaje_id,
        regla_id=tarifa.regla_id,
        moneda="ARS",
        desglose=Desglose.model_validate(tarifa, from_attributes=True),
        calculada_en=tarifa.calculada_en,
    )
