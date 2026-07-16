import math

import pytest

from estudios.nucleo import (
    CORTE_HISTERESIS_MS,
    CORTE_VERIFICACION_MS,
    cambios_de_posicion,
    max_drawdown,
    metricas_buy_and_hold,
    metricas_estrategia,
    peor_mes,
    percentil_rodante,
    ratio_ma,
    resumen,
    retorno_forward,
    retornos_diarios,
    senal_tsmom,
    serie_estrategia,
    sharpe_anualizado,
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


def test_senal_tsmom_signo_y_borde():
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert senal_tsmom(closes, 2, 2) == 1     # 101 > 100
    assert senal_tsmom(closes, 3, 2) == -1    # 99 < 102
    assert senal_tsmom(closes, 1, 2) is None  # sin lookback completo
    assert senal_tsmom([100.0, 100.0, 100.0], 2, 2) == 0


def test_ratio_ma_y_borde():
    closes = [100.0, 110.0, 120.0]
    assert ratio_ma(closes, 2, 3) == 120.0 / 110.0
    assert ratio_ma(closes, 1, 3) is None


def test_retornos_diarios():
    # NOTE: brief asserts `rets[1] == 0.1` exactly, but 110.0/100.0 - 1.0 ==
    # 0.10000000000000009 under IEEE-754 doubles (not exactly representable).
    # The brief's own next assertion already uses a tolerance for the same
    # reason (rets[2]), so this looks like an inconsistency rather than an
    # intentional exact-equality check; using the same tolerance style here.
    rets = retornos_diarios([100.0, 110.0, 99.0])
    assert rets[0] == 0.0
    assert abs(rets[1] - 0.1) < 1e-12
    assert abs(rets[2] - (-0.1)) < 1e-12


def test_serie_estrategia_aplica_posicion_del_dia_previo():
    # pos decided at close of t applies to the return of t+1
    assert serie_estrategia([0.0, 0.01, -0.02], [1.0, -1.0, 0.0]) == [0.01, 0.02]


def test_sharpe_anualizado():
    assert abs(sharpe_anualizado([0.01, 0.02, 0.03]) - 2.0 * math.sqrt(365)) < 1e-9
    assert sharpe_anualizado([0.01]) is None
    assert sharpe_anualizado([0.01, 0.01]) is None  # desvio 0


def test_max_drawdown():
    # equity: 1.10 -> 0.88 -> 0.968; peak 1.10 -> dd = 1 - 0.88/1.10 = 0.2
    assert abs(max_drawdown([0.10, -0.20, 0.10]) - 0.2) < 1e-12
    assert max_drawdown([0.01, 0.01]) == 0.0


def test_peor_mes():
    ene = 1767225600000   # 2026-01-01T00:00:00Z
    feb = 1769904000000   # 2026-02-01T00:00:00Z
    ts = [ene, ene + 86_400_000, feb]
    assert abs(peor_mes(ts, [0.01, 0.01, -0.02]) - (-0.02)) < 1e-12
    assert peor_mes([], []) is None


def test_metricas_estrategia_y_buy_and_hold():
    retornos = [0.0, 0.10, -0.20, 0.10]
    posiciones = [1.0, 1.0, 0.0, 1.0]
    m = metricas_estrategia(retornos, posiciones)
    assert m["n_dias"] == 3
    assert m["n_dias_en_posicion"] == 2          # days 1 and 2 held a position
    assert abs(m["max_drawdown"] - 0.2) < 1e-12  # 1.10 -> 0.88 -> 0.88
    assert abs(m["mediana_en_posicion"] - (-0.05)) < 1e-12
    b = metricas_buy_and_hold(retornos)
    assert b["n_dias"] == 3
    assert abs(b["media"] - (0.10 - 0.20 + 0.10) / 3) < 1e-12


def test_metricas_estrategia_eval_desde_recorta_el_burn_in():
    retornos = [0.0, 0.05, 0.10, -0.20]
    posiciones = [1.0, 1.0, 1.0, 1.0]
    m = metricas_estrategia(retornos, posiciones, eval_desde=2)
    assert m["n_dias"] == 2  # solo los dias 2 y 3


def test_cambios_de_posicion_cuenta_transiciones():
    assert cambios_de_posicion([0.0, 0.0, 1.0, 1.0, 0.0]) == 2
    assert cambios_de_posicion([1.0, 1.0, 1.0]) == 0
    assert cambios_de_posicion([1.0]) == 0
    assert cambios_de_posicion([]) == 0


def test_corte_histeresis_ms_es_2025_07_01():
    from datetime import datetime, timezone
    momento = datetime.fromtimestamp(CORTE_HISTERESIS_MS / 1000, tz=timezone.utc)
    assert momento == datetime(2025, 7, 1, tzinfo=timezone.utc)
