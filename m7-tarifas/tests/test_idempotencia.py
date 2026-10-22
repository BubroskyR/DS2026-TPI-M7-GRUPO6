"""Idempotency-Key (RF-7.6, RNF-08): la misma solicitud repetida no cobra dos veces."""

import pytest

from app.core import db
from app.core.errores import ErrorDeDominio
from app.core.idempotencia import ejecutar_una_vez


class Cobro:
    """Operación de prueba que cuenta cuántas veces se hizo."""

    def __init__(self, respuesta: dict):
        self.respuesta = respuesta
        self.veces = 0

    def __call__(self) -> dict:
        self.veces += 1
        return self.respuesta


def test_la_primera_vez_hace_la_operacion(sesion):
    cobro = Cobro({"id": "pago-1", "estado": "aprobado"})

    respuesta, es_nueva = ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "100"}, cobro)

    assert respuesta == {"id": "pago-1", "estado": "aprobado"}
    assert es_nueva is True
    assert cobro.veces == 1


def test_misma_clave_y_mismo_cuerpo_devuelve_la_respuesta_original_sin_repetir(sesion):
    cuerpo = {"monto": "100", "metodo": "efectivo"}
    ejecutar_una_vez(sesion, "crearPago", "clave-1", cuerpo, Cobro({"id": "pago-1"}))
    segundo_cobro = Cobro({"id": "pago-2"})

    # Otra sesión, como si fuera otra solicitud, con los campos en otro orden.
    with db.SesionLocal() as otra_sesion:
        respuesta, es_nueva = ejecutar_una_vez(
            otra_sesion, "crearPago", "clave-1", {"metodo": "efectivo", "monto": "100"}, segundo_cobro
        )

    assert respuesta == {"id": "pago-1"}
    assert es_nueva is False
    assert segundo_cobro.veces == 0


def test_misma_clave_con_otro_cuerpo_responde_422(sesion):
    ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "100"}, Cobro({"id": "pago-1"}))
    segundo_cobro = Cobro({"id": "pago-2"})

    with pytest.raises(ErrorDeDominio) as error:
        ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "999"}, segundo_cobro)

    assert error.value.status == 422
    assert segundo_cobro.veces == 0


def test_misma_clave_mientras_la_primera_se_procesa_responde_409(sesion):
    estados_de_la_repeticion = []
    repeticion = Cobro({"id": "pago-2"})

    def cobro_lento() -> dict:
        # Mientras la primera se procesa, llega la misma solicitud por otra sesión.
        with db.SesionLocal() as otra_sesion:
            try:
                ejecutar_una_vez(otra_sesion, "crearPago", "clave-1", {"monto": "100"}, repeticion)
            except ErrorDeDominio as error:
                estados_de_la_repeticion.append(error.status)
        return {"id": "pago-1"}

    ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "100"}, cobro_lento)

    assert estados_de_la_repeticion == [409]
    assert repeticion.veces == 0


def test_si_la_operacion_falla_la_clave_se_puede_volver_a_usar(sesion):
    def cobro_que_falla() -> dict:
        raise ErrorDeDominio(422, "/errores/de-prueba", "Falla de prueba")

    with pytest.raises(ErrorDeDominio):
        ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "100"}, cobro_que_falla)
    cobro = Cobro({"id": "pago-1"})

    respuesta, es_nueva = ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "100"}, cobro)

    assert respuesta == {"id": "pago-1"}
    assert es_nueva is True
    assert cobro.veces == 1


def test_la_misma_clave_en_otra_operacion_es_otra_solicitud(sesion):
    ejecutar_una_vez(sesion, "crearPago", "clave-1", {"monto": "100"}, Cobro({"id": "pago-1"}))
    reembolso = Cobro({"id": "reembolso-1"})

    respuesta, es_nueva = ejecutar_una_vez(
        sesion, "reembolsarPago", "clave-1", {"monto": "100"}, reembolso
    )

    assert respuesta == {"id": "reembolso-1"}
    assert es_nueva is True
    assert reembolso.veces == 1
