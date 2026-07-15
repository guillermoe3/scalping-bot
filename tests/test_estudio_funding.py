import pytest

from estudios.estudio_funding import detectar_eventos, retornos_firmados


def _funding_series():
    # 92 lecturas: 90 neutras en 0.0001, luego un salto extremo sostenido
    rows = [[i * 28_800_000, 0.0001 + (i % 3) * 1e-6] for i in range(90)]
    rows.append([90 * 28_800_000, 0.01])   # cruce de entrada a cola alta
    rows.append([91 * 28_800_000, 0.011])  # sigue extremo: NO es evento nuevo
    return rows


def test_detectar_eventos_solo_el_cruce_de_entrada():
    eventos = detectar_eventos(_funding_series())
    assert eventos == [(90, "alta")]


def test_detectar_eventos_ignora_sin_ventana_completa():
    corta = _funding_series()[:50]
    assert detectar_eventos(corta) == []


def test_retornos_firmados_cola_alta_es_tesis_short():
    funding = _funding_series()
    ts_evento = funding[90][0]
    # klines 15m: la vela que cierra en el funding abre 900_000 antes
    rows = []
    for k in range(-1, 40):
        ts = ts_evento - 900_000 + k * 900_000
        close = 100.0 if k <= 0 else 90.0  # el precio CAE tras el evento
        rows.append([ts, close, close, close, close, 1.0, 0.5])
    firmados = retornos_firmados([(90, "alta")], funding, rows, horizonte_barras=32)
    assert len(firmados) == 1
    assert firmados[0] == pytest.approx(0.10)  # caida del 10% firmada positiva


def test_retornos_firmados_ancla_tolera_jitter_de_ms_en_funding():
    # Los ts de funding reales traen jitter de milisegundos: el ancla debe
    # pisarse a la grilla de 900_000 ms antes de restar la vela previa.
    funding = _funding_series()
    funding[90][0] += 7  # +7ms de jitter sobre la grilla
    ts_grilla = 90 * 28_800_000
    rows = []
    for k in range(-1, 40):
        ts = ts_grilla - 900_000 + k * 900_000
        close = 100.0 if k <= 0 else 90.0
        rows.append([ts, close, close, close, close, 1.0, 0.5])
    firmados = retornos_firmados([(90, "alta")], funding, rows, horizonte_barras=32)
    assert len(firmados) == 1
    assert firmados[0] == pytest.approx(0.10)


def test_detectar_eventos_flip_directo_alta_baja_no_es_evento():
    # extremo(i) es booleano (cualquiera de las dos colas): un flip directo
    # alta -> baja son dos lecturas extremas seguidas, NO un evento nuevo.
    rows = [[i * 28_800_000, 0.0001 + (i % 3) * 1e-6] for i in range(90)]
    rows.append([90 * 28_800_000, 0.01])    # cruce de entrada (alta)
    rows.append([91 * 28_800_000, -0.01])   # flip directo a baja: sigue extremo
    assert detectar_eventos(rows) == [(90, "alta")]


def test_retornos_firmados_horizonte_fuera_de_rango_se_saltea():
    funding = _funding_series()
    ts_evento = funding[90][0]
    rows = []
    for k in range(-1, 5):  # solo 5 velas tras el ancla: horizonte 32 no entra
        ts = ts_evento - 900_000 + k * 900_000
        rows.append([ts, 100.0, 100.0, 100.0, 100.0, 1.0, 0.5])
    firmados = retornos_firmados([(90, "alta")], funding, rows, horizonte_barras=32)
    assert firmados == []
