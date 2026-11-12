"""Tokens de Keycloak (RNF-12) y permisos según el rol (RF-1.3).

Estas pruebas levantan un "Keycloak de prueba": un servidor local que publica la
clave pública, como la ruta /certs del realm. Los tokens se firman acá con la
clave privada que le corresponde.
"""

import json
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.seguridad import PERMISOS
from app.services.liquidaciones import HORA_ARGENTINA
from tests.ayudas import (
    AVISO_PASARELA,
    CARGOS,
    LIQUIDACIONES,
    MEDIOS,
    PAGOS,
    REGLA_AUTO,
    REGLAS,
    SECRETO,
    VIAJE_TERMINADO,
    nueva_clave,
)

EMISOR = "http://localhost:8080/realms/ds-2026-realm"
CLAVE_PRIVADA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA_CLAVE_PRIVADA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "clave-de-prueba"
CONTRATO = (
    Path(__file__).resolve().parents[2] / "contratos" / "contratos" / "m7_tarifas" / "openapi.yml"
)


@pytest.fixture(scope="module")
def keycloak_de_prueba():
    """Publica la clave pública en formato JWKS y devuelve su URL."""
    publica = jwt.algorithms.RSAAlgorithm.to_jwk(CLAVE_PRIVADA.public_key(), as_dict=True)
    jwks = json.dumps({"keys": [{**publica, "kid": KID, "use": "sig", "alg": "RS256"}]}).encode()

    class Certs(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(jwks)

        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Certs)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}/realms/ds-2026-realm/protocol/openid-connect/certs"
    servidor.shutdown()
    servidor.server_close()
    hilo.join()


