from __future__ import annotations

import argparse
import sys
from typing import List

import daily_history
from estudios.nucleo import (
    CORTE_MOMENTUM_MS,
    metricas_buy_and_hold,
    metricas_estrategia,
    ratio_ma,
    retorno_forward,
    retornos_diarios,
    resumen,
    ventana,
)
from estudios.reporte import escribir_reporte

MAS = (10, 20, 50, 100)
HORIZONTES = {"1d": 1, "7d": 7, "14d": 14}
BURN_IN = 100
START_MONTH = "2017-08"
END_MONTH = "2026-07"  # exclusive: current month has no published dump

PREREGISTRO = {
    "rol": "M2 P/MA (replica de Detzel et al. 2021) — estudio de adopcion (spec 2026-07-15)",
    "datos": "klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC+ETH",
    "senal": "P(t)/MA_n(close), n in {10,20,50,100}; long si ratio > 1, flat si <= 1 (sin banda muerta); la posicion decidida al cierre de t se aplica al retorno de t+1",
    "split": "calibracion 2017-08 -> 2023-12; verificacion 2024-01 -> presente (sellada); corte_ms=1704067200000",
    "burn_in": "en verificacion, los 100 dias previos al corte solo alimentan la senal",
    "descriptivo": "contraste de quintiles del ratio (quintil alto vs bajo, forward 1/7/14d) DENTRO de cada ventana — SOLO descriptivo",
    "umbral_adopcion": (
        "por celda de estrategia de BTC, en calibracion Y verificacion por separado "
        "(verificacion entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, "
        "Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de "
        "r_strat sobre los dias con posicion > 0. 'Casi' = NO PASA. Solo BTC adopta/veta; ETH robustez."
    ),
    "regla_fragilidad": "si M1 pasa y M2 falla (o viceversa) en celdas economicamente equivalentes, se reporta como fragilidad de especificacion — no se elige la mejor",
    "criterio_abandono": "si ninguna celda de M1 ni M2 pasa en BTC -> se congela la busqueda de senal (firmado 2026-07-15)",
}


def posiciones_ma(closes: List[float], n: int) -> List[float]:
    """Long/flat position decided at the close of each day (paper spec)."""
    out: List[float] = []
    for i in range(len(closes)):
        ratio = ratio_ma(closes, i, n)
        out.append(1.0 if ratio is not None and ratio > 1.0 else 0.0)
    return out


def rows_con_burn_in(symbol: str, modo: str, verificacion: bool):
    """Window rows plus, in verification mode, a signal-only burn-in prefix."""
    todas = daily_history.cargar_rango(symbol, START_MONTH, END_MONTH)
    seleccion = ventana(todas, modo, corte_ms=CORTE_MOMENTUM_MS,
                        verificacion_habilitada=verificacion)
    if modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_MOMENTUM_MS][-BURN_IN:]
        return previos + seleccion, len(previos)
    return seleccion, 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M2: price-to-MA base-rate study on daily spot klines.")
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    args = parser.parse_args(argv)
    simbolos = [s.strip() for s in args.symbols.split(",") if s.strip()]

    resultados: dict = {}
    for symbol in simbolos:
        rows, eval_desde = rows_con_burn_in(symbol, args.modo, args.verificacion)
        closes = [r[4] for r in rows]
        rets = retornos_diarios(closes)
        por_simbolo: dict = {
            "buy_and_hold": metricas_buy_and_hold(rets, eval_desde),
            "estrategia": {},
            "quintiles": {},
        }
        for n in MAS:
            pos = posiciones_ma(closes, n)
            por_simbolo["estrategia"][str(n)] = metricas_estrategia(rets, pos, eval_desde)

            desc: dict = {}
            for nombre_h, h in HORIZONTES.items():
                pares: List[tuple] = []
                for i in range(max(eval_desde, n - 1), len(rows)):
                    ratio = ratio_ma(closes, i, n)
                    fwd = retorno_forward(closes, i, h)
                    if ratio is None or fwd is None:
                        continue
                    pares.append((ratio, fwd))
                pares.sort(key=lambda p: p[0])
                quinto = len(pares) // 5
                desc[nombre_h] = {
                    "q_bajo": resumen([f for _, f in pares[:quinto]]),
                    "q_alto": resumen([f for _, f in pares[-quinto:]]) if quinto else resumen([]),
                }
            por_simbolo["quintiles"][str(n)] = desc
        resultados[symbol] = por_simbolo

    celdas = len(simbolos) * (len(MAS) + len(MAS) * len(HORIZONTES) * 2)
    ruta = escribir_reporte(f"ma-{args.modo}", PREREGISTRO, celdas, resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
