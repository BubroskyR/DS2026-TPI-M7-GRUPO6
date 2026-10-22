import re

from sqlalchemy.exc import OperationalError

from app.core import db


def test_devuelve_el_x_request_id_recibido(cliente):
    respuesta = cliente.get("/health", headers={"X-Request-Id": "viaje-123.abc_9"})

    assert respuesta.headers["X-Request-Id"] == "viaje-123.abc_9"


def test_genera_un_x_request_id_si_no_llega_o_es_invalido(cliente):
    sin_encabezado = cliente.get("/health")
    invalido = cliente.get("/health", headers={"X-Request-Id": "con espacios"})

    for respuesta in (sin_encabezado, invalido):
        assert respuesta.status_code == 200
        assert re.fullmatch(r"[A-Za-z0-9._-]{1,128}", respuesta.headers["X-Request-Id"])
    assert invalido.headers["X-Request-Id"] != "con espacios"


def test_ruta_inexistente_responde_404_en_formato_problem_json(cliente):
    respuesta = cliente.get("/no-existe")

    assert respuesta.status_code == 404
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.json() == {"type": "about:blank", "title": "No encontrado", "status": 404}
    assert "X-Request-Id" in respuesta.headers


def test_metodo_no_admitido_responde_405_con_allow(cliente):
    respuesta = cliente.post("/health")

    assert respuesta.status_code == 405
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert "GET" in respuesta.headers["Allow"]
    assert respuesta.json()["title"] == "Método no permitido"


def test_error_inesperado_responde_500_sin_detalles(cliente, monkeypatch):
    def falla():
        raise RuntimeError("detalle interno que no se tiene que ver")

    monkeypatch.setattr(db, "base_disponible", falla)

    respuesta = cliente.get("/health", headers={"X-Request-Id": "abc"})

    assert respuesta.status_code == 500
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.headers["X-Request-Id"] == "abc"
    assert respuesta.json() == {"type": "about:blank", "title": "Error interno", "status": 500}


def test_si_la_base_se_cae_durante_la_solicitud_responde_503(cliente, monkeypatch):
    def base_caida():
        raise OperationalError("SELECT 1", {}, Exception("se perdió la conexión"))

    monkeypatch.setattr(db, "base_disponible", base_caida)

    respuesta = cliente.get("/health")

    assert respuesta.status_code == 503
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.headers["Retry-After"] == "5"
    assert respuesta.json() == {
        "type": "about:blank",
        "title": "Servicio no disponible",
        "status": 503,
    }
