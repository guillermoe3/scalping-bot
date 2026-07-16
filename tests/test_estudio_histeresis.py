from estudios.estudio_histeresis import posiciones_tsmom_banda


def test_banda_entra_largo_mantiene_y_sale():
    # k=2, x=0.05 (5%): retorno claro > x entra, interior mantiene, < -x sale
    closes = [100.0, 100.0, 106.0, 107.0, 103.0, 101.0]
    assert posiciones_tsmom_banda(closes, 2, 0.05) == [0.0, 0.0, 1.0, 1.0, 1.0, 0.0]


def test_banda_primer_dia_interior_sin_previa_es_flat():
    # dia 2 (primer dia evaluable, i==k): retorno 2% cae en el interior
    # (-5%, 5%], pero no hay posicion previa real -> flat, por construccion
    closes = [100.0, 100.0, 102.0]
    assert posiciones_tsmom_banda(closes, 2, 0.05) == [0.0, 0.0, 0.0]


def test_banda_x_cero_replica_tsmom_long_flat_sin_banda():
    # mismo fixture que test_posiciones_long_flat_recorta_el_lado_corto en
    # tests/test_estudio_momentum.py; con x=0.0 debe dar el mismo resultado
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert posiciones_tsmom_banda(closes, 2, 0.0) == [0.0, 0.0, 1.0, 0.0, 0.0]
