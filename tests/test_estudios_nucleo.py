import pytest

from estudios.nucleo import (
    CORTE_VERIFICACION_MS,
    percentil_rodante,
    resumen,
    retorno_forward,
    ventana,
)


def _row(ts_ms, close=100.0):
    return [ts_ms, close, close, close, close, 1.0, 0.5]


def test_ventana_calibracion_filtra_por_corte():
    rows = [_row(CORTE_VERIFICACION_MS - 1), _row(CORTE_VERIFICACION_MS)]
    assert ventana(rows, "calibracion") == [rows[0]]


def test_ventana_verificacion_bloqueada_por_default():
    with pytest.raises(ValueError, match="locked"):
        ventana([_row(CORTE_VERIFICACION_MS)], "verificacion")


def test_ventana_verificacion_con_flag():
    rows = [_row(CORTE_VERIFICACION_MS - 1), _row(CORTE_VERIFICACION_MS)]
    assert ventana(rows, "verificacion", verificacion_habilitada=True) == [rows[1]]


def test_retorno_forward_y_borde():
    closes = [100.0, 101.0, 102.0]
    assert retorno_forward(closes, 0, 2) == pytest.approx(0.02)
    assert retorno_forward(closes, 1, 2) is None


def test_percentil_rodante_excluye_la_posicion_actual():
    vals = [1.0, 2.0, 3.0, 4.0, 10.0]
    # ventana = las 4 anteriores a i=4; 10.0 es mayor que todas
    assert percentil_rodante(vals, 4, 4, 10.0) == pytest.approx(1.0)
    assert percentil_rodante(vals, 3, 4, 4.0) is None  # solo 3 previas


def test_resumen():
    # NOTE: brief's literal sample [0.01, -0.02, 0.03] has fmean == 0.00667,
    # inconsistent with the brief's asserted 0.00333 (abs tol 1e-4). Using
    # [0.01, -0.02, 0.02] instead: it satisfies all three assertions exactly
    # (media, mediana, hit_rate) with the correct statistics.fmean/median,
    # so it looks like a one-digit typo (0.03 -> 0.02) in the brief rather
    # than a different intended formula for "media". See task-7-report.md.
    r = resumen([0.01, -0.02, 0.02])
    assert r["n"] == 3
    assert r["media"] == pytest.approx(0.00333, abs=1e-4)
    assert r["mediana"] == pytest.approx(0.01)
    assert r["hit_rate"] == pytest.approx(2 / 3)


def test_resumen_vacio_devuelve_none():
    assert resumen([]) == {"n": 0, "media": None, "mediana": None, "hit_rate": None}
