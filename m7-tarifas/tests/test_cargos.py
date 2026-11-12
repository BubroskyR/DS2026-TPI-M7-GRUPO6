"""Cargo fijo por una cancelación (RF-7.4)."""

import uuid

from tests.ayudas import (
    CARGOS,
    PAGOS,
    avisar,
    crear_regla,
    nueva_clave,
    pagar_aprobado,
    registrar_medio,
)


def pedido_de_cargo(**cambios) -> dict:
    return {
        "viaje_id": str(uuid.uuid4()),
        "cliente_id": str(uuid.uuid4()),
        "tipo_vehiculo": "auto",
        "motivo": "El cliente canceló con el conductor en camino",
        **cambios,
    }


def registrar_cargo(cliente, **cambios) -> dict:
    respuesta = cliente.post(CARGOS, json=pedido_de_cargo(**cambios), headers=nueva_clave())
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_el_cargo_es_el_monto_fijo_de_la_regla_activa(cliente):
    crear_regla(cliente, cargo_cancelacion=800)
    pedido = pedido_de_cargo(metodo="tarjeta")

    respuesta = cliente.post(CARGOS, json=pedido, headers=nueva_clave())

    assert respuesta.status_code == 201, respuesta.text
    cargo = respuesta.json()
    assert respuesta.headers["Location"] == f"{PAGOS}/{cargo['id']}"
    assert cargo["concepto"] == "cargo_cancelacion"
    assert cargo["monto"] == 800
    assert cargo["metodo"] == "tarjeta"
    # Se le pide a la pasarela: queda pendiente hasta su aviso.
    assert cargo["estado"] == "pendiente"
    assert cargo["referencia_externa"]
    # Es para la plataforma: no tiene beneficiario.
    assert "beneficiario_id" not in cargo


def test_el_motivo_queda_en_el_historial(cliente):
    crear_regla(cliente)

    cargo = registrar_cargo(cliente, metodo="tarjeta")

    movimientos = cliente.get(f"{PAGOS}/{cargo['id']}/movimientos").json()["items"]
    assert [m["tipo"] for m in movimientos] == ["registro"]
    assert movimientos[0]["detalle"] == "El cliente canceló con el conductor en camino"


def test_usa_el_cargo_de_la_regla_del_tipo_de_vehiculo(cliente):
    crear_regla(cliente)
    crear_regla(cliente, tipo_vehiculo="moto", cargo_cancelacion=400)

    cargo = registrar_cargo(cliente, tipo_vehiculo="moto")

    assert cargo["monto"] == 400


def test_sin_metodo_usa_la_tarjeta_o_billetera_predeterminada(cliente):
    crear_regla(cliente)
    cliente_id = str(uuid.uuid4())
    registrar_medio(cliente, cliente_id, tipo="tarjeta")
    registrar_medio(cliente, cliente_id, tipo="billetera_virtual", predeterminado=True)

    cargo = registrar_cargo(cliente, cliente_id=cliente_id)

    assert cargo["metodo"] == "billetera_virtual"
    assert cargo["referencia_externa"]


def test_si_el_predeterminado_es_efectivo_usa_la_ultima_tarjeta_o_billetera(cliente):
    crear_regla(cliente)
    cliente_id = str(uuid.uuid4())
    registrar_medio(cliente, cliente_id, tipo="billetera_virtual")
    registrar_medio(cliente, cliente_id, tipo="tarjeta")
    registrar_medio(cliente, cliente_id, tipo="efectivo", predeterminado=True)

    cargo = registrar_cargo(cliente, cliente_id=cliente_id)

    assert cargo["metodo"] == "tarjeta"


def test_sin_tarjeta_ni_billetera_el_cargo_espera_sin_metodo(cliente):
    crear_regla(cliente)
    cliente_id = str(uuid.uuid4())
    registrar_medio(cliente, cliente_id, tipo="efectivo")

    cargo = registrar_cargo(cliente, cliente_id=cliente_id)

    assert cargo["estado"] == "pendiente"
    assert "metodo" not in cargo
    assert "referencia_externa" not in cargo


