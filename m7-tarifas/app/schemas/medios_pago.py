"""Esquemas de los medios de pago del cliente (RF-7.2), con los nombres y los campos
del contrato."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.paginacion import Pagina
from app.schemas.comunes import Cambios, MetodoPago

Alias = Annotated[str, Field(min_length=1, max_length=50)]


class MedioPagoNuevo(BaseModel):
    """Una tarjeta o billetera virtual necesita `token_pasarela`; el efectivo no lo lleva."""

    model_config = ConfigDict(extra="forbid")

    cliente_id: uuid.UUID
    tipo: MetodoPago
    # Lo que devuelve la pasarela cuando la aplicación le da la tarjeta o la
    # billetera. M7 nunca recibe el número de la tarjeta (RNF-19).
    token_pasarela: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    # Últimos 4 dígitos de la tarjeta, para que el cliente la reconozca.
    ultimos_4: Annotated[str, Field(pattern=r"^[0-9]{4}$")] | None = None
    # Nombre que le pone el cliente, por ejemplo "Visa del trabajo".
    alias: Alias | None = None
    predeterminado: bool = False

    @model_validator(mode="after")
    def _segun_el_tipo(self):
        if self.tipo == "efectivo":
            if self.token_pasarela is not None or self.ultimos_4 is not None:
                raise ValueError("el efectivo no lleva token_pasarela ni ultimos_4")
        elif self.token_pasarela is None:
            raise ValueError("una tarjeta o billetera virtual necesita token_pasarela")
        return self


class MedioPagoCambios(Cambios):
    """Para dejar de usar un medio como predeterminado, se elige otro."""

    predeterminado: Literal[True] | None = None
    alias: Alias | None = None


class MedioPago(BaseModel):
    """Nunca lleva el token de la pasarela."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cliente_id: uuid.UUID
    tipo: MetodoPago
    ultimos_4: str | None = None
    alias: str | None = None
    predeterminado: bool
    creado_en: datetime


class PaginaMediosPago(Pagina[MedioPago]):
    """Página de medios de pago."""
