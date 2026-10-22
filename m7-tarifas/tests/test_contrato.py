"""Cada operación de la API tiene que estar en el contrato oficial (RNF-03)."""

from pathlib import Path

import pytest
import yaml

from app.main import app

# El repo de la cátedra está en el submódulo `contratos`, y adentro el
# contrato de M7 está en contratos/m7_tarifas/openapi.yml.
CONTRATO = (
    Path(__file__).resolve().parents[2] / "contratos" / "contratos" / "m7_tarifas" / "openapi.yml"
)
METODOS = {"get", "post", "put", "patch", "delete"}


def _operaciones(paths: dict) -> set[tuple[str, str, str]]:
    return {
        (ruta, metodo.upper(), operacion["operationId"])
        for ruta, item in paths.items()
        for metodo, operacion in item.items()
        if metodo in METODOS
    }


def test_cada_operacion_de_la_api_esta_en_el_contrato():
    if not CONTRATO.exists():
        pytest.skip("Falta el submódulo de contratos: git submodule update --init")
    contrato = yaml.safe_load(CONTRATO.read_text(encoding="utf-8"))
    del_contrato = _operaciones(contrato.get("paths") or {})
    if not del_contrato:
        pytest.skip("El contrato del submódulo todavía no tiene rutas: falta que se acepte su PR")

    sobrantes = _operaciones(app.openapi()["paths"]) - del_contrato

    assert not sobrantes, f"Operaciones que no están en el contrato: {sorted(sobrantes)}"
