"""Liquidaciones y saldo de los beneficiarios (RF-7.8)."""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.core.config import settings
from app.models.pagos import Pago
from tests.ayudas import (
    CARGOS,
    LIQUIDACIONES,
    PAGOS,
    avisar,
    crear_regla,
    nueva_clave,
    pagar,
    pagar_aprobado,
)

CONDUCTOR = str(uuid.uuid4())
NOVIEMBRE = {"periodo_desde": "2026-11-01", "periodo_hasta": "2026-11-30"}


@pytest.fixture
def fechar(sesion):
    """Cambia la fecha en que se creó un pago, para ubicarlo en un período."""

    def _fechar(pago: dict, cuando: str = "2026-11-10T12:00:00-03:00") -> dict:
        sesion.execute(
            update(Pago)
            .where(Pago.id == uuid.UUID(pago["id"]))
            .values(creado_en=datetime.fromisoformat(cuando))
        )
        sesion.commit()
        return pago

    return _fechar


def liquidar(cliente, beneficiario_id=CONDUCTOR, **periodo):
    return cliente.post(
        LIQUIDACIONES, json={"beneficiario_id": beneficiario_id, **NOVIEMBRE, **periodo}
    )


def precio_fijo(cliente, total: int) -> None:
    """Una regla de auto con la que todo viaje cuesta `total`."""
    crear_regla(cliente, tarifa_base=total, precio_por_km=0, precio_por_minuto=0, tarifa_minima=0)


def test_el_ejemplo_del_contrato(cliente, fechar):
    # Un viaje con tarjeta de $ 10.000 y otro en efectivo de $ 5.000, con 20% de comisión.
    precio_fijo(cliente, 10000)
    con_tarjeta = fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR, monto=10000))
    precio_fijo(cliente, 5000)
    en_efectivo = fechar(
        pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR, monto=5000),
        "2026-11-11T12:00:00-03:00",
    )

    respuesta = liquidar(cliente)

    assert respuesta.status_code == 201, respuesta.text
    liquidacion = respuesta.json()
    assert respuesta.headers["Location"] == f"{LIQUIDACIONES}/{liquidacion['id']}"
    assert liquidacion["beneficiario_id"] == CONDUCTOR
    assert liquidacion["periodo_desde"] == "2026-11-01"
    assert liquidacion["periodo_hasta"] == "2026-11-30"
    assert liquidacion["pago_ids"] == [con_tarjeta["id"], en_efectivo["id"]]
    assert liquidacion["monto_bruto"] == 15000
    assert liquidacion["comision_plataforma"] == 3000
    assert liquidacion["cobrado_en_efectivo"] == 5000
    # Con los $ 5.000 que ya cobró, el conductor se queda con $ 12.000, el 80%.
    assert liquidacion["monto_neto"] == 7000
    assert liquidacion["moneda"] == "ARS"
    assert liquidacion["estado"] == "pendiente"
    assert "referencia_transferencia" not in liquidacion


def test_si_cobro_todo_en_efectivo_el_neto_es_negativo(cliente, fechar):
    crear_regla(cliente)
    fechar(pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR))

    liquidacion = liquidar(cliente).json()

    # Cobró 2090 en mano y le debe a la plataforma su comisión: 418.
    assert liquidacion["monto_bruto"] == 2090
    assert liquidacion["comision_plataforma"] == 418
    assert liquidacion["cobrado_en_efectivo"] == 2090
    assert liquidacion["monto_neto"] == -418


def test_lo_reembolsado_no_cuenta_en_el_bruto(cliente, fechar):
    crear_regla(cliente)
    pago = fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    cliente.post(
        f"{PAGOS}/{pago['id']}/reembolsos",
        json={"monto": 90, "motivo": "Desvío"},
        headers=nueva_clave(),
    )

    liquidacion = liquidar(cliente).json()

    assert liquidacion["pago_ids"] == [pago["id"]]
    assert liquidacion["monto_bruto"] == 2000
    assert liquidacion["comision_plataforma"] == 400
    assert liquidacion["monto_neto"] == 1600


def test_en_efectivo_se_descuenta_todo_lo_que_cobro_en_mano(cliente, fechar):
    # Si se le reembolsó una parte al cliente, la puso la plataforma: el
    # conductor igual cobró todo el viaje en mano.
    crear_regla(cliente)
    pago = fechar(pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR))
    cliente.post(
        f"{PAGOS}/{pago['id']}/reembolsos",
        json={"monto": 90, "motivo": "Desvío"},
        headers=nueva_clave(),
    )

    liquidacion = liquidar(cliente).json()

    assert liquidacion["monto_bruto"] == 2000
    assert liquidacion["cobrado_en_efectivo"] == 2090
    assert liquidacion["monto_neto"] == -490


