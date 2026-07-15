"""Study C1: extreme-funding base rate — the cycle's main bet.

Pre-registered event: funding rate crossing INTO the extreme tail (top/bottom
decile over the 90 prior funding observations). Anchors on the 15m kline that
CLOSES at the funding timestamp and measures the signed forward return over
three horizons, signing so that a crowded-longs extreme (alta) is scored as a
SHORT thesis and a crowded-shorts extreme (baja) is scored as a LONG thesis.

stdlib only.
"""

from __future__ import annotations

import argparse

import funding_history
from estudios.nucleo import cargar_klines, percentil_rodante, resumen, retorno_forward, ventana
from estudios.reporte import escribir_reporte

VENTANA_PERCENTIL = 90
UMBRAL_ALTO = 0.90
UMBRAL_BAJO = 0.10
ANCLA_OFFSET_MS = 900_000  # 15m: the anchor bar closes at the funding ts
N_MINIMO_CALIBRACION = 150

HORIZONTES = {"8h": 32, "24h": 96, "72h": 288}


def _cola_extremo(rates: list[float], i: int) -> str | None:
    """Which tail (if any) observation i falls in, given the 90 prior rates."""
    pct = percentil_rodante(rates, i, VENTANA_PERCENTIL, rates[i])
    if pct is None:
        return None
    if pct > UMBRAL_ALTO:
        return "alta"
    if pct < UMBRAL_BAJO:
        return "baja"
    return None


def detectar_eventos(funding: list[list]) -> list[tuple[int, str]]:
    """Indices (into `funding`) where the rate crosses INTO an extreme tail.

    extremo(i) = percentil_rodante(rates, i, 90, rates[i]) > 0.90 ("alta")
                 or < 0.10 ("baja")
    evento si extremo(i) y no extremo(i-1). extremo is BOOLEAN (in EITHER
    tail): a direct alta<->baja flip is two consecutive extreme readings and
    is NOT a new event. i-1 with an incomplete window (fewer than 90 priors)
    counts as "not extreme".
    """
    rates = [r[1] for r in funding]
    eventos: list[tuple[int, str]] = []
    extremo_previo = False
    for i in range(len(rates)):
        cola_actual = _cola_extremo(rates, i)
        extremo_actual = cola_actual is not None
        if extremo_actual and not extremo_previo:
            eventos.append((i, cola_actual))
        extremo_previo = extremo_actual
    return eventos


def indexar_klines(rows: list[list]) -> dict[int, int]:
    """Map each kline's ts_ms to its row index."""
    return {row[0]: i for i, row in enumerate(rows)}


def retornos_firmados(
    eventos: list[tuple[int, str]],
    funding: list[list],
    rows: list[list],
    horizonte_barras: int,
) -> list[float]:
    """Signed forward returns for each event.

    Anchor: the 15m kline whose ts == ts_funding - 900_000 (the bar that
    CLOSES at the funding timestamp). Real funding timestamps carry ms-level
    jitter off the 15m grid, so ts_funding is floored to the 900_000 ms grid
    BEFORE subtracting the anchor offset. Events without that anchor bar are
    skipped. Signing: "alta" (crowded longs) -> SHORT thesis -> -retorno;
    "baja" (crowded shorts) -> LONG thesis -> +retorno.
    """
    indice_ts = indexar_klines(rows)
    closes = [row[4] for row in rows]
    firmados: list[float] = []
    for idx_funding, cola in eventos:
        ts_funding = funding[idx_funding][0]
        ts_ancla = (ts_funding // ANCLA_OFFSET_MS) * ANCLA_OFFSET_MS - ANCLA_OFFSET_MS
        idx_ancla = indice_ts.get(ts_ancla)
        if idx_ancla is None:
            continue
        retorno = retorno_forward(closes, idx_ancla, horizonte_barras)
        if retorno is None:
            continue
        signo = -1.0 if cola == "alta" else 1.0
        firmados.append(retorno * signo)
    return firmados


def estudiar_symbol(symbol: str, modo: str, verificacion_habilitada: bool) -> dict:
    klines = ventana(
        cargar_klines(symbol, "2020-01", "2026-07"),
        modo,
        verificacion_habilitada=verificacion_habilitada,
    )
    funding = ventana(
        funding_history.read_funding(symbol),
        modo,
        verificacion_habilitada=verificacion_habilitada,
    )
    eventos = detectar_eventos(funding)
    eventos_por_cola = {"alta": [], "baja": []}
    for evento in eventos:
        eventos_por_cola[evento[1]].append(evento)

    resultados: dict = {}
    for cola, eventos_cola in eventos_por_cola.items():
        resultados[cola] = {}
        for etiqueta_horizonte, barras in HORIZONTES.items():
            firmados = retornos_firmados(eventos_cola, funding, klines, barras)
            celda = resumen(firmados)
            if modo == "calibracion" and celda["n"] < N_MINIMO_CALIBRACION:
                celda["nota"] = "n insuficiente — solo descartar o extender datos"
            resultados[cola][etiqueta_horizonte] = celda
    return resultados


PREREGISTRO = {
    "rol": "apuesta principal del ciclo (C1)",
    "datos": "klines 15m + funding futures um, 2020-01 -> 2026-06 (mes corriente sin dump)",
    "evento": (
        "cruce de entrada a la cola: percentil_rodante(rates, i, 90, rates[i]) > 0.90 "
        "(alta) o < 0.10 (baja) sobre las 90 lecturas de funding previas; evento si "
        "extremo(i) y no extremo(i-1); extremo es booleano (cualquiera de las dos "
        "colas): un flip directo alta<->baja NO es evento nuevo"
    ),
    "ventana_funding": (
        "funding filtrado por ventana(modo) ANTES de detectar eventos; las primeras "
        "~90 lecturas de funding dentro de cualquier ventana no pueden ser eventos "
        "(no tienen ventana rodante completa) — aceptado y documentado, no es un bug"
    ),
    "ancla": (
        "vela 15m cuyo ts == ts_funding - 900_000 (la que CIERRA en el funding); "
        "ts_funding se pisa a la grilla de 900_000 ms antes de restar (los ts reales "
        "traen jitter de ms); si falta la vela, se descarta el evento"
    ),
    "horizontes": "8h=32 barras, 24h=96 barras, 72h=288 barras (barras de 15m)",
    "firma": "cola alta (longs crowded) -> tesis SHORT -> retorno * -1; cola baja -> tesis LONG -> retorno * +1",
    "n_minimo_calibracion": "150 por cola por simbolo",
    "umbral_adopcion": (
        "mediana firmada >= 0.14% Y media mismo signo Y hit_rate > 50% en "
        "calibracion, sostenido en verificacion (mismo signo, magnitud >= 1/2 de "
        "calibracion)"
    ),
    "decision": "solo BTC adopta/veta; ETH es robustez",
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modo", choices=["calibracion", "verificacion"], required=True)
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbols", required=True)
    args = parser.parse_args(argv)

    symbols = args.symbols.split(",")
    resultados = {
        symbol: estudiar_symbol(symbol, args.modo, args.verificacion)
        for symbol in symbols
    }
    celdas = 2 * len(HORIZONTES) * len(symbols)
    ruta = escribir_reporte(
        f"funding-{args.modo}", PREREGISTRO, celdas=celdas, resultados=resultados
    )
    print(f"Reporte escrito en: {ruta}")


if __name__ == "__main__":
    main()
