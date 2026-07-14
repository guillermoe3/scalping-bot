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