@pytest.fixture(autouse=True)
def con_tokens(monkeypatch, keycloak_de_prueba):
    """En este archivo, M7 valida los tokens contra el Keycloak de prueba."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "keycloak_issuer_uri", EMISOR)
    monkeypatch.setattr(settings, "keycloak_jwks_uri", keycloak_de_prueba)


def token(*permisos, roles=(), sub=None, clave=CLAVE_PRIVADA, **cambios) -> dict:
    """Encabezado Authorization con un token firmado, como los que emite Keycloak."""
    ahora = int(time.time())
    datos = {
        "iss": EMISOR,
        "sub": sub or str(uuid.uuid4()),
        "iat": ahora,
        "exp": ahora + 300,
        "scope": " ".join(("openid", *permisos)),
        "realm_access": {"roles": list(roles)},
        **cambios,
    }
    firmado = jwt.encode(datos, clave, algorithm="RS256", headers={"kid": KID})
    return {"Authorization": f"Bearer {firmado}"}


def modulo() -> dict:
    """Token de la cuenta de servicio de un módulo (sin rol de persona), con todos los permisos."""
    return token(*PERMISOS)


def pagar(cliente, cliente_id=None, beneficiario_id=None) -> dict:
    """Un módulo (M6) termina un viaje y registra su pago en efectivo."""
    viaje_id = str(uuid.uuid4())
    cliente.post(
        f"/api/v1/tarifas/viajes/{viaje_id}/tarifa-final", json=VIAJE_TERMINADO, headers=modulo()
    )
    pedido = {
        "viaje_id": viaje_id,
        "cliente_id": cliente_id or str(uuid.uuid4()),
        "beneficiario_id": beneficiario_id or str(uuid.uuid4()),
        "monto": 2090,
    }
    respuesta = cliente.post(PAGOS, json=pedido, headers={**modulo(), **nueva_clave()})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


@pytest.fixture
def con_regla(cliente):
    respuesta = cliente.post(REGLAS, json=REGLA_AUTO, headers=modulo())
    assert respuesta.status_code == 201, respuesta.text


# --- El token -----------------------------------------------------------------


def test_sin_token_responde_401(cliente):
    respuesta = cliente.get(REGLAS)

    assert respuesta.status_code == 401
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.headers["WWW-Authenticate"] == "Bearer"
    assert respuesta.json()["title"] == "No autenticado"


def test_con_un_token_valido_y_el_permiso_responde(cliente):
    respuesta = cliente.get(REGLAS, headers=token("tarifas:read"))

    assert respuesta.status_code == 200


def test_un_token_invalido_responde_401(cliente):
    ahora = int(time.time())
    invalidos = {
        "no es un token": {"Authorization": "Bearer esto-no-es-un-token"},
        "otro esquema": {"Authorization": "Basic dXN1YXJpbzpjbGF2ZQ=="},
        "vencido": token("tarifas:read", exp=ahora - 60),
        "de otro emisor": token("tarifas:read", iss="http://otro-keycloak/realms/otro"),
        "firmado con otra clave": token("tarifas:read", clave=OTRA_CLAVE_PRIVADA),
    }

    for caso, encabezado in invalidos.items():
        respuesta = cliente.get(REGLAS, headers=encabezado)

        assert respuesta.status_code == 401, caso
    assert "vencido" in cliente.get(REGLAS, headers=invalidos["vencido"]).json()["detail"]


def test_sin_el_permiso_de_la_operacion_responde_403(cliente):
    respuesta = cliente.post(REGLAS, json=REGLA_AUTO, headers=token("tarifas:read"))

    assert respuesta.status_code == 403
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert "tarifas:write" in respuesta.json()["detail"]


def test_si_keycloak_no_responde_contesta_503(cliente, monkeypatch):
    # Nadie escucha en el puerto 9: es como si Keycloak estuviera caído.
    monkeypatch.setattr(settings, "keycloak_jwks_uri", "http://127.0.0.1:9/certs")

    respuesta = cliente.get(REGLAS, headers=token("tarifas:read"))

    assert respuesta.status_code == 503
    assert respuesta.headers["Retry-After"] == "5"


def test_health_y_el_aviso_de_la_pasarela_no_usan_token(cliente, con_regla):
    pago = cliente.post(
        PAGOS,
        json={
            "viaje_id": _viaje_terminado(cliente),
            "cliente_id": str(uuid.uuid4()),
            "beneficiario_id": str(uuid.uuid4()),
            "monto": 2090,
            "metodo": "tarjeta",
        },
        headers={**modulo(), **nueva_clave()},
    ).json()
    aviso = {
        "referencia_externa": pago["referencia_externa"],
        "pago_id": pago["id"],
        "estado": "aprobado",
    }

    salud = cliente.get("/health")
    respuesta = cliente.post(AVISO_PASARELA, json=aviso, headers=SECRETO)

    assert salud.status_code == 200
    assert respuesta.status_code == 200


def test_cada_operacion_pide_el_permiso_del_contrato(cliente):
    """Para cada operación del contrato: sin token, 401; con un token que tiene
    todos los permisos menos el suyo, 403."""
    if not CONTRATO.exists():
        pytest.skip("Falta el submódulo de contratos: git submodule update --init")
    contrato = yaml.safe_load(CONTRATO.read_text(encoding="utf-8"))
    revisadas = 0

    for ruta, item in contrato["paths"].items():
        url = ruta
        for parametro in (
            "viaje_id",
            "regla_id",
            "pago_id",
            "medio_pago_id",
            "liquidacion_id",
            "beneficiario_id",
        ):
            url = url.replace(f"{{{parametro}}}", str(uuid.uuid4()))
        for metodo, operacion in item.items():
            if metodo not in {"get", "post", "patch", "delete"}:
                continue
            permisos = [
                p
                for requisito in operacion.get("security", [{"oauth2": []}])
                for p in requisito.get("oauth2", [])
            ]
            if not permisos:
                continue  # /health y el aviso de la pasarela
            (permiso,) = permisos
            otros = token(*(PERMISOS - {permiso}))
            cuerpo = {"json": {}} if metodo in {"post", "patch"} else {}

            sin_token = cliente.request(metodo, url, **cuerpo)
            sin_permiso = cliente.request(metodo, url, headers=otros, **cuerpo)

            assert sin_token.status_code == 401, (metodo, ruta)
            assert sin_permiso.status_code == 403, (metodo, ruta)
            revisadas += 1

    assert revisadas == 24


# --- Clientes: solo lo suyo ---------------------------------------------------


def test_un_cliente_solo_ve_sus_pagos(cliente, con_regla):
    yo = str(uuid.uuid4())
    mio = pagar(cliente, cliente_id=yo)
    de_otro = pagar(cliente)
    como_cliente = token("pagos:read", roles=["CLIENTE"], sub=yo)

    lista = cliente.get(PAGOS, headers=como_cliente)
    lista_de_otro = cliente.get(
        PAGOS, params={"cliente_id": de_otro["cliente_id"]}, headers=como_cliente
    )
    el_mio = cliente.get(f"{PAGOS}/{mio['id']}", headers=como_cliente)
    el_de_otro = cliente.get(f"{PAGOS}/{de_otro['id']}", headers=como_cliente)
    historial_de_otro = cliente.get(f"{PAGOS}/{de_otro['id']}/movimientos", headers=como_cliente)
    reembolsos_de_otro = cliente.get(f"{PAGOS}/{de_otro['id']}/reembolsos", headers=como_cliente)

    assert [p["id"] for p in lista.json()["items"]] == [mio["id"]]
    assert el_mio.status_code == 200
    for respuesta in (lista_de_otro, el_de_otro, historial_de_otro, reembolsos_de_otro):
        assert respuesta.status_code == 403


def test_un_operador_ve_todos_los_pagos(cliente, con_regla):
    pagar(cliente)
    pagar(cliente)
    como_operador = token("pagos:read", roles=["OPERADOR"])

    respuesta = cliente.get(PAGOS, headers=como_operador)

    assert respuesta.json()["total_elementos"] == 2


def test_un_cliente_no_registra_pagos_cargos_ni_reembolsos(cliente, con_regla):
    # Los clientes tienen pagos:write solo para sus medios de pago (contrato).
    yo = str(uuid.uuid4())
    mio = pagar(cliente, cliente_id=yo)
    como_cliente = {
        **token("pagos:read", "pagos:write", roles=["CLIENTE"], sub=yo),
        **nueva_clave(),
    }
    pago = {
        "viaje_id": _viaje_terminado(cliente),
        "cliente_id": yo,
        "beneficiario_id": str(uuid.uuid4()),
        "monto": 2090,
    }
    cargo = {
        "viaje_id": str(uuid.uuid4()),
        "cliente_id": yo,
        "tipo_vehiculo": "auto",
        "motivo": "x",
    }

    respuestas = [
        cliente.post(PAGOS, json=pago, headers=como_cliente),
        cliente.post(CARGOS, json=cargo, headers=como_cliente),
        cliente.post(f"{PAGOS}/{mio['id']}/reembolsos", json={"motivo": "x"}, headers=como_cliente),
    ]

    assert [r.status_code for r in respuestas] == [403, 403, 403]


def test_un_cliente_maneja_solo_sus_medios_de_pago(cliente):
    yo = str(uuid.uuid4())
    otro = str(uuid.uuid4())
    como_cliente = token("pagos:read", "pagos:write", roles=["CLIENTE"], sub=yo)
    tarjeta = {"tipo": "tarjeta", "token_pasarela": "tok_123"}
    de_otro = cliente.post(MEDIOS, json={"cliente_id": otro, **tarjeta}, headers=modulo()).json()

    mio = cliente.post(MEDIOS, json={"cliente_id": yo, **tarjeta}, headers=como_cliente)
    para_otro = cliente.post(MEDIOS, json={"cliente_id": otro, **tarjeta}, headers=como_cliente)
    lista = cliente.get(MEDIOS, headers=como_cliente)
    lista_de_otro = cliente.get(MEDIOS, params={"cliente_id": otro}, headers=como_cliente)
    cambiar_el_de_otro = cliente.patch(
        f"{MEDIOS}/{de_otro['id']}", json={"alias": "x"}, headers=como_cliente
    )
    borrar_el_de_otro = cliente.delete(f"{MEDIOS}/{de_otro['id']}", headers=como_cliente)

    assert mio.status_code == 201
    assert [m["id"] for m in lista.json()["items"]] == [mio.json()["id"]]
    for respuesta in (para_otro, lista_de_otro, cambiar_el_de_otro, borrar_el_de_otro):
        assert respuesta.status_code == 403


# --- Conductores: solo lo suyo ------------------------------------------------


def test_un_conductor_solo_ve_sus_liquidaciones_y_su_saldo(cliente, con_regla):
    yo = str(uuid.uuid4())
    otro = str(uuid.uuid4())
    pagar(cliente, beneficiario_id=yo)
    pagar(cliente, beneficiario_id=otro)
    hoy = datetime.now(HORA_ARGENTINA).date().isoformat()
    periodo = {"periodo_desde": hoy, "periodo_hasta": hoy}
    la_mia = cliente.post(
        LIQUIDACIONES, json={"beneficiario_id": yo, **periodo}, headers=modulo()
    ).json()
    la_de_otro = cliente.post(
        LIQUIDACIONES, json={"beneficiario_id": otro, **periodo}, headers=modulo()
    ).json()
    como_conductor = token("liquidaciones:read", roles=["CONDUCTOR"], sub=yo)

    lista = cliente.get(LIQUIDACIONES, headers=como_conductor)
    lista_de_otro = cliente.get(
        LIQUIDACIONES, params={"beneficiario_id": otro}, headers=como_conductor
    )
    mia = cliente.get(f"{LIQUIDACIONES}/{la_mia['id']}", headers=como_conductor)
    de_otro = cliente.get(f"{LIQUIDACIONES}/{la_de_otro['id']}", headers=como_conductor)
    mi_saldo = cliente.get(f"{LIQUIDACIONES}/saldos/{yo}", headers=como_conductor)
    saldo_de_otro = cliente.get(f"{LIQUIDACIONES}/saldos/{otro}", headers=como_conductor)

    assert [liq["id"] for liq in lista.json()["items"]] == [la_mia["id"]]
    assert mia.status_code == 200
    assert mi_saldo.status_code == 200
    for respuesta in (lista_de_otro, de_otro, saldo_de_otro):
        assert respuesta.status_code == 403


def test_un_conductor_no_genera_liquidaciones(cliente):
    yo = str(uuid.uuid4())
    como_conductor = token("liquidaciones:read", "liquidaciones:write", roles=["CONDUCTOR"], sub=yo)

    respuesta = cliente.post(
        LIQUIDACIONES,
        json={"beneficiario_id": yo, "periodo_desde": "2026-11-01", "periodo_hasta": "2026-11-30"},
        headers=como_conductor,
    )

    assert respuesta.status_code == 403


def test_el_historial_anota_el_sub_de_quien_registro_el_pago(cliente, con_regla):
    m6 = str(uuid.uuid4())
    viaje_id = _viaje_terminado(cliente)
    pedido = {
        "viaje_id": viaje_id,
        "cliente_id": str(uuid.uuid4()),
        "beneficiario_id": str(uuid.uuid4()),
        "monto": 2090,
    }
    pago = cliente.post(
        PAGOS, json=pedido, headers={**token("pagos:write", sub=m6), **nueva_clave()}
    ).json()

    movimientos = cliente.get(f"{PAGOS}/{pago['id']}/movimientos", headers=modulo()).json()["items"]

    assert {m["actor"] for m in movimientos} == {m6}


def _viaje_terminado(cliente) -> str:
    viaje_id = str(uuid.uuid4())
    respuesta = cliente.post(
        f"/api/v1/tarifas/viajes/{viaje_id}/tarifa-final", json=VIAJE_TERMINADO, headers=modulo()
    )
    assert respuesta.status_code == 201, respuesta.text
    return viaje_id
