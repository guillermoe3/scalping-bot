from estudios.estudio_ma import posiciones_ma


def test_posiciones_ma_long_flat():
    closes = [100.0, 100.0, 100.0, 130.0]
    # i=0: sin MA(2) completa -> 0; i=1,2: ratio == 1.0 (no > 1) -> 0
    # i=3: MA = (100+130)/2 = 115, ratio > 1 -> 1
    assert posiciones_ma(closes, 2) == [0.0, 0.0, 0.0, 1.0]
