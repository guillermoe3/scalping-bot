from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Tuple

import daily_history
import funding_history
from estudios import estudio_ma, estudio_momentum
from estudios.nucleo import (
    CORTE_MOMENTUM_MS,
    max_drawdown,
    retornos_diarios,
    sharpe_anualizado,
    ventana,
)
from estudios.reporte import escribir_reporte

START_MONTH = "2020-01"  # funding cache coverage (pre-registered M4 window)
END_MONTH = "2026-07"
_DIA_MS = 86_400_000

PREREGISTRO = {
    "rol": "M4 costo de instrumento — CONDICIONAL: corre solo si alguna celda de M1/M2 paso (spec 2026-07-15)",
    "ventana": "2020-01 -> presente (cobertura del funding cacheado); la calibracion pre-2020 queda fuera de M4 — es comparacion de costos, no test de senal",
    "series": "A (perp) = pata long menos funding acumulado de los dias en posicion; B (spot) = pata long sin funding",
    "aproximacion": "precio SPOT + funding de FUTUROS; la base spot-perp se ignora (documentado)",
    "decision": "sin umbral: la diferencia de retorno total y Sharpe decide el instrumento de la pata long en el ciclo de diseno de senal",
}


def funding_por_dia(funding_rows: List[list]) -> Dict[int, float]:
    """Sum the (three) 8h funding readings of each UTC day."""
    por_dia: Dict[int, float] = {}
    for ts, rate in funding_rows:
        dia = ts - ts % _DIA_MS
        por_dia[dia] = por_dia.get(dia, 0.0) + rate
    return por_dia


def serie_neta(rows: List[list], rets: List[float], pos_long: List[float],
               por_dia: Dict[int, float], eval_desde: int) -> Tuple[List[float], List[float]]:
    """(gross, net-of-funding) daily returns of the long leg from max(1, eval_desde)."""
    idx0 = max(1, eval_desde)
    bruta: List[float] = []
    neta: List[float] = []
    for t in range(idx0, len(rows)):
        r = pos_long[t - 1] * rets[t]
        bruta.append(r)
        dia = rows[t][0] - rows[t][0] % _DIA_MS
        neta.append(r - pos_long[t - 1] * por_dia.get(dia, 0.0))
    return bruta, neta


def _metricas(serie: List[float]) -> dict:
    total = 1.0
    for r in serie:
        total *= 1.0 + r
    return {
        "n_dias": len(serie),
        "retorno_total": total - 1.0,
        "sharpe": sharpe_anualizado(serie),
        "max_drawdown": max_drawdown(serie),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M4: perp-funding drag vs spot for the winning cell's long leg.")
    parser.add_argument("--estudio", required=True, choices=("momentum", "ma"))
    parser.add_argument("--parametro", required=True, type=int)
    parser.add_argument("--variante", default="long_flat",
                        choices=("long_short", "long_flat"))
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args(argv)
    if args.estudio == "ma" and args.variante != "long_flat":
        parser.error("--estudio ma only supports --variante long_flat")

    burn_in = estudio_momentum.BURN_IN if args.estudio == "momentum" else estudio_ma.BURN_IN
    todas = daily_history.cargar_rango(args.symbol, START_MONTH, END_MONTH)
    seleccion = ventana(todas, args.modo, corte_ms=CORTE_MOMENTUM_MS,
                        verificacion_habilitada=args.verificacion)
    if args.modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_MOMENTUM_MS][-burn_in:]
        rows, eval_desde = previos + seleccion, len(previos)
    else:
        rows, eval_desde = seleccion, 0

    closes = [r[4] for r in rows]
    rets = retornos_diarios(closes)
    if args.estudio == "momentum":
        pos = estudio_momentum.posiciones_tsmom(closes, args.parametro, args.variante)
    else:
        pos = estudio_ma.posiciones_ma(closes, args.parametro)
    pos_long = [p if p > 0.0 else 0.0 for p in pos]

    por_dia = funding_por_dia(funding_history.read_funding(args.symbol))
    bruta, neta = serie_neta(rows, rets, pos_long, por_dia, eval_desde)

    resultados = {
        "celda_base": vars(args) | {"symbol": args.symbol},
        "spot_sin_funding": _metricas(bruta),
        "perp_neto_de_funding": _metricas(neta),
        "drag_retorno_total": _metricas(bruta)["retorno_total"] - _metricas(neta)["retorno_total"],
    }
    ruta = escribir_reporte(f"instrumento-{args.modo}", PREREGISTRO,
                            celdas=2, resultados=resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
