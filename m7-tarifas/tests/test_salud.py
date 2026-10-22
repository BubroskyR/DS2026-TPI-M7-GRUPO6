from app.core import db


def test_health_responde_ok_si_la_base_esta_disponible(cliente):
    respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_health_responde_503_si_la_base_no_responde(cliente, monkeypatch):
    monkeypatch.setattr(db, "base_disponible", lambda: False)

    respuesta = cliente.get("/health")

    assert respuesta.status_code == 503
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.headers["Retry-After"] == "5"
    assert respuesta.json() == {
        "type": "about:blank",
        "title": "Servicio no disponible",
        "status": 503,
    }
