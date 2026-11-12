"""Pago de un viaje (RF-7.2, RF-7.3, RF-7.6) y su historial (RF-7.7)."""

import uuid

from app.services import pasarela
from tests.ayudas import (
    PAGOS,
    TOTAL_DEL_VIAJE,
    avisar,
    crear_regla,
    nueva_clave,
    pagar,
    pedido_de_pago,
    registrar_medio,
    viaje_terminado,
)


def movimientos(cliente, pago_id) -> list[dict]:
    respuesta = cliente.get(f"{PAGOS}/{pago_id}/movimientos")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["items"]


def test_un_pago_en_efectivo_queda_aprobado_en_el_acto(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente), metodo="efectivo")

    respuesta = cliente.post(PAGOS, json=pedido, headers=nueva_clave())

    assert respuesta.status_code == 201, respuesta.text
    pago = respuesta.json()
    assert respuesta.headers["Location"] == f"{PAGOS}/{pago['id']}"
    assert pago["concepto"] == "viaje"
    assert pago["viaje_id"] == pedido["viaje_id"]
    assert pago["cliente_id"] == pedido["cliente_id"]
    assert pago["beneficiario_id"] == pedido["beneficiario_id"]
    assert pago["monto"] == TOTAL_DEL_VIAJE
    assert pago["monto_reembolsado"] == 0
    assert pago["moneda"] == "ARS"
    assert pago["metodo"] == "efectivo"
    assert pago["estado"] == "aprobado"
    assert pago["creado_en"].endswith(("Z", "+00:00"))
    # Los campos que no tiene no van en la respuesta: el contrato no admite null.
    assert "reserva_id" not in pago
    assert "referencia_externa" not in pago


def test_con_tarjeta_queda_pendiente_hasta_el_aviso_de_la_pasarela(cliente):
    crear_regla(cliente)

    pago = pagar(cliente, metodo="tarjeta")

    assert pago["estado"] == "pendiente"
    assert pago["metodo"] == "tarjeta"
    assert pago["referencia_externa"]


def test_sin_metodo_usa_el_medio_predeterminado_del_cliente(cliente):
    crear_regla(cliente)
    cliente_id = str(uuid.uuid4())
    registrar_medio(cliente, cliente_id, tipo="tarjeta")
    billetera = registrar_medio(cliente, cliente_id, tipo="billetera_virtual", predeterminado=True)

    pago = pagar(cliente, cliente_id=cliente_id)

    assert billetera["predeterminado"] is True
    assert pago["metodo"] == "billetera_virtual"
    assert pago["estado"] == "pendiente"


def test_sin_metodo_y_sin_medios_registrados_se_paga_en_efectivo(cliente):
    crear_regla(cliente)

    pago = pagar(cliente)

    assert pago["metodo"] == "efectivo"
    assert pago["estado"] == "aprobado"


def test_el_metodo_del_pedido_le_gana_al_predeterminado(cliente):
    crear_regla(cliente)
    cliente_id = str(uuid.uuid4())
    registrar_medio(cliente, cliente_id, tipo="tarjeta")

    pago = pagar(cliente, cliente_id=cliente_id, metodo="efectivo")

    assert pago["metodo"] == "efectivo"
    assert pago["estado"] == "aprobado"


def test_un_viaje_sin_tarifa_final_responde_422(cliente):
    crear_regla(cliente)

    respuesta = cliente.post(PAGOS, json=pedido_de_pago(str(uuid.uuid4())), headers=nueva_clave())

    assert respuesta.status_code == 422
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.json()["type"] == "/errores/viaje-sin-tarifa-final"


def test_un_monto_distinto_de_la_tarifa_final_responde_422(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente), monto=2000)

    respuesta = cliente.post(PAGOS, json=pedido, headers=nueva_clave())

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/monto-distinto-de-la-tarifa"
    assert cliente.get(PAGOS).json()["total_elementos"] == 0


def test_un_segundo_pago_del_mismo_viaje_responde_409(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente))
    cliente.post(PAGOS, json=pedido, headers=nueva_clave())

    respuesta = cliente.post(PAGOS, json=pedido, headers=nueva_clave())

    assert respuesta.status_code == 409
    assert respuesta.json()["type"] == "/errores/pago-ya-registrado"
    assert cliente.get(PAGOS).json()["total_elementos"] == 1


def test_si_la_pasarela_rechazo_el_pago_se_puede_registrar_otro(cliente):
    crear_regla(cliente)
    rechazado = pagar(cliente, metodo="tarjeta")
    avisar(cliente, rechazado, "rechazado")
    pedido = pedido_de_pago(
        rechazado["viaje_id"],
        cliente_id=rechazado["cliente_id"],
        beneficiario_id=rechazado["beneficiario_id"],
        metodo="efectivo",
    )

    respuesta = cliente.post(PAGOS, json=pedido, headers=nueva_clave())

    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "aprobado"


def test_la_misma_idempotency_key_devuelve_el_pago_original_con_200(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente))
    clave = nueva_clave()
    original = cliente.post(PAGOS, json=pedido, headers=clave)

    repetido = cliente.post(PAGOS, json=pedido, headers=clave)

    assert repetido.status_code == 200
    assert repetido.json() == original.json()
    assert "Location" not in repetido.headers
    assert cliente.get(PAGOS).json()["total_elementos"] == 1
    # Tampoco se repite el historial.
    assert len(movimientos(cliente, original.json()["id"])) == 2


