import pytest

from estudios.estudio_cascadas import detectar_cascadas


def _rows_con_cascada():
    rows = []
    price = 100.0
    for i in range(120):
        # ruido suave +-0.05%, volumen balanceado (flujo 0)
        price *= 1.0005 if i % 2 == 0 else 0.9995
        rows.append([i * 900_000, price, price, price, price, 10.0, 5.0])
    # vela 120: caida del 3% con flujo vendedor unidireccional (taker_buy=1/10)
    crash = rows[-1][4] * 0.97
    rows.append([120 * 900_000, crash, crash, crash, crash, 10.0, 1.0])
    return rows


def test_detectar_cascadas_encuentra_la_caida():
    eventos = detectar_cascadas(_rows_con_cascada())
    assert eventos == [(120, -1)]


def test_sin_flujo_unidireccional_no_hay_evento():
    rows = _rows_con_cascada()
    rows[-1][6] = 5.0  # flujo balanceado
    assert detectar_cascadas(rows) == []
