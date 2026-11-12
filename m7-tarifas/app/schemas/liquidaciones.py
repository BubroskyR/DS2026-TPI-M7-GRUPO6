"""Esquemas de liquidaciones y saldos (RF-7.8), con los nombres y los campos del contrato."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.paginacion import Pagina
from app.schemas.comunes import Importe, ImporteConSigno, Moneda

EstadoLiquidacion = Literal["pendiente", "transferida", "anulada"]


class LiquidacionNueva(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beneficiario_id: uuid.UUID
    # Primer y último día del período, los dos incluidos.
    periodo_desde: date
    periodo_hasta: date


class Liquidacion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beneficiario_id: uuid.UUID
    periodo_desde: date
    periodo_hasta: date
    pago_ids: list[uuid.UUID]
    # Lo cobrado en esos pagos, sin lo reembolsado.
    monto_bruto: Importe
    comision_plataforma: Importe
    # Lo que el beneficiario ya cobró en mano en los pagos en efectivo.
    cobrado_en_efectivo: Importe
    # monto_bruto - comision_plataforma - cobrado_en_efectivo. Si es negativo,
    # el beneficiario le debe esa diferencia a la plataforma.
    monto_neto: ImporteConSigno
    moneda: Moneda = "ARS"
    estado: EstadoLiquidacion
    referencia_transferencia: str | None = None
    creada_en: datetime
    actualizada_en: datetime


class PaginaLiquidaciones(Pagina[Liquidacion]):
    """Página de liquidaciones."""


class TransferenciaNueva(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Comprobante o número de la transferencia.
    referencia_transferencia: Annotated[str, Field(min_length=1, max_length=100)]


class Saldo(BaseModel):
    beneficiario_id: uuid.UUID
    # Lo cobrado (antes de la comisión) en pagos que todavía no están en una liquidación.
    saldo_pendiente_liquidar: Importe
    # Suma del neto de las liquidaciones pendientes; puede ser negativa.
    liquidado_pendiente_transferir: ImporteConSigno
    # Suma del neto de las liquidaciones transferidas; puede ser negativa.
    total_transferido: ImporteConSigno
    moneda: Moneda = "ARS"