def test_la_misma_idempotency_key_con_otro_cuerpo_responde_422(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente))
    clave = nueva_clave()
    cliente.post(PAGOS, json=pedido, headers=clave)

    respuesta = cliente.post(PAGOS, json={**pedido, "metodo": "tarjeta"}, headers=clave)

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/idempotency-key-con-otro-cuerpo"


def test_sin_idempotency_key_responde_400(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente))

    sin_clave = cliente.post(PAGOS, json=pedido)
    clave_vacia = cliente.post(PAGOS, json=pedido, headers={"Idempotency-Key": ""})

    assert sin_clave.status_code == 400
    assert clave_vacia.status_code == 400


def test_un_pedido_con_formato_invalido_responde_400(cliente):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente))
    invalidos = [
        {**pedido, "monto": 0},
        {**pedido, "monto": 2090.001},
        {**pedido, "metodo": "cheque"},
        {**pedido, "viaje_id": "viaje-1"},
        {**pedido, "campo_que_no_existe": 1},
        {k: v for k, v in pedido.items() if k != "beneficiario_id"},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.post(PAGOS, json=cuerpo, headers=nueva_clave())

        assert respuesta.status_code == 400, cuerpo


def test_si_la_pasarela_no_responde_responde_503_y_no_cobra(cliente, monkeypatch):
    crear_regla(cliente)
    pedido = pedido_de_pago(viaje_terminado(cliente), metodo="tarjeta")
    clave = nueva_clave()

    def pasarela_caida(*args):
        raise pasarela.PasarelaNoDisponible()

    with monkeypatch.context() as cambios:
        cambios.setattr(pasarela, "pedir_cobro", pasarela_caida)
        respuesta = cliente.post(PAGOS, json=pedido, headers=clave)

    assert respuesta.status_code == 503
    assert respuesta.headers["Retry-After"] == "5"
    assert respuesta.json()["type"] == "/errores/pasarela-no-disponible"
    assert cliente.get(PAGOS).json()["total_elementos"] == 0
    # Cuando la pasarela vuelve, se reintenta con la misma clave.
    reintento = cliente.post(PAGOS, json=pedido, headers=clave)
    assert reintento.status_code == 201
    assert reintento.json()["estado"] == "pendiente"


def test_consultar_un_pago(cliente):
    crear_regla(cliente)
    pago = pagar(cliente)

    respuesta = cliente.get(f"{PAGOS}/{pago['id']}")

    assert respuesta.status_code == 200
    assert respuesta.json() == pago


def test_consultar_un_pago_que_no_existe_responde_404(cliente):
    respuesta = cliente.get(f"{PAGOS}/{uuid.uuid4()}")
    no_es_uuid = cliente.get(f"{PAGOS}/pago-1")

    assert respuesta.status_code == 404
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert no_es_uuid.status_code == 400


def test_listar_pagos_con_filtros(cliente):
    crear_regla(cliente)
    en_efectivo = pagar(cliente, metodo="efectivo")
    con_tarjeta = pagar(cliente, metodo="tarjeta")

    todos = cliente.get(PAGOS).json()
    del_viaje = cliente.get(PAGOS, params={"viaje_id": con_tarjeta["viaje_id"]}).json()
    del_cliente = cliente.get(PAGOS, params={"cliente_id": en_efectivo["cliente_id"]}).json()
    del_conductor = cliente.get(
        PAGOS, params={"beneficiario_id": con_tarjeta["beneficiario_id"]}
    ).json()
    pendientes = cliente.get(PAGOS, params={"estado": "pendiente"}).json()

    assert [p["id"] for p in todos["items"]] == [en_efectivo["id"], con_tarjeta["id"]]
    assert todos["total_elementos"] == 2
    assert [p["id"] for p in del_viaje["items"]] == [con_tarjeta["id"]]
    assert [p["id"] for p in del_cliente["items"]] == [en_efectivo["id"]]
    assert [p["id"] for p in del_conductor["items"]] == [con_tarjeta["id"]]
    assert [p["id"] for p in pendientes["items"]] == [con_tarjeta["id"]]


def test_listar_pagos_es_paginado(cliente):
    crear_regla(cliente)
    for _ in range(3):
        pagar(cliente)

    pagina = cliente.get(PAGOS, params={"page": 1, "size": 2}).json()
    estado_invalido = cliente.get(PAGOS, params={"estado": "cobrado"})

    assert len(pagina["items"]) == 1
    assert pagina["total_elementos"] == 3
    assert pagina["total_paginas"] == 2
    assert estado_invalido.status_code == 400


def test_el_historial_de_un_pago_en_efectivo(cliente):
    crear_regla(cliente)
    pago = pagar(cliente)

    historial = movimientos(cliente, pago["id"])

    assert [m["tipo"] for m in historial] == ["registro", "aprobacion"]
    for movimiento in historial:
        assert movimiento["pago_id"] == pago["id"]
        assert movimiento["monto"] == TOTAL_DEL_VIAJE
        # Las pruebas corren sin token: lo hace el usuario de desarrollo.
        assert movimiento["actor"] == "sin-autenticacion"


def test_el_historial_de_un_pago_que_no_existe_responde_404(cliente):
    respuesta = cliente.get(f"{PAGOS}/{uuid.uuid4()}/movimientos")

    assert respuesta.status_code == 404
