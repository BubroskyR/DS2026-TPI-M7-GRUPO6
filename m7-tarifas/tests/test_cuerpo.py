"""Cuerpos de las solicitudes: solo application/json (si no, 415) y hasta 1 MiB (si no, 413)."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.cuerpo import ControlDeCuerpoMiddleware
from app.core.errores import registrar_manejadores

UN_MIB = 1024 * 1024
JSON = {"Content-Type": "application/json"}


def test_cuerpo_de_mas_de_1_mib_responde_413(cliente):
    respuesta = cliente.post("/health", content=b"x" * (UN_MIB + 1), headers=JSON)

    assert respuesta.status_code == 413
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.json() == {
        "type": "about:blank",
        "title": "Cuerpo demasiado grande",
        "status": 413,
    }
    assert "X-Request-Id" in respuesta.headers


def test_cuerpo_de_1_mib_justo_no_es_demasiado_grande(cliente):
    respuesta = cliente.post("/health", content=b"x" * UN_MIB, headers=JSON)

    # Pasa el control del cuerpo y llega a la ruta, que no admite POST.
    assert respuesta.status_code == 405


def test_cuerpo_que_no_es_json_responde_415(cliente):
    respuesta = cliente.post("/health", content=b"hola", headers={"Content-Type": "text/plain"})

    assert respuesta.status_code == 415
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.json() == {
        "type": "about:blank",
        "title": "Tipo de contenido no soportado",
        "status": 415,
    }
    assert "X-Request-Id" in respuesta.headers


def test_cuerpo_sin_content_type_responde_415(cliente):
    respuesta = cliente.post("/health", content=b"{}")

    assert respuesta.status_code == 415


def test_json_con_charset_se_acepta(cliente):
    respuesta = cliente.post(
        "/health", content=b"{}", headers={"Content-Type": "application/json; charset=utf-8"}
    )

    assert respuesta.status_code == 405


def test_post_sin_cuerpo_no_pide_content_type(cliente):
    # Por ejemplo, la anulación de una liquidación no lleva cuerpo.
    respuesta = cliente.post("/health")

    assert respuesta.status_code == 405


# Un cuerpo enviado en partes no anuncia su largo (Content-Length): el límite
# se controla mientras la ruta lo lee. Para probarlo hace falta una ruta que lea
# el cuerpo, así que se arma una app mínima con el mismo control.
def _app_que_lee_el_cuerpo() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ControlDeCuerpoMiddleware)
    registrar_manejadores(app)

    @app.post("/eco")
    def eco(datos: dict) -> dict:
        return datos

    return app


def _en_partes(contenido: bytes, tamano: int = 64 * 1024):
    for inicio in range(0, len(contenido), tamano):
        yield contenido[inicio : inicio + tamano]


def test_cuerpo_en_partes_de_mas_de_1_mib_responde_413():
    cuerpo = json.dumps({"texto": "a" * UN_MIB}).encode()

    with TestClient(_app_que_lee_el_cuerpo()) as cliente:
        respuesta = cliente.post("/eco", content=_en_partes(cuerpo), headers=JSON)

    assert respuesta.status_code == 413
    assert respuesta.headers["content-type"] == "application/problem+json"


def test_cuerpo_en_partes_dentro_del_limite_llega_completo():
    cuerpo = json.dumps({"texto": "a" * 200_000}).encode()

    with TestClient(_app_que_lee_el_cuerpo()) as cliente:
        respuesta = cliente.post("/eco", content=_en_partes(cuerpo), headers=JSON)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"texto": "a" * 200_000}
