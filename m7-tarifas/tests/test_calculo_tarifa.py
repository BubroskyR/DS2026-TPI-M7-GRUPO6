"""Cálculo de la tarifa (RF-7.1) con la fórmula del contrato, en ejemplos hechos a mano.

total = máximo((tarifa_base + precio_por_km × distancia + precio_por_minuto × duración)
               × multiplicador_demanda, tarifa_minima), redondeado al centavo.
"""

from decimal import Decimal

from app.models.tarifas import ReglaTarifa
from app.services.tarifas import calcular_desglose


def regla(tarifa_base="500", precio_por_km="150", precio_por_minuto="20", tarifa_minima="1000"):
    return ReglaTarifa(
        tipo_vehiculo="auto",
        tarifa_base=Decimal(tarifa_base),
        precio_por_km=Decimal(precio_por_km),
        precio_por_minuto=Decimal(precio_por_minuto),
        tarifa_minima=Decimal(tarifa_minima),
    )


def test_suma_la_base_la_distancia_y_el_tiempo():
    # 500 + 150 × 8,2 + 20 × 18 = 500 + 1230 + 360 = 2090
    desglose = calcular_desglose(regla(), Decimal("8.2"), Decimal("18"), Decimal("1"))

    assert desglose.tarifa_base == Decimal("500")
    assert desglose.cargo_distancia == Decimal("1230")
    assert desglose.cargo_tiempo == Decimal("360")
    assert desglose.multiplicador_demanda == Decimal("1")
    assert desglose.total == Decimal("2090")


def test_el_multiplicador_de_demanda_multiplica_la_suma():
    # (500 + 1230 + 360) × 1,5 = 3135
    desglose = calcular_desglose(regla(), Decimal("8.2"), Decimal("18"), Decimal("1.5"))

    assert desglose.total == Decimal("3135")


def test_si_la_suma_no_llega_a_la_tarifa_minima_se_cobra_la_minima():
    # 500 + 150 × 1 + 20 × 2 = 690, menos que la mínima de 1000
    desglose = calcular_desglose(regla(), Decimal("1"), Decimal("2"), Decimal("1"))

    assert desglose.total == Decimal("1000")


def test_la_tarifa_minima_se_compara_despues_del_multiplicador():
    # 690 × 1,5 = 1035, que ya supera la mínima de 1000
    desglose = calcular_desglose(regla(), Decimal("1"), Decimal("2"), Decimal("1.5"))

    assert desglose.total == Decimal("1035")


def test_redondea_al_centavo_con_la_mitad_hacia_arriba():
    # 1 + 0,10 × 0,05 = 1,005, que se redondea a 1,01 (la mitad hacia arriba)
    sin_minima = regla(
        tarifa_base="1", precio_por_km="0", precio_por_minuto="0.10", tarifa_minima="0"
    )

    desglose = calcular_desglose(sin_minima, Decimal("1"), Decimal("0.05"), Decimal("1"))

    assert desglose.cargo_tiempo == Decimal("0.01")
    assert desglose.total == Decimal("1.01")


def test_el_total_se_redondea_una_sola_vez_al_final():
    # Cada cargo da 0,004 y se muestra como 0,00, pero el total es 0,008 y se
    # redondea a 0,01: la fórmula del contrato redondea al final.
    sin_minima = regla(
        tarifa_base="0", precio_por_km="0.01", precio_por_minuto="0.01", tarifa_minima="0"
    )

    desglose = calcular_desglose(sin_minima, Decimal("0.4"), Decimal("0.4"), Decimal("1"))

    assert desglose.cargo_distancia == Decimal("0")
    assert desglose.cargo_tiempo == Decimal("0")
    assert desglose.total == Decimal("0.01")