def test_solo_entran_los_pagos_cobrados_del_beneficiario_en_el_periodo(cliente, fechar):
    crear_regla(cliente)
    cobrado = fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    fechar(pagar(cliente, metodo="tarjeta", beneficiario_id=CONDUCTOR))  # pendiente
    rechazado = fechar(pagar(cliente, metodo="tarjeta", beneficiario_id=CONDUCTOR))
    avisar(cliente, rechazado, "rechazado")
    reembolsado = fechar(pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR))
    cliente.post(
        f"{PAGOS}/{reembolsado['id']}/reembolsos", json={"motivo": "x"}, headers=nueva_clave()
    )
    fechar(pagar_aprobado(cliente, "efectivo"))  # de otro conductor
    fechar(
        pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR), "2026-12-01T10:00:00-03:00"
    )
    # Un cargo por cancelación del mismo viaje: es de la plataforma, no se liquida.
    cargo = cliente.post(
        CARGOS,
        json={
            "viaje_id": cobrado["viaje_id"],
            "cliente_id": cobrado["cliente_id"],
            "tipo_vehiculo": "auto",
            "metodo": "tarjeta",
            "motivo": "x",
        },
        headers=nueva_clave(),
    ).json()
    fechar(avisar(cliente, cargo).json())

    liquidacion = liquidar(cliente).json()

    assert liquidacion["pago_ids"] == [cobrado["id"]]
    assert liquidacion["monto_bruto"] == 2090


def test_los_dias_del_periodo_son_los_de_la_argentina(cliente, fechar):
    crear_regla(cliente)
    # El 31 de octubre a las 23:30 en la Argentina ya es 1 de noviembre en UTC.
    de_octubre = fechar(
        pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR), "2026-10-31T23:30:00-03:00"
    )
    del_30_de_noviembre = fechar(
        pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR), "2026-11-30T23:59:00-03:00"
    )

    noviembre = liquidar(cliente).json()
    octubre = liquidar(cliente, periodo_desde="2026-10-01", periodo_hasta="2026-10-31").json()

    assert noviembre["pago_ids"] == [del_30_de_noviembre["id"]]
    assert octubre["pago_ids"] == [de_octubre["id"]]


def test_un_pago_no_entra_en_dos_liquidaciones(cliente, fechar):
    crear_regla(cliente)
    fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    liquidar(cliente)

    respuesta = liquidar(cliente)

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/sin-pagos-para-liquidar"


def test_sin_pagos_para_liquidar_responde_422(cliente):
    respuesta = liquidar(cliente)

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/sin-pagos-para-liquidar"


def test_un_periodo_que_termina_antes_de_empezar_responde_422(cliente):
    respuesta = liquidar(cliente, periodo_desde="2026-11-30", periodo_hasta="2026-11-01")

    assert respuesta.status_code == 422
    assert respuesta.json()["type"] == "/errores/periodo-invalido"


def test_un_pedido_con_formato_invalido_responde_400(cliente):
    invalidos = [
        {"beneficiario_id": CONDUCTOR, "periodo_desde": "2026-11-01"},
        {"beneficiario_id": "conductor-1", **NOVIEMBRE},
        {"beneficiario_id": CONDUCTOR, **NOVIEMBRE, "periodo_hasta": "30/11/2026"},
        {"beneficiario_id": CONDUCTOR, **NOVIEMBRE, "comision": 0},
    ]

    for cuerpo in invalidos:
        respuesta = cliente.post(LIQUIDACIONES, json=cuerpo)

        assert respuesta.status_code == 400, cuerpo


def test_la_comision_se_configura(cliente, fechar, monkeypatch):
    monkeypatch.setattr(settings, "comision_plataforma", Decimal("0.15"))
    crear_regla(cliente)
    fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))

    liquidacion = liquidar(cliente).json()

    # 15% de 2090 = 313,50.
    assert liquidacion["comision_plataforma"] == 313.5
    assert liquidacion["monto_neto"] == 1776.5


