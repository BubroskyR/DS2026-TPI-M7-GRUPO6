"""Reembolsos totales o parciales de un pago (RF-7.5)."""

import uuid

from tests.ayudas import PAGOS, avisar, crear_regla, nueva_clave, pagar, pagar_aprobado


def reembolsos(pago_id) -> str:
    return f"{PAGOS}/{pago_id}/reembolsos"


def reembolsar(cliente, pago_id, **datos):
    return cliente.post(
        reembolsos(pago_id), json={"motivo": "Ajuste por desvío", **datos}, headers=nueva_clave()
    )


def test_un_reembolso_parcial(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)

    respuesta = reembolsar(cliente, pago["id"], monto=500)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.headers["Location"] == reembolsos(pago["id"])
    reembolso = respuesta.json()
    assert reembolso["pago_id"] == pago["id"]
    assert reembolso["monto"] == 500
    assert reembolso["motivo"] == "Ajuste por desvío"
    actualizado = cliente.get(f"{PAGOS}/{pago['id']}").json()
    assert actualizado["estado"] == "reembolsado_parcial"
    assert actualizado["monto_reembolsado"] == 500


def test_sin_monto_se_reembolsa_todo_lo_que_queda(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)
    reembolsar(cliente, pago["id"], monto=500.5)

    respuesta = reembolsar(cliente, pago["id"])

    assert respuesta.json()["monto"] == 1589.5
    actualizado = cliente.get(f"{PAGOS}/{pago['id']}").json()
    assert actualizado["estado"] == "reembolsado"
    assert actualizado["monto_reembolsado"] == 2090


def test_dos_parciales_que_completan_el_pago_lo_dejan_reembolsado(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente, metodo="efectivo")

    reembolsar(cliente, pago["id"], monto=1000)
    reembolsar(cliente, pago["id"], monto=1090)

    assert cliente.get(f"{PAGOS}/{pago['id']}").json()["estado"] == "reembolsado"


def test_un_monto_mayor_que_lo_que_queda_responde_422(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)
    reembolsar(cliente, pago["id"], monto=2000)

    respuesta = reembolsar(cliente, pago["id"], monto=100)

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/reembolso-mayor-que-lo-que-queda"
    assert cliente.get(f"{PAGOS}/{pago['id']}").json()["monto_reembolsado"] == 2000


def test_un_pago_que_no_esta_cobrado_no_se_reembolsa(cliente):
    crear_regla(cliente)
    pendiente = pagar(cliente, metodo="tarjeta")
    rechazado = pagar(cliente, metodo="tarjeta")
    avisar(cliente, rechazado, "rechazado")
    reembolsado = pagar_aprobado(cliente)
    reembolsar(cliente, reembolsado["id"])

    for pago in (pendiente, rechazado, reembolsado):
        respuesta = reembolsar(cliente, pago["id"], monto=1)

        assert respuesta.status_code == 409, pago["estado"]
        assert respuesta.json()["type"] == "/errores/pago-no-reembolsable"


def test_el_reembolso_queda_en_el_historial(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)

    reembolsar(cliente, pago["id"], monto=300)

    movimientos = cliente.get(f"{PAGOS}/{pago['id']}/movimientos").json()["items"]
    assert [m["tipo"] for m in movimientos] == ["registro", "aprobacion", "reembolso"]
    assert movimientos[2]["monto"] == 300
    assert movimientos[2]["detalle"] == "Ajuste por desvío"


def test_la_misma_idempotency_key_no_reembolsa_dos_veces(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)
    clave = nueva_clave()
    cuerpo = {"monto": 500, "motivo": "Reserva cancelada"}
    original = cliente.post(reembolsos(pago["id"]), json=cuerpo, headers=clave)

    repetido = cliente.post(reembolsos(pago["id"]), json=cuerpo, headers=clave)

    assert repetido.status_code == 200
    assert repetido.json() == original.json()
    assert cliente.get(f"{PAGOS}/{pago['id']}").json()["monto_reembolsado"] == 500


def test_la_misma_clave_para_otro_pago_responde_422(cliente):
    crear_regla(cliente)
    un_pago = pagar_aprobado(cliente)
    otro_pago = pagar_aprobado(cliente)
    clave = nueva_clave()
    cuerpo = {"monto": 500, "motivo": "Reserva cancelada"}
    cliente.post(reembolsos(un_pago["id"]), json=cuerpo, headers=clave)

    respuesta = cliente.post(reembolsos(otro_pago["id"]), json=cuerpo, headers=clave)

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/idempotency-key-con-otro-cuerpo"


def test_listar_los_reembolsos_de_un_pago(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)
    primero = reembolsar(cliente, pago["id"], monto=100).json()
    segundo = reembolsar(cliente, pago["id"], monto=200).json()

    respuesta = cliente.get(reembolsos(pago["id"]))

    assert respuesta.status_code == 200
    assert respuesta.json()["items"] == [primero, segundo]
    assert respuesta.json()["total_elementos"] == 2


def test_reembolsos_de_un_pago_que_no_existe_responden_404(cliente):
    pago_id = uuid.uuid4()

    reembolso = reembolsar(cliente, pago_id, monto=100)
    lista = cliente.get(reembolsos(pago_id))

    assert reembolso.status_code == 404
    assert lista.status_code == 404


def test_un_pedido_con_formato_invalido_responde_400(cliente):
    crear_regla(cliente)
    pago = pagar_aprobado(cliente)
    invalidos = [{"monto": 0, "motivo": "x"}, {"monto": 10}, {"monto": 1.234, "motivo": "x"}]

    for cuerpo in invalidos:
        respuesta = cliente.post(reembolsos(pago["id"]), json=cuerpo, headers=nueva_clave())

        assert respuesta.status_code == 400, cuerpo
