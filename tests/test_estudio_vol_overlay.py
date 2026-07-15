from estudios.estudio_vol_overlay import VENTANA_SIGMA, exposiciones


def test_exposiciones_cero_durante_burn_in_y_con_sigma_cero():
    rets = [0.0] * (VENTANA_SIGMA + 5)
    exp = exposiciones(rets, 0.30)
    assert all(e == 0.0 for e in exp)  # sigma 0 -> sin exposicion


def test_exposiciones_capped_a_uno_y_monotonas_en_target():
    # alternating +-3% daily: sigma anualizada ~ 0.57 -> target 0.2 da < 1
    rets = [0.03 if i % 2 == 0 else -0.03 for i in range(VENTANA_SIGMA + 10)]
    e_bajo = exposiciones(rets, 0.20)
    e_alto = exposiciones(rets, 5.00)
    t = VENTANA_SIGMA + 5
    assert 0.0 < e_bajo[t] < 1.0
    assert e_alto[t] == 1.0            # cap de exposicion 1x
    assert e_bajo[t] <= e_alto[t]      # monotonia en sigma_target
    assert all(e == 0.0 for e in e_bajo[:VENTANA_SIGMA])
