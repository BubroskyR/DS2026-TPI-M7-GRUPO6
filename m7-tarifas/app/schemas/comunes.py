"""Tipos que comparten varios esquemas del contrato."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, PlainSerializer, WithJsonSchema

# Los tipos de vehículo del enunciado (RF-3.2).
TipoVehiculo = Literal["auto", "moto"]
# Pesos argentinos.
Moneda = Literal["ARS"]

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
# Un número mayor que 0, como la distancia o la duración de un viaje.
Positivo = Annotated[
    Decimal, Field(gt=0), _COMO_NUMERO, WithJsonSchema({"type": "number", "exclusiveMinimum": 0})
]
# Recargo por alta demanda. Con 1 no hay recargo.
Multiplicador = Annotated[
    Decimal, Field(ge=1), _COMO_NUMERO, WithJsonSchema({"type": "number", "minimum": 1})
]
