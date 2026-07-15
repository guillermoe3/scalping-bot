"""Study C3: post-extreme-move reversion base rate.

Pre-registered event: a 15m return more than 3 sigma away from the rolling
96-bar return stdev, coupled with unidirectional taker flow (>= 60% one
side). Measures the signed forward return AGAINST the move's direction over
three horizons, testing whether extreme unidirectional cascades tend to
revert. BTC only: ETH has no local futures tick data to validate the
taker_buy column against (see Task 6 Step 4b), so it is out of scope for C3.

stdlib only.
"""

from __future__ import annotations

import argparse
import statistics

from estudios.nucleo import cargar_klines, resumen, retorno_forward, ventana
from estudios.reporte import escribir_reporte

VENTANA_SIGMA = 96
UMBRAL_SIGMA = 3.0
UMBRAL_FLUJO = 0.6
N_MINIMO_CALIBRACION = 50
CORTE_C3_MS = 1780272000000  # 2026-06-01T00:00:00Z
INICIO_EVENTOS_MS = 1775001600000  # 2026-04-01T00:00:00Z

HORIZONTES = {"1h": 4, "4h": 16, "8h": 32}


def detectar_cascadas(rows: list[list]) -> list[tuple[int, int]]:
    """Indices (into `rows`) of extreme unidirectional moves.

    Event at i requires i >= 97 (96 prior returns + the return into i) and:
    - ret[i] = (c[i]-c[i-1])/c[i-1]; sigma = stdev(ret[i-96:i]) (the 96
      returns strictly before i, no lookahead); |ret[i]| > 3*sigma.
    - vol[i] > 0 and unidirectional taker flow:
      |2*taker_buy[i] - vol[i]| / vol[i] >= 0.6.

    Returns [(indice, direccion)] with direccion +1 (up move) or -1 (down
    move), direccion = sign(ret[i]).
    """
    closes = [r[4] for r in rows]
    volumenes = [r[5] for r in rows]
    taker_buys = [r[6] for r in rows]

    retornos = [None] * len(rows)
    for i in range(1, len(rows)):
        retornos[i] = (closes[i] - closes[i - 1]) / closes[i - 1]

    eventos: list[tuple[int, int]] = []
    for i in range(len(rows)):
        if i < VENTANA_SIGMA + 1:
            continue
        vol = volumenes[i]
        if vol <= 0:
            continue
        ventana_retornos = retornos[i - VENTANA_SIGMA : i]
        sigma = statistics.stdev(ventana_retornos)
        if sigma == 0:
            continue
        ret_i = retornos[i]
        if abs(ret_i) <= UMBRAL_SIGMA * sigma:
            continue
        flujo = abs(2 * taker_buys[i] - vol) / vol
        if flujo < UMBRAL_FLUJO:
            continue
        direccion = 1 if ret_i > 0 else -1
        eventos.append((i, direccion))
    return eventos


def retornos_firmados(
    eventos: list[tuple[int, int]], closes: list[float], horizonte_barras: int
) -> list[float]:
    """Signed forward returns for each event, AGAINST the move's direction.

    firmado = -direccion * retorno_forward(closes, indice, horizonte_barras)
    so a cascade up is scored as a SHORT thesis and a cascade down is scored
    as a LONG thesis (reversion bet). Events without that horizon bar are
    skipped.
    """
    firmados: list[float] = []
    for indice, direccion in eventos:
        retorno = retorno_forward(closes, indice, horizonte_barras)
        if retorno is None:
            continue
        firmados.append(-direccion * retorno)
    return firmados


def estudiar(symbol: str, modo: str, verificacion_habilitada: bool) -> dict:
    rows_completas = cargar_klines(symbol, "2026-03", "2026-07")
    # 2026-03 stays IN the split so the 96-bar sigma window can reach back
    # into it; only the event CANDIDATES are trimmed to >= 2026-04-01 below.
    rows = ventana(
        rows_completas,
        modo,
        corte_ms=CORTE_C3_MS,
        verificacion_habilitada=verificacion_habilitada,
    )
    closes = [r[4] for r in rows]
    eventos = [
        (i, direccion)
        for i, direccion in detectar_cascadas(rows)
        if rows[i][0] >= INICIO_EVENTOS_MS
    ]
    eventos_por_direccion = {1: [], -1: []}
    for evento in eventos:
        eventos_por_direccion[evento[1]].append(evento)

    n_total = len(eventos)
    resultados: dict = {}
    for direccion, etiqueta in ((1, "alcista"), (-1, "bajista")):
        resultados[etiqueta] = {}
        for etiqueta_horizonte, barras in HORIZONTES.items():
            firmados = retornos_firmados(eventos_por_direccion[direccion], closes, barras)
            celda = resumen(firmados)
            resultados[etiqueta][etiqueta_horizonte] = celda
    resultados["n_total"] = n_total
    if n_total < N_MINIMO_CALIBRACION:
        resultados["nota"] = (
            f"n_total={n_total} < {N_MINIMO_CALIBRACION}: "
            "conclusiones permitidas: solo 'descartar' o 'extender datos'"
        )
    return resultados


PREREGISTRO = {
    "rol": "estudio de reversion post-movimiento extremo (C3)",
    "alcance": "solo BTC; ETH sin ticks futures locales para validar taker_buy queda fuera de C3 (spec)",
    "datos": "klines 15m futures um BTCUSDT, 2026-03 -> 2026-06 (2026-03 solo alimenta la ventana de sigma)",
    "eventos_desde": "2026-04-01T00:00:00Z (los candidatos a evento se recortan; los datos de sigma no)",
    "evento": (
        "ret[i] = (c[i]-c[i-1])/c[i-1]; sigma = stdev de los 96 retornos 15m previos "
        "(retornos, no precios; sin lookahead; requiere i >= 97 y vol > 0); |ret[i]| > 3*sigma "
        "y flujo unidireccional: |2*taker_buy[i] - vol[i]| / vol[i] >= 0.6"
    ),
    "split": "corte propio C3 = 2026-06-01T00:00:00Z (corte_ms=1780272000000), NO el corte global 2025",
    "horizontes": "1h=4 barras, 4h=16 barras, 8h=32 barras (barras de 15m)",
    "firma": "retorno forward CONTRA la direccion del movimiento: firmado = -direccion * retorno_forward(...)",
    "n_minimo_calibracion": f"regla dura: n_total < {N_MINIMO_CALIBRACION} -> conclusiones permitidas: solo 'descartar' o 'extender datos'",
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modo", choices=["calibracion", "verificacion"], required=True)
    parser.add_argument("--verificacion", action="store_true")
    args = parser.parse_args(argv)

    resultados = {"BTCUSDT": estudiar("BTCUSDT", args.modo, args.verificacion)}
    celdas = 2 * len(HORIZONTES)
    ruta = escribir_reporte(
        f"cascadas-{args.modo}", PREREGISTRO, celdas=celdas, resultados=resultados
    )
    print(f"Reporte escrito en: {ruta}")


if __name__ == "__main__":
    main()