def test_registrar_la_transferencia(cliente, fechar):
    crear_regla(cliente)
    fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    liquidacion = liquidar(cliente).json()

    respuesta = cliente.post(
        f"{LIQUIDACIONES}/{liquidacion['id']}/transferencia",
        json={"referencia_transferencia": "TRF-0001"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "transferida"
    assert respuesta.json()["referencia_transferencia"] == "TRF-0001"
    assert cliente.get(f"{LIQUIDACIONES}/{liquidacion['id']}").json() == respuesta.json()


def test_anular_libera_los_pagos_para_otra_liquidacion(cliente, fechar):
    crear_regla(cliente)
    pago = fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    primera = liquidar(cliente).json()

    anulada = cliente.post(f"{LIQUIDACIONES}/{primera['id']}/anulacion")
    segunda = liquidar(cliente)

    assert anulada.status_code == 200
    assert anulada.json()["estado"] == "anulada"
    # La anulada conserva qué pagos tenía.
    assert anulada.json()["pago_ids"] == [pago["id"]]
    assert segunda.status_code == 201
    assert segunda.json()["pago_ids"] == [pago["id"]]


def test_solo_se_transfiere_o_se_anula_una_liquidacion_pendiente(cliente, fechar):
    crear_regla(cliente)
    fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    transferida = liquidar(cliente).json()
    cliente.post(
        f"{LIQUIDACIONES}/{transferida['id']}/transferencia",
        json={"referencia_transferencia": "TRF-1"},
    )

    otra_transferencia = cliente.post(
        f"{LIQUIDACIONES}/{transferida['id']}/transferencia",
        json={"referencia_transferencia": "TRF-2"},
    )
    anulacion = cliente.post(f"{LIQUIDACIONES}/{transferida['id']}/anulacion")

    for respuesta in (otra_transferencia, anulacion):
        assert respuesta.status_code == 409
        assert respuesta.json()["type"] == "/errores/liquidacion-no-pendiente"
    assert cliente.get(f"{LIQUIDACIONES}/{transferida['id']}").json()["estado"] == "transferida"


def test_una_liquidacion_que_no_existe_responde_404(cliente):
    liquidacion_id = uuid.uuid4()

    consulta = cliente.get(f"{LIQUIDACIONES}/{liquidacion_id}")
    transferencia = cliente.post(
        f"{LIQUIDACIONES}/{liquidacion_id}/transferencia", json={"referencia_transferencia": "T"}
    )
    anulacion = cliente.post(f"{LIQUIDACIONES}/{liquidacion_id}/anulacion")

    for respuesta in (consulta, transferencia, anulacion):
        assert respuesta.status_code == 404


def test_listar_liquidaciones_con_filtros(cliente, fechar):
    crear_regla(cliente)
    otro_conductor = str(uuid.uuid4())
    fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR))
    fechar(pagar_aprobado(cliente, "tarjeta", beneficiario_id=otro_conductor))
    del_conductor = liquidar(cliente).json()
    del_otro = liquidar(cliente, otro_conductor).json()
    cliente.post(f"{LIQUIDACIONES}/{del_otro['id']}/anulacion")

    todas = cliente.get(LIQUIDACIONES).json()
    filtradas = cliente.get(LIQUIDACIONES, params={"beneficiario_id": CONDUCTOR}).json()
    anuladas = cliente.get(LIQUIDACIONES, params={"estado": "anulada"}).json()

    assert todas["total_elementos"] == 2
    assert [liq["id"] for liq in filtradas["items"]] == [del_conductor["id"]]
    assert [liq["id"] for liq in anuladas["items"]] == [del_otro["id"]]


def test_el_saldo_de_un_beneficiario(cliente, fechar):
    crear_regla(cliente)
    # Una liquidación transferida, otra pendiente y un pago sin liquidar.
    fechar(
        pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR), "2026-10-10T12:00:00-03:00"
    )
    octubre = liquidar(cliente, periodo_desde="2026-10-01", periodo_hasta="2026-10-31").json()
    cliente.post(
        f"{LIQUIDACIONES}/{octubre['id']}/transferencia", json={"referencia_transferencia": "T"}
    )
    fechar(pagar_aprobado(cliente, "efectivo", beneficiario_id=CONDUCTOR))
    liquidar(cliente)
    fechar(
        pagar_aprobado(cliente, "tarjeta", beneficiario_id=CONDUCTOR), "2026-12-05T12:00:00-03:00"
    )

    respuesta = cliente.get(f"{LIQUIDACIONES}/saldos/{CONDUCTOR}")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "beneficiario_id": CONDUCTOR,
        "saldo_pendiente_liquidar": 2090,
        "liquidado_pendiente_transferir": -418,
        "total_transferido": 1672,
        "moneda": "ARS",
    }


def test_un_beneficiario_sin_pagos_tiene_saldo_0(cliente):
    respuesta = cliente.get(f"{LIQUIDACIONES}/saldos/{uuid.uuid4()}")

    assert respuesta.status_code == 200
    saldo = respuesta.json()
    assert saldo["saldo_pendiente_liquidar"] == 0
    assert saldo["liquidado_pendiente_transferir"] == 0
    assert saldo["total_transferido"] == 0
