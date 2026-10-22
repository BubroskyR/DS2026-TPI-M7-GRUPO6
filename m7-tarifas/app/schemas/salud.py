from typing import Literal

from pydantic import BaseModel


class Salud(BaseModel):
    """Esquema Salud del contrato."""

    status: Literal["ok"]
