"""Tipos que comparten varios esquemas del contrato."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema, model_validator

# Los tipos de vehículo del enunciado (RF-3.2).
TipoVehiculo = Literal["auto", "moto"]
# Pesos argentinos.
Moneda = Literal["ARS"]
# Los medios de pago (RF-7.2). billetera_virtual incluye Mercado Pago.
MetodoPago = Literal["tarjeta", "efectivo", "billetera_virtual"]

# En JSON los importes van como números (4850.5) y no como texto ("4850.50").
_COMO_NUMERO = PlainSerializer(float, return_type=float, when_used="json")

# Lo más grande que entra en las columnas de importes de la base (Numeric(12, 2)).
IMPORTE_MAXIMO = Decimal("9999999999.99")

# Importe en pesos con hasta dos decimales.
Importe = Annotated[
    Decimal,
    Field(ge=0, le=IMPORTE_MAXIMO, decimal_places=2),
    _COMO_NUMERO,
    WithJsonSchema({"type": "number", "minimum": 0}),
]
# Importe mayor que 0, como el monto de un pago o de un reembolso.
ImportePositivo = Annotated[
    Decimal,
    Field(gt=0, le=IMPORTE_MAXIMO, decimal_places=2),
    _COMO_NUMERO,
    WithJsonSchema({"type": "number", "exclusiveMinimum": 0}),
]
# Importe que puede ser negativo, como el neto de una liquidación.
ImporteConSigno = Annotated[
    Decimal, Field(decimal_places=2), _COMO_NUMERO, WithJsonSchema({"type": "number"})
]
# Un número mayor que 0, como la distancia o la duración de un viaje.
Positivo = Annotated[
    Decimal, Field(gt=0), _COMO_NUMERO, WithJsonSchema({"type": "number", "exclusiveMinimum": 0})
]
# Recargo por alta demanda. Con 1 no hay recargo.
Multiplicador = Annotated[
    Decimal, Field(ge=1), _COMO_NUMERO, WithJsonSchema({"type": "number", "minimum": 1})
]

# Un motivo escrito por una persona, como el de un reembolso o un cargo.
Motivo = Annotated[str, Field(min_length=1, max_length=500)]


class Cambios(BaseModel):
    """Cuerpo de un PATCH: solo los campos que cambian.

    Un cuerpo vacío o un campo en null responden 400, como cualquier formato inválido.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _al_menos_un_campo_y_ninguno_null(self):
        if not self.model_fields_set:
            raise ValueError("hay que enviar al menos un campo")
        nulos = sorted(campo for campo in self.model_fields_set if getattr(self, campo) is None)
        if nulos:
            raise ValueError(f"no pueden ser null: {', '.join(nulos)}")
        return self
