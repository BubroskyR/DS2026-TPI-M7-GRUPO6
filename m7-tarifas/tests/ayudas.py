"""Datos y pasos que repiten varias pruebas."""

REGLAS = "/api/v1/tarifas/reglas"
REGLA_AUTO = {
    "tipo_vehiculo": "auto",
    "tarifa_base": 500,
    "precio_por_km": 150,
    "precio_por_minuto": 20,
    "tarifa_minima": 1000,
    "cargo_cancelacion": 800,
}


def crear_regla(cliente, **cambios) -> dict:
    """Crea una regla de tarifa (la de auto, con los cambios que se pasen) y la devuelve."""
    respuesta = cliente.post(REGLAS, json={**REGLA_AUTO, **cambios})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()
