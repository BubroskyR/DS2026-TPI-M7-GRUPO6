"""Esquemas de pagos, cargos por cancelación, movimientos y reembolsos (RF-7.2 a RF-7.7),
con los nombres y los campos del contrato."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.paginacion import Pagina
from app.schemas.comunes import (
    Importe,
    ImportePositivo,
    MetodoPago,
    Moneda,
    Motivo,
    TipoVehiculo,
)

ConceptoPago = Literal["viaje", "cargo_cancelacion"]
EstadoPago = Literal["pendiente", "aprobado", "rechazado", "reembolsado", "reembolsado_parcial"]
TipoMovimiento = Literal["registro", "aprobacion", "rechazo", "reembolso"]


class PagoNuevo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    viaje_id: uuid.UUID
    # Si el viaje viene de una reserva (RF-5.2).
    reserva_id: uuid.UUID | None = None
    cliente_id: uuid.UUID
    # Conductor o dueño del vehículo que recibe el pago en la liquidación.
    beneficiario_id: uuid.UUID
    # Tiene que ser el total de la tarifa final del viaje.
    monto: ImportePositivo
    # Si no llega, M7 usa el medio predeterminado del cliente y, si no tiene, efectivo.
    metodo: MetodoPago | None = None


class CargoCancelacionNuevo(BaseModel):
    """Lleva `viaje_id`, `reserva_id` o los dos."""

    model_config = ConfigDict(extra="forbid")

    viaje_id: uuid.UUID | None = None
    reserva_id: uuid.UUID | None = None
    cliente_id: uuid.UUID
    tipo_vehiculo: TipoVehiculo
    # No se acepta efectivo: el cargo es para la plataforma y en efectivo lo cobraría el conductor.
    metodo: Literal["tarjeta", "billetera_virtual"] | None = None
    motivo: Motivo

    @model_validator(mode="after")
    def _viaje_o_reserva(self):
        if self.viaje_id is None and self.reserva_id is None:
            raise ValueError("hay que enviar viaje_id, reserva_id o los dos")
        return self


class Pago(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    concepto: ConceptoPago
    viaje_id: uuid.UUID | None = None
    reserva_id: uuid.UUID | None = None
    cliente_id: uuid.UUID
    # Los cargos por cancelación no tienen.
    beneficiario_id: uuid.UUID | None = None
    monto: Importe
    monto_reembolsado: Importe
    moneda: Moneda = "ARS"
    # Falta solo en un cargo que espera que el cliente registre una tarjeta o billetera.
    metodo: MetodoPago | None = None
    estado: EstadoPago
    referencia_externa: str | None = None
    creado_en: datetime
    actualizado_en: datetime


class PaginaPagos(Pagina[Pago]):
    """Página de pagos."""


class AvisoPasarela(BaseModel):
    """Lo que manda la pasarela cuando sabe si aprobó o rechazó un cobro."""

    model_config = ConfigDict(extra="forbid")

    referencia_externa: Annotated[str, Field(min_length=1)]
    pago_id: uuid.UUID
    estado: Literal["aprobado", "rechazado"]


class Movimiento(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pago_id: uuid.UUID
    tipo: TipoMovimiento
    monto: Importe
    fecha: datetime
    # El `sub` del token de quien lo hizo, o "pasarela" si llegó por su aviso.
    actor: str
    detalle: str | None = None


class PaginaMovimientos(Pagina[Movimiento]):
    """Página de movimientos, del más antiguo al más nuevo."""


class ReembolsoNuevo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Si no llega, se reembolsa todo lo que queda.
    monto: ImportePositivo | None = None
    motivo: Motivo


class Reembolso(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pago_id: uuid.UUID
    monto: Importe
    motivo: str
    creado_en: datetime


class PaginaReembolsos(Pagina[Reembolso]):
    """Página de reembolsos."""
