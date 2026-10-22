"""Listas paginadas con page (desde 0) y size, como piden el contrato y la filmina DS-04."""

from dataclasses import dataclass
from math import ceil
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


@dataclass
class Paginacion:
    page: int = 0
    size: int = 20


def _leer_paginacion(
    page: Annotated[int, Query(ge=0, description="Número de página, desde 0.")] = 0,
    size: Annotated[int, Query(ge=1, le=100, description="Elementos por página.")] = 20,
) -> Paginacion:
    # Un page negativo o un size fuera de 1 a 100 responden 400.
    return Paginacion(page=page, size=size)


# Las rutas que listan lo reciben así: `paginacion: ParametrosDePagina`.
ParametrosDePagina = Annotated[Paginacion, Depends(_leer_paginacion)]


class Pagina(BaseModel, Generic[T]):
    """Esquema Pagina del contrato: los elementos de la página y los totales."""

    items: list[T]
    page: int
    size: int
    total_elementos: int
    total_paginas: int


def paginar(sesion: Session, consulta: Select, paginacion: Paginacion) -> dict:
    """Devuelve una página de `consulta`, con los datos del esquema Pagina.

    La consulta tiene que tener un orden fijo (order_by): si no, una misma
    fila podría aparecer en dos páginas.
    """
    total = sesion.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    desde = paginacion.page * paginacion.size
    items = sesion.scalars(consulta.offset(desde).limit(paginacion.size)).all()
    return {
        "items": list(items),
        "page": paginacion.page,
        "size": paginacion.size,
        "total_elementos": total,
        "total_paginas": ceil(total / paginacion.size),
    }
