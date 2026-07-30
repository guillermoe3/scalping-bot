from __future__ import annotations

import argparse
import sys
from typing import List

from estudios import estudio_ma, estudio_momentum
from estudios.nucleo import (
    VENTANA_SIGMA,
    exposiciones,
    metricas_estrategia,
    peor_mes,
    retornos_diarios,
    serie_estrategia,
)
from estudios.reporte import escribir_reporte

SIGMA_TARGETS = (0.20, 0.30, 0.40)

PREREGISTRO = {
    "rol": "M3 vol targeting — CONDICIONAL: corre solo si alguna celda de M1/M2 paso calibracion Y verificacion (spec 2026-07-15)",
    "overlay": "exposicion(t) = min(1, sigma_target / sigma_realizada_30d(t)); sigma realizada = desvio de los ultimos 30 retornos diarios x sqrt(365), calculada al cierre de t y aplicada a t+1; tope 1x",
    "grilla": "sigma_target in {0.20, 0.30, 0.40} anualizado",
    "umbral_adopcion": "en calibracion Y verificacion: mejora max drawdown Y peor mes calendario vs la version cruda, Y media de r_strat >= 1/2 de la cruda",
    "celda_base": "la mejor celda ganadora de M1/M2 en BTC (mayor Sharpe de verificacion), pasada por CLI",
}


def _posiciones_base(args, closes: List[float]) -> List[float]:
    if args.estudio == "momentum":
        return estudio_momentum.posiciones_tsmom(closes, args.parametro, args.variante)
    return estudio_ma.posiciones_ma(closes, args.parametro)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M3: volatility-targeting overlay on the winning M1/M2 cell.")
    parser.add_argument("--estudio", required=True, choices=("momentum", "ma"))
    parser.add_argument("--parametro", required=True, type=int,
                        help="lookback k (momentum) or MA length n (ma)")
    parser.add_argument("--variante", default="long_flat",
                        choices=("long_short", "long_flat"))
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args(argv)
    if args.estudio == "ma" and args.variante != "long_flat":
        parser.error("--estudio ma only supports --variante long_flat")

    modulo = estudio_momentum if args.estudio == "momentum" else estudio_ma
    rows, eval_desde = modulo.rows_con_burn_in(args.symbol, args.modo, args.verificacion)
    closes = [r[4] for r in rows]
    rets = retornos_diarios(closes)
    pos_base = _posiciones_base(args, closes)

    idx0 = max(1, eval_desde)
    ts_eval = [rows[t][0] for t in range(idx0, len(rows))]

    def _celda(posiciones: List[float]) -> dict:
        celda = metricas_estrategia(rets, posiciones, eval_desde)
        r_strat = serie_estrategia(rets, posiciones)[idx0 - 1:]
        celda["peor_mes"] = peor_mes(ts_eval, r_strat)
        return celda

    resultados: dict = {"celda_base": vars(args) | {"symbol": args.symbol},
                        "cruda": _celda(pos_base), "overlay": {}}
    for target in SIGMA_TARGETS:
        exp = exposiciones(rets, target)
        pos_overlay = [p * e for p, e in zip(pos_base, exp)]
        resultados["overlay"][f"{target:.2f}"] = _celda(pos_overlay)

    ruta = escribir_reporte(f"vol-overlay-{args.modo}", PREREGISTRO,
                            celdas=1 + len(SIGMA_TARGETS), resultados=resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
