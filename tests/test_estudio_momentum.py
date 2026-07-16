from estudios.estudio_momentum import posiciones_tsmom


def test_posiciones_long_short():
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert posiciones_tsmom(closes, 2, "long_short") == [0.0, 0.0, 1.0, -1.0, -1.0]


def test_posiciones_long_flat_recorta_el_lado_corto():
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert posiciones_tsmom(closes, 2, "long_flat") == [0.0, 0.0, 1.0, 0.0, 0.0]
