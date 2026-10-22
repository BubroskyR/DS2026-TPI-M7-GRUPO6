"""Listas paginadas con page (desde 0) y size, como piden el contrato y la filmina DS-04."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core import db
from app.core.paginacion import Paginacion, paginar


class _TablasDePrueba(DeclarativeBase):
    """Tablas que existen solo para estas pruebas."""


class Numero(_TablasDePrueba):
    __tablename__ = "numeros_de_prueba"

    valor: Mapped[int] = mapped_column(primary_key=True)


@pytest.fixture
def del_1_al_45():
    """Consulta de los números del 1 al 45, ordenados."""
    _TablasDePrueba.metadata.create_all(db.engine)
    with db.SesionLocal() as sesion:
        sesion.execute(delete(Numero))
        sesion.add_all(Numero(valor=n) for n in range(1, 46))
        sesion.commit()
    return select(Numero.valor).order_by(Numero.valor)


def test_primera_pagina(sesion, del_1_al_45):
    pagina = paginar(sesion, del_1_al_45, Paginacion(page=0, size=20))

    assert pagina == {
        "items": list(range(1, 21)),
        "page": 0,
        "size": 20,
        "total_elementos": 45,
        "total_paginas": 3,
    }


def test_ultima_pagina_incompleta(sesion, del_1_al_45):
    pagina = paginar(sesion, del_1_al_45, Paginacion(page=2, size=20))

    assert pagina["items"] == [41, 42, 43, 44, 45]
    assert pagina["total_paginas"] == 3


def test_total_de_paginas_cuando_la_ultima_queda_justa(sesion, del_1_al_45):
    hasta_el_40 = del_1_al_45.where(Numero.valor <= 40)

    pagina = paginar(sesion, hasta_el_40, Paginacion(page=1, size=20))

    assert pagina["items"] == list(range(21, 41))
    assert pagina["total_elementos"] == 40
    assert pagina["total_paginas"] == 2


def test_pagina_despues_de_la_ultima_viene_vacia(sesion, del_1_al_45):
    pagina = paginar(sesion, del_1_al_45, Paginacion(page=5, size=20))

    assert pagina["items"] == []
    assert pagina["total_elementos"] == 45
    assert pagina["total_paginas"] == 3


def test_sin_elementos_no_hay_paginas(sesion, del_1_al_45):
    ninguno = del_1_al_45.where(Numero.valor > 100)

    pagina = paginar(sesion, ninguno, Paginacion(page=0, size=20))

    assert pagina["items"] == []
    assert pagina["total_elementos"] == 0
    assert pagina["total_paginas"] == 0