def test_cuando_el_cliente_registra_una_tarjeta_se_cobra_el_cargo_que_esperaba(cliente):
    crear_regla(cliente)
    cliente_id = str(uuid.uuid4())
    cargo = registrar_cargo(cliente, cliente_id=cliente_id)

    registrar_medio(cliente, cliente_id, tipo="tarjeta")

    cobrado = cliente.get(f"{PAGOS}/{cargo['id']}").json()
    assert cobrado["metodo"] == "tarjeta"
    assert cobrado["estado"] == "pendiente"
    assert cobrado["referencia_externa"]
    # Desde ahora, la pasarela puede avisar el resultado.
    assert avisar(cliente, cobrado).json()["estado"] == "aprobado"


def test_un_cargo_de_una_reserva(cliente):
    crear_regla(cliente)
    reserva_id = str(uuid.uuid4())

    cargo = registrar_cargo(cliente, viaje_id=None, reserva_id=reserva_id, metodo="tarjeta")

    assert cargo["reserva_id"] == reserva_id
    assert "viaje_id" not in cargo


def test_un_segundo_cargo_del_mismo_viaje_o_reserva_responde_409(cliente):
    crear_regla(cliente)
    primero = registrar_cargo(cliente, reserva_id=str(uuid.uuid4()), metodo="tarjeta")
    mismo_viaje = pedido_de_cargo(viaje_id=primero["viaje_id"])
    misma_reserva = pedido_de_cargo(reserva_id=primero["reserva_id"])

    for pedido in (mismo_viaje, misma_reserva):
        respuesta = cliente.post(CARGOS, json=pedido, headers=nueva_clave())

        assert respuesta.status_code == 409, pedido
        assert respuesta.json()["type"] == "/errores/cargo-ya-registrado"


def test_si_la_pasarela_rechazo_el_cargo_se_puede_registrar_otro(cliente):
    crear_regla(cliente)
    rechazado = registrar_cargo(cliente, metodo="tarjeta")
    avisar(cliente, rechazado, "rechazado")

    respuesta = cliente.post(
        CARGOS, json=pedido_de_cargo(viaje_id=rechazado["viaje_id"]), headers=nueva_clave()
    )

    assert respuesta.status_code == 201


def test_el_pago_del_viaje_y_su_cargo_no_se_molestan(cliente):
    # Un viaje puede tener su pago y, aparte, un cargo: son conceptos distintos.
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)

    cargo = registrar_cargo(cliente, viaje_id=pago["viaje_id"], metodo="tarjeta")

    assert cargo["viaje_id"] == pago["viaje_id"]


def test_la_misma_idempotency_key_devuelve_el_cargo_original(cliente):
    crear_regla(cliente)
    pedido = pedido_de_cargo(metodo="tarjeta")
    clave = nueva_clave()
    original = cliente.post(CARGOS, json=pedido, headers=clave)

    repetido = cliente.post(CARGOS, json=pedido, headers=clave)

    assert repetido.status_code == 200
    assert repetido.json() == original.json()


def test_sin_regla_activa_o_sin_cargo_responde_422(cliente):
    sin_regla = cliente.post(CARGOS, json=pedido_de_cargo(), headers=nueva_clave())
    crear_regla(cliente, cargo_cancelacion=0)
    sin_cargo = cliente.post(CARGOS, json=pedido_de_cargo(), headers=nueva_clave())

    assert sin_regla.status_code == 422
    assert sin_regla.json()["type"] == "/errores/sin-regla-activa"
    assert sin_cargo.status_code == 422
    assert sin_cargo.json()["type"] == "/errores/sin-cargo-de-cancelacion"


def test_un_pedido_con_formato_invalido_responde_400(cliente):
    crear_regla(cliente)
    invalidos = [
        pedido_de_cargo(viaje_id=None),
        pedido_de_cargo(metodo="efectivo"),
        pedido_de_cargo(motivo=""),
        pedido_de_cargo(motivo="x" * 501),
        pedido_de_cargo(tipo_vehiculo="camion"),
        {k: v for k, v in pedido_de_cargo().items() if k != "motivo"},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.post(CARGOS, json=cuerpo, headers=nueva_clave())

        assert respuesta.status_code == 400, cuerpo
