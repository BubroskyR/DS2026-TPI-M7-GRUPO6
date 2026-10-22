"""Estimación y tarifa final de un viaje (RF-7.1)."""

import uuid

from tests.ayudas import crear_regla

ESTIMACIONES = "/api/v1/tarifas/estimaciones"
VIAJE_8_KM = {"tipo_vehiculo": "auto", "distancia_km": 8.2, "duracion_estimada_min": 18}
VIAJE_TERMINADO = {"tipo_vehiculo": "auto", "distancia_real_km": 8.2, "duracion_real_min": 18}
# Con la regla de auto de las pruebas: 500 + 150 × 8,2 + 20 × 18 = 2090.
DESGLOSE_8_KM = {
    "tarifa_base": 500,
    "cargo_distancia": 1230,
    "cargo_tiempo": 360,
    "multiplicador_demanda": 1,
    "total": 2090,
}


def tarifa_final(viaje_id) -> str:
    return f"/api/v1/tarifas/viajes/{viaje_id}/tarifa-final"


def test_estimar_con_la_regla_activa(cliente):
    regla = crear_regla(cliente)

    respuesta = cliente.post(ESTIMACIONES, json=VIAJE_8_KM)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"regla_id": regla["id"], "moneda": "ARS", "desglose": DESGLOSE_8_KM}


def test_estimar_con_multiplicador_de_demanda(cliente):
    crear_regla(cliente)

    respuesta = cliente.post(ESTIMACIONES, json={**VIAJE_8_KM, "multiplicador_demanda": 1.5})

    assert respuesta.json()["desglose"]["multiplicador_demanda"] == 1.5
    assert respuesta.json()["desglose"]["total"] == 3135


def test_estimar_usa_la_regla_del_tipo_de_vehiculo(cliente):
    crear_regla(cliente)
    de_moto = crear_regla(cliente, tipo_vehiculo="moto", tarifa_base=300)

    respuesta = cliente.post(ESTIMACIONES, json={**VIAJE_8_KM, "tipo_vehiculo": "moto"})

    assert respuesta.json()["regla_id"] == de_moto["id"]
    assert respuesta.json()["desglose"]["tarifa_base"] == 300


def test_estimar_sin_regla_activa_responde_422(cliente):
    crear_regla(cliente, activa=False)

    respuesta = cliente.post(ESTIMACIONES, json=VIAJE_8_KM)

    assert respuesta.status_code == 422
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.json()["type"] == "/errores/sin-regla-activa"


