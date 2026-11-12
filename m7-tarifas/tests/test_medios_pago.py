"""Medios de pago que registra cada cliente (RF-7.2)."""

import uuid

from tests.ayudas import MEDIOS, crear_regla, pagar, registrar_medio

CLIENTE = str(uuid.uuid4())


def medios_de(cliente, cliente_id=CLIENTE) -> list[dict]:
    respuesta = cliente.get(MEDIOS, params={"cliente_id": cliente_id})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["items"]


def test_registrar_una_tarjeta(cliente):
    respuesta = cliente.post(
        MEDIOS,
        json={
            "cliente_id": CLIENTE,
            "tipo": "tarjeta",
            "token_pasarela": "tok_visa_123",
            "ultimos_4": "4242",
            "alias": "Visa del trabajo",
        },
    )

    assert respuesta.status_code == 201, respuesta.text
    medio = respuesta.json()
    assert respuesta.headers["Location"] == f"{MEDIOS}/{medio['id']}"
    assert medio["cliente_id"] == CLIENTE
    assert medio["tipo"] == "tarjeta"
    assert medio["ultimos_4"] == "4242"
    assert medio["alias"] == "Visa del trabajo"
    assert medio["creado_en"].endswith(("Z", "+00:00"))
    # M7 nunca devuelve el token de la pasarela (RNF-19).
    assert "token_pasarela" not in medio


def test_el_primer_medio_queda_como_predeterminado(cliente):
    primero = registrar_medio(cliente, CLIENTE)
    segundo = registrar_medio(cliente, CLIENTE, tipo="billetera_virtual")

    assert primero["predeterminado"] is True
    assert segundo["predeterminado"] is False


def test_un_medio_nuevo_predeterminado_reemplaza_al_anterior(cliente):
    primero = registrar_medio(cliente, CLIENTE)

    nuevo = registrar_medio(cliente, CLIENTE, tipo="efectivo", predeterminado=True)

    assert nuevo["predeterminado"] is True
    por_id = {m["id"]: m for m in medios_de(cliente)}
    assert por_id[primero["id"]]["predeterminado"] is False


def test_el_efectivo_no_lleva_token_y_la_tarjeta_si(cliente):
    invalidos = [
        {"cliente_id": CLIENTE, "tipo": "efectivo", "token_pasarela": "tok"},
        {"cliente_id": CLIENTE, "tipo": "efectivo", "ultimos_4": "1234"},
        {"cliente_id": CLIENTE, "tipo": "tarjeta"},
        {"cliente_id": CLIENTE, "tipo": "billetera_virtual", "token_pasarela": ""},
        {"cliente_id": CLIENTE, "tipo": "tarjeta", "token_pasarela": "tok", "ultimos_4": "42"},
        {"cliente_id": CLIENTE, "tipo": "tarjeta", "token_pasarela": "tok", "alias": "x" * 51},
        {"cliente_id": CLIENTE, "tipo": "cheque"},
        {"cliente_id": CLIENTE, "tipo": "tarjeta", "token_pasarela": "tok", "numero": "4242"},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.post(MEDIOS, json=cuerpo)

        assert respuesta.status_code == 400, cuerpo
    assert medios_de(cliente) == []


def test_listar_los_medios_primero_el_predeterminado(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)
    billetera = registrar_medio(cliente, CLIENTE, tipo="billetera_virtual", predeterminado=True)
    efectivo = registrar_medio(cliente, CLIENTE, tipo="efectivo")
    registrar_medio(cliente, str(uuid.uuid4()))

    ids = [m["id"] for m in medios_de(cliente)]

    assert ids == [billetera["id"], tarjeta["id"], efectivo["id"]]
    assert cliente.get(MEDIOS).json()["total_elementos"] == 4


def test_elegir_otro_medio_como_predeterminado(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)
    billetera = registrar_medio(cliente, CLIENTE, tipo="billetera_virtual")

    respuesta = cliente.patch(f"{MEDIOS}/{billetera['id']}", json={"predeterminado": True})

    assert respuesta.status_code == 200
    assert respuesta.json()["predeterminado"] is True
    por_id = {m["id"]: m for m in medios_de(cliente)}
    assert por_id[tarjeta["id"]]["predeterminado"] is False


def test_cambiar_el_alias(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)

    respuesta = cliente.patch(f"{MEDIOS}/{tarjeta['id']}", json={"alias": "La de siempre"})

    assert respuesta.json()["alias"] == "La de siempre"
    assert respuesta.json()["predeterminado"] is True


def test_un_cambio_invalido_responde_400(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)

    for cuerpo in ({}, {"predeterminado": False}, {"alias": None}, {"tipo": "efectivo"}):
        respuesta = cliente.patch(f"{MEDIOS}/{tarjeta['id']}", json=cuerpo)

        assert respuesta.status_code == 400, cuerpo


def test_dar_de_baja_un_medio(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)
    billetera = registrar_medio(cliente, CLIENTE, tipo="billetera_virtual")

    respuesta = cliente.delete(f"{MEDIOS}/{tarjeta['id']}")

    assert respuesta.status_code == 204
    assert respuesta.content == b""
    # Se dio de baja el predeterminado: el cliente queda sin predeterminado.
    assert medios_de(cliente) == [billetera]


def test_sin_predeterminado_los_viajes_se_pagan_en_efectivo(cliente):
    crear_regla(cliente)
    tarjeta = registrar_medio(cliente, CLIENTE)
    cliente.delete(f"{MEDIOS}/{tarjeta['id']}")

    pago = pagar(cliente, cliente_id=CLIENTE)

    assert pago["metodo"] == "efectivo"


def test_dar_de_baja_dos_veces_no_es_un_error(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)
    cliente.delete(f"{MEDIOS}/{tarjeta['id']}")

    respuesta = cliente.delete(f"{MEDIOS}/{tarjeta['id']}")

    assert respuesta.status_code == 204


def test_un_medio_dado_de_baja_no_se_cambia(cliente):
    tarjeta = registrar_medio(cliente, CLIENTE)
    cliente.delete(f"{MEDIOS}/{tarjeta['id']}")

    respuesta = cliente.patch(f"{MEDIOS}/{tarjeta['id']}", json={"predeterminado": True})

    assert respuesta.status_code == 404


def test_un_medio_que_no_existe_responde_404(cliente):
    medio_id = uuid.uuid4()

    cambio = cliente.patch(f"{MEDIOS}/{medio_id}", json={"alias": "x"})
    baja = cliente.delete(f"{MEDIOS}/{medio_id}")

    assert cambio.status_code == 404
    assert baja.status_code == 404


def test_despues_de_una_baja_el_proximo_medio_queda_predeterminado(cliente):
    # Si no le queda ningún medio, el próximo vuelve a ser "el primero".
    tarjeta = registrar_medio(cliente, CLIENTE)
    cliente.delete(f"{MEDIOS}/{tarjeta['id']}")

    nueva = registrar_medio(cliente, CLIENTE)

    assert nueva["predeterminado"] is True
