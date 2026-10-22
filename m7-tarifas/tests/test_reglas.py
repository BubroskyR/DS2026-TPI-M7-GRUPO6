"""Reglas de tarifa (RF-7.1): crear, listar, consultar y modificar."""

import uuid

from tests.ayudas import REGLA_AUTO, REGLAS, crear_regla


def test_crear_regla_responde_201_con_la_regla_y_su_ubicacion(cliente):
    respuesta = cliente.post(REGLAS, json=REGLA_AUTO)

    assert respuesta.status_code == 201
    regla = respuesta.json()
    assert uuid.UUID(regla["id"])
    assert respuesta.headers["Location"] == f"{REGLAS}/{regla['id']}"
    assert regla == {**REGLA_AUTO, "id": regla["id"], "activa": True}


def test_los_importes_salen_como_numeros_en_json(cliente):
    regla = crear_regla(cliente, tarifa_base=500.5)

    assert regla["tarifa_base"] == 500.5
    assert isinstance(regla["tarifa_base"], float)


def test_sin_cargo_de_cancelacion_queda_en_cero(cliente):
    sin_cargo = {
        campo: valor for campo, valor in REGLA_AUTO.items() if campo != "cargo_cancelacion"
    }

    respuesta = cliente.post(REGLAS, json=sin_cargo)

    assert respuesta.json()["cargo_cancelacion"] == 0


def test_una_regla_activa_nueva_desactiva_la_anterior_del_mismo_tipo(cliente):
    vieja = crear_regla(cliente)
    de_moto = crear_regla(cliente, tipo_vehiculo="moto")

    nueva = crear_regla(cliente, tarifa_base=600)

    assert nueva["activa"] is True
    assert cliente.get(f"{REGLAS}/{vieja['id']}").json()["activa"] is False
    assert cliente.get(f"{REGLAS}/{de_moto['id']}").json()["activa"] is True


def test_una_regla_inactiva_nueva_no_cambia_la_activa(cliente):
    activa = crear_regla(cliente)

    crear_regla(cliente, activa=False)

    assert cliente.get(f"{REGLAS}/{activa['id']}").json()["activa"] is True


def test_crear_regla_con_datos_invalidos_responde_400(cliente):
    invalidos = [
        {**REGLA_AUTO, "tipo_vehiculo": "camion"},
        {**REGLA_AUTO, "tarifa_base": -1},
        {**REGLA_AUTO, "precio_por_km": 150.555},
        # Más de lo que entra en la base: los importes llegan hasta 9.999.999.999,99.
        {**REGLA_AUTO, "tarifa_base": 1e10},
        {**REGLA_AUTO, "campo_que_no_existe": 1},
        {campo: valor for campo, valor in REGLA_AUTO.items() if campo != "tarifa_minima"},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.post(REGLAS, json=cuerpo)

        assert respuesta.status_code == 400, cuerpo
        assert respuesta.headers["content-type"] == "application/problem+json"


def test_consultar_una_regla(cliente):
    regla = crear_regla(cliente)

    respuesta = cliente.get(f"{REGLAS}/{regla['id']}")

    assert respuesta.status_code == 200
    assert respuesta.json() == regla


def test_consultar_una_regla_que_no_existe_responde_404(cliente):
    respuesta = cliente.get(f"{REGLAS}/{uuid.uuid4()}")

    assert respuesta.status_code == 404
    assert respuesta.headers["content-type"] == "application/problem+json"


def test_un_id_que_no_es_uuid_responde_400(cliente):
    respuesta = cliente.get(f"{REGLAS}/no-es-un-uuid")

    assert respuesta.status_code == 400


def test_listar_reglas_pagina_y_filtra(cliente):
    vieja_de_auto = crear_regla(cliente)
    activa_de_auto = crear_regla(cliente, tarifa_base=600)
    de_moto = crear_regla(cliente, tipo_vehiculo="moto")

    de_auto = cliente.get(REGLAS, params={"tipo_vehiculo": "auto"}).json()
    activas = cliente.get(REGLAS, params={"solo_activas": "true"}).json()
    primera_pagina = cliente.get(REGLAS, params={"page": 0, "size": 2}).json()
    segunda_pagina = cliente.get(REGLAS, params={"page": 1, "size": 2}).json()

    assert {r["id"] for r in de_auto["items"]} == {vieja_de_auto["id"], activa_de_auto["id"]}
    assert {r["id"] for r in activas["items"]} == {activa_de_auto["id"], de_moto["id"]}
    # Entre las dos páginas están las tres reglas, sin repetir ninguna.
    ids_por_pagina = [r["id"] for r in primera_pagina["items"] + segunda_pagina["items"]]
    assert sorted(ids_por_pagina) == sorted(
        [vieja_de_auto["id"], activa_de_auto["id"], de_moto["id"]]
    )
    assert {
        campo: segunda_pagina[campo]
        for campo in ("page", "size", "total_elementos", "total_paginas")
    } == {
        "page": 1,
        "size": 2,
        "total_elementos": 3,
        "total_paginas": 2,
    }


def test_listar_reglas_con_page_o_size_fuera_de_rango_responde_400(cliente):
    for parametros in ({"page": -1}, {"size": 0}, {"size": 101}):
        respuesta = cliente.get(REGLAS, params=parametros)

        assert respuesta.status_code == 400, parametros


def test_modificar_cambia_solo_los_campos_enviados(cliente):
    regla = crear_regla(cliente)

    respuesta = cliente.patch(f"{REGLAS}/{regla['id']}", json={"tarifa_base": 550})

    assert respuesta.status_code == 200
    assert respuesta.json() == {**regla, "tarifa_base": 550}


def test_activar_una_regla_desactiva_la_otra_del_mismo_tipo(cliente):
    inactiva = crear_regla(cliente, activa=False)
    activa = crear_regla(cliente, tarifa_base=600)

    respuesta = cliente.patch(f"{REGLAS}/{inactiva['id']}", json={"activa": True})

    assert respuesta.json()["activa"] is True
    assert cliente.get(f"{REGLAS}/{activa['id']}").json()["activa"] is False


def test_modificar_con_cambios_invalidos_responde_400(cliente):
    regla = crear_regla(cliente)
    invalidos = [
        {},
        {"tipo_vehiculo": "moto"},
        {"tarifa_base": None},
        {"tarifa_base": -5},
        {"tarifa_base": 1e10},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.patch(f"{REGLAS}/{regla['id']}", json=cuerpo)

        assert respuesta.status_code == 400, cuerpo
    assert cliente.get(f"{REGLAS}/{regla['id']}").json() == regla


def test_modificar_una_regla_que_no_existe_responde_404(cliente):
    respuesta = cliente.patch(f"{REGLAS}/{uuid.uuid4()}", json={"tarifa_base": 550})

    assert respuesta.status_code == 404
