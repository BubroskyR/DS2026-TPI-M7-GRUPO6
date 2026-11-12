"""Aviso de la pasarela de pago simulada (RF-7.3): aprueba o rechaza un pago pendiente."""

import uuid

from app.core.config import settings
from tests.ayudas import AVISO_PASARELA, PAGOS, SECRETO, avisar, crear_regla, pagar


def historial(cliente, pago_id) -> list[dict]:
    return cliente.get(f"{PAGOS}/{pago_id}/movimientos").json()["items"]


def test_la_pasarela_aprueba_un_pago_pendiente(cliente):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="tarjeta")

    respuesta = avisar(cliente, pago, "aprobado")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "aprobado"
    assert cliente.get(f"{PAGOS}/{pago['id']}").json()["estado"] == "aprobado"
    movimientos = historial(cliente, pago["id"])
    assert [m["tipo"] for m in movimientos] == ["registro", "aprobacion"]
    assert movimientos[1]["actor"] == "pasarela"


def test_la_pasarela_rechaza_un_pago_pendiente(cliente):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="billetera_virtual")

    respuesta = avisar(cliente, pago, "rechazado")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "rechazado"
    # El rechazo también queda en el historial (RF-7.7).
    assert [m["tipo"] for m in historial(cliente, pago["id"])] == ["registro", "rechazo"]


def test_un_aviso_repetido_no_cambia_nada(cliente):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="tarjeta")
    aprobado = avisar(cliente, pago, "aprobado").json()

    repetido = avisar(cliente, pago, "aprobado")
    contradictorio = avisar(cliente, pago, "rechazado")

    assert repetido.status_code == 200
    assert repetido.json() == aprobado
    assert contradictorio.json()["estado"] == "aprobado"
    assert len(historial(cliente, pago["id"])) == 2


def test_sin_el_secreto_o_con_otro_responde_401(cliente):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="tarjeta")
    aviso = {
        "referencia_externa": pago["referencia_externa"],
        "pago_id": pago["id"],
        "estado": "aprobado",
    }

    sin_secreto = cliente.post(AVISO_PASARELA, json=aviso)
    con_otro = cliente.post(AVISO_PASARELA, json=aviso, headers={"X-Webhook-Secret": "otro"})
    # Tampoco revela si el cuerpo es válido.
    cuerpo_invalido = cliente.post(AVISO_PASARELA, json={"estado": "quizas"})

    for respuesta in (sin_secreto, con_otro, cuerpo_invalido):
        assert respuesta.status_code == 401
        assert respuesta.headers["content-type"] == "application/problem+json"
    assert cliente.get(f"{PAGOS}/{pago['id']}").json()["estado"] == "pendiente"


def test_si_m7_no_tiene_secreto_configurado_responde_401(cliente, monkeypatch):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="tarjeta")
    monkeypatch.setattr(settings, "pasarela_webhook_secret", None)

    respuesta = avisar(cliente, pago)

    assert respuesta.status_code == 401


def test_el_aviso_de_un_pago_que_no_existe_responde_404(cliente):
    aviso = {"referencia_externa": "pas-1", "pago_id": str(uuid.uuid4()), "estado": "aprobado"}

    respuesta = cliente.post(AVISO_PASARELA, json=aviso, headers=SECRETO)

    assert respuesta.status_code == 404


def test_el_aviso_con_otra_referencia_responde_404(cliente):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="tarjeta")

    respuesta = avisar(cliente, {**pago, "referencia_externa": "pas-de-otro-cobro"})

    assert respuesta.status_code == 404
    assert cliente.get(f"{PAGOS}/{pago['id']}").json()["estado"] == "pendiente"


def test_un_aviso_con_formato_invalido_responde_400(cliente):
    crear_regla(cliente)
    pago = pagar(cliente, metodo="tarjeta")

    respuesta = avisar(cliente, pago, "quizas")

    assert respuesta.status_code == 400
