import pytest

from estudios.estudio_instrumento import funding_por_dia, serie_neta


def test_funding_por_dia_suma_las_lecturas_del_dia_utc():
    dia = 1704067200000  # 2024-01-01T00:00:00Z
    rows = [[dia, 0.0001], [dia + 8 * 3_600_000, 0.0002], [dia + 86_400_000, 0.0005]]
    # pytest.approx: 0.0001 + 0.0002 != 0.0003 exactly in IEEE 754 float64
    # (yields 0.00030000000000000003); exact dict equality on floats is not
    # meaningful here, so this compares with tolerance like the rest of the
    # study suite does (see tests/test_estudios_nucleo.py).
    assert funding_por_dia(rows) == pytest.approx({dia: 0.0003, dia + 86_400_000: 0.0005})


def test_serie_neta_resta_funding_solo_en_dias_long():
    dia0 = 1704067200000
    rows = [[dia0, 0, 0, 0, 100.0, 0], [dia0 + 86_400_000, 0, 0, 0, 102.0, 0]]
    rets = [0.0, 0.02]
    pos_long = [1.0, 1.0]
    por_dia = {dia0 + 86_400_000: 0.001}
    bruta, neta = serie_neta(rows, rets, pos_long, por_dia, eval_desde=0)
    assert bruta == [0.02]
    assert abs(neta[0] - 0.019) < 1e-12