def test_estimar_con_datos_invalidos_responde_400(cliente):
    crear_regla(cliente)
    invalidos = [
        {**VIAJE_8_KM, "distancia_km": 0},
        {**VIAJE_8_KM, "duracion_estimada_min": -3},
        {**VIAJE_8_KM, "multiplicador_demanda": 0.5},
        {**VIAJE_8_KM, "tipo_vehiculo": "camion"},
        {**VIAJE_8_KM, "fecha_hora": "mañana"},
        {**VIAJE_8_KM, "campo_que_no_existe": 1},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.post(ESTIMACIONES, json=cuerpo)

        assert respuesta.status_code == 400, cuerpo


def test_un_precio_mas_grande_que_el_maximo_responde_422(cliente):
    # Con 1e12 km, el viaje costaría 150 billones de pesos: no entra en la base,
    # donde los importes llegan hasta 9.999.999.999,99.
    crear_regla(cliente)
    viaje_id = uuid.uuid4()

    for distancia in (1e12, 1e300):
        estimacion = cliente.post(ESTIMACIONES, json={**VIAJE_8_KM, "distancia_km": distancia})
        final = cliente.post(
            tarifa_final(viaje_id), json={**VIAJE_TERMINADO, "distancia_real_km": distancia}
        )

        for respuesta in (estimacion, final):
            assert respuesta.status_code == 422, (distancia, respuesta.text)
            assert respuesta.json()["type"] == "/errores/importe-demasiado-grande"
    assert cliente.get(tarifa_final(viaje_id)).status_code == 404


def test_la_estimacion_no_se_guarda(cliente):
    crear_regla(cliente)
    viaje_id = uuid.uuid4()

    cliente.post(ESTIMACIONES, json=VIAJE_8_KM)

    assert cliente.get(tarifa_final(viaje_id)).status_code == 404


def test_registrar_la_tarifa_final_responde_201(cliente):
    regla = crear_regla(cliente)
    viaje_id = str(uuid.uuid4())

    respuesta = cliente.post(tarifa_final(viaje_id), json=VIAJE_TERMINADO)

    assert respuesta.status_code == 201
    assert respuesta.headers["Location"] == tarifa_final(viaje_id)
    cuerpo = respuesta.json()
    assert cuerpo["viaje_id"] == viaje_id
    assert cuerpo["regla_id"] == regla["id"]
    assert cuerpo["moneda"] == "ARS"
    assert cuerpo["desglose"] == DESGLOSE_8_KM
    assert cuerpo["calculada_en"].endswith(("Z", "+00:00"))


def test_consultar_la_tarifa_final_devuelve_la_registrada(cliente):
    crear_regla(cliente)
    viaje_id = uuid.uuid4()
    registrada = cliente.post(tarifa_final(viaje_id), json=VIAJE_TERMINADO).json()

    respuesta = cliente.get(tarifa_final(viaje_id))

    assert respuesta.status_code == 200
    assert respuesta.json() == registrada


def test_la_tarifa_final_guarda_el_multiplicador_con_el_que_se_calculo(cliente):
    crear_regla(cliente)
    viaje_id = uuid.uuid4()
    registrada = cliente.post(
        tarifa_final(viaje_id), json={**VIAJE_TERMINADO, "multiplicador_demanda": 1.23456}
    ).json()

    consultada = cliente.get(tarifa_final(viaje_id)).json()

    assert consultada["desglose"]["multiplicador_demanda"] == 1.23456
    assert consultada == registrada


def test_la_tarifa_final_no_cambia_si_despues_cambia_la_regla(cliente):
    regla = crear_regla(cliente)
    viaje_id = uuid.uuid4()
    cliente.post(tarifa_final(viaje_id), json=VIAJE_TERMINADO)

    cliente.patch(f"/api/v1/tarifas/reglas/{regla['id']}", json={"tarifa_base": 900})

    assert cliente.get(tarifa_final(viaje_id)).json()["desglose"]["total"] == 2090


def test_una_segunda_tarifa_final_del_mismo_viaje_responde_409(cliente):
    crear_regla(cliente)
    viaje_id = uuid.uuid4()
    cliente.post(tarifa_final(viaje_id), json=VIAJE_TERMINADO)

    respuesta = cliente.post(
        tarifa_final(viaje_id), json={**VIAJE_TERMINADO, "distancia_real_km": 20}
    )

    assert respuesta.status_code == 409
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert cliente.get(tarifa_final(viaje_id)).json()["desglose"]["total"] == 2090


def test_tarifa_final_sin_regla_activa_responde_422(cliente):
    respuesta = cliente.post(tarifa_final(uuid.uuid4()), json=VIAJE_TERMINADO)

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/sin-regla-activa"


def test_tarifa_final_de_un_viaje_sin_tarifa_responde_404(cliente):
    respuesta = cliente.get(tarifa_final(uuid.uuid4()))

    assert respuesta.status_code == 404


def test_tarifa_final_con_datos_invalidos_responde_400(cliente):
    crear_regla(cliente)

    sin_distancia = cliente.post(
        tarifa_final(uuid.uuid4()), json={"tipo_vehiculo": "auto", "duracion_real_min": 18}
    )
    viaje_que_no_es_uuid = cliente.post(tarifa_final("viaje-1"), json=VIAJE_TERMINADO)

    assert sin_distancia.status_code == 400
    assert viaje_que_no_es_uuid.status_code == 400
