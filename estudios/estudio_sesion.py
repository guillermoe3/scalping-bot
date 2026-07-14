"""Study C2: session / time-of-day base rates.

Pre-registered role: INSUMO (input), not a signal — no adoption threshold.
Buckets every 15m candle by (UTC hour, is-weekend) and reports the forward
1-bar return distribution per bucket, per symbol. Purely descriptive.

stdlib only.
"""

from __future__ import annotations

import argparse
import statistics
from datetime import datetime, timezone

from estudios.nucleo import cargar_klines, resumen, retorno_forward, ventana
from estudios.reporte import escribir_reporte


def bucketear(rows: list[list]) -> dict[tuple[int, bool], list[int]]:
    """Map each row index into its (hour_utc, es_finde) bucket.

    Returns dict[(hora, es_finde)] -> list of row indices, in row order.
    """
    buckets: dict[tuple[int, bool], list[int]] = {}
    for i, row in enumerate(rows):
        ts_ms = row[0]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        clave = (dt.hour, dt.weekday() >= 5)
        buckets.setdefault(clave, []).append(i)
    return buckets


def _metricas_celda(closes: list[float], volumes: list[float], indices: list[int]) -> dict:
    muestras = []
    abs_muestras = []
    vols = []
    for i in indices:
        r = retorno_forward(closes, i, 1)
        if r is None:
            continue
        muestras.append(r)
        abs_muestras.append(abs(r))
        vols.append(volumes[i])
    metricas = resumen(muestras)
    metricas["media_abs_ret"] = statistics.fmean(abs_muestras) if abs_muestras else None
    metricas["volumen_medio"] = statistics.fmean(vols) if vols else None
    return metricas


def estudiar_symbol(symbol: str, modo: str, verificacion_habilitada: bool) -> dict:
    rows = ventana(
        cargar_klines(symbol, "2020-01", "2026-07"),
        modo,
        verificacion_habilitada=verificacion_habilitada,
    )
    closes = [r[4] for r in rows]
    volumes = [r[5] for r in rows]
    buckets = bucketear(rows)
    resultados = {}
    for hora in range(24):
        for es_finde in (False, True):
            clave = f"{hora:02d}_{'finde' if es_finde else 'habil'}"
            indices = buckets.get((hora, es_finde), [])
            resultados[clave] = _metricas_celda(closes, volumes, indices)
    return resultados


PREREGISTRO = {
    "rol": "insumo, sin umbral de adopcion (spec 2026-07-14)",
    "split": "calibracion 2020-01->2024-12, verificacion 2025-01->presente",
    "evento": "cada vela 15m, bucket hora UTC x habil/finde",
    "metricas": "media, mediana, hit_rate, |ret| media, volumen medio",
    "datos": "klines 15m futures um, 2020-01 -> 2026-06 (mes corriente sin dump)",
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
    celdas = 24 * 2 * len(symbols)
    ruta = escribir_reporte(
        f"sesion-{args.modo}", PREREGISTRO, celdas=celdas, resultados=resultados
    )
    print(f"Reporte escrito en: {ruta}")


if __name__ == "__main__":
    main()
