"""Datos y pasos que repiten varias pruebas."""

import uuid

REGLAS = "/api/v1/tarifas/reglas"
PAGOS = "/api/v1/pagos"
AVISO_PASARELA = "/api/v1/pagos/webhooks/pasarela"
CARGOS = "/api/v1/cargos-cancelacion"
MEDIOS = "/api/v1/medios-pago"
LIQUIDACIONES = "/api/v1/liquidaciones"

REGLA_AUTO = {
    "tipo_vehiculo": "auto",
    "tarifa_base": 500,
    "precio_por_km": 150,
    "precio_por_minuto": 20,
    "tarifa_minima": 1000,
    "cargo_cancelacion": 800,
}
# Con la regla de auto: 500 + 150 × 8,2 + 20 × 18 = 2090 pesos.
VIAJE_TERMINADO = {"tipo_vehiculo": "auto", "distancia_real_km": 8.2, "duracion_real_min": 18}
TOTAL_DEL_VIAJE = 2090
# El secreto de la pasarela simulada en las pruebas (conftest.py).
SECRETO = {"X-Webhook-Secret": "secreto-de-prueba"}


def crear_regla(cliente, **cambios) -> dict:
    """Crea una regla de tarifa (la de auto, con los cambios que se pasen) y la devuelve."""
    respuesta = cliente.post(REGLAS, json={**REGLA_AUTO, **cambios})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def nueva_clave() -> dict:
    """Encabezado con una Idempotency-Key nueva."""
    return {"Idempotency-Key": str(uuid.uuid4())}


def viaje_terminado(cliente, **cambios) -> str:
    """Registra la tarifa final de un viaje nuevo (2090 pesos) y devuelve su id.
    Necesita una regla activa de auto."""
    viaje_id = str(uuid.uuid4())
    respuesta = cliente.post(
        f"/api/v1/tarifas/viajes/{viaje_id}/tarifa-final", json={**VIAJE_TERMINADO, **cambios}
    )
    assert respuesta.status_code == 201, respuesta.text
    return viaje_id


def pedido_de_pago(viaje_id: str, **cambios) -> dict:
    """El cuerpo de un pago de 2090 pesos, con un cliente y un conductor nuevos."""
    return {
        "viaje_id": viaje_id,
        "cliente_id": str(uuid.uuid4()),
        "beneficiario_id": str(uuid.uuid4()),
        "monto": TOTAL_DEL_VIAJE,
        **cambios,
    }


def pagar(cliente, **cambios) -> dict:
    """Termina un viaje nuevo y registra su pago. Devuelve el pago."""
    pedido = pedido_de_pago(viaje_terminado(cliente), **cambios)
    respuesta = cliente.post(PAGOS, json=pedido, headers=nueva_clave())
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def avisar(cliente, pago: dict, estado: str = "aprobado"):
    """La pasarela simulada avisa el resultado del cobro de `pago`."""
    aviso = {
        "referencia_externa": pago["referencia_externa"],
        "pago_id": pago["id"],
        "estado": estado,
    }
    return cliente.post(AVISO_PASARELA, json=aviso, headers=SECRETO)


def pagar_aprobado(cliente, metodo: str = "tarjeta", **cambios) -> dict:
    """Un pago ya cobrado: en efectivo queda aprobado en el acto; con tarjeta o
    billetera, después del aviso de la pasarela."""
    pago = pagar(cliente, metodo=metodo, **cambios)
    if pago["estado"] == "pendiente":
        respuesta = avisar(cliente, pago)
        assert respuesta.status_code == 200, respuesta.text
        pago = respuesta.json()
    assert pago["estado"] == "aprobado"
    return pago


def registrar_medio(cliente, cliente_id: str, tipo: str = "tarjeta", **cambios) -> dict:
    """Registra un medio de pago del cliente y lo devuelve."""
    medio = {"cliente_id": cliente_id, "tipo": tipo, **cambios}
    if tipo != "efectivo":
        medio.setdefault("token_pasarela", f"tok-{uuid.uuid4().hex}")
    respuesta = cliente.post(MEDIOS, json=medio)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()
