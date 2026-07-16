from __future__ import annotations

import argparse
import sys
from typing import List

import daily_history
from estudios.nucleo import (
    CORTE_MOMENTUM_MS,
    metricas_buy_and_hold,
    metricas_estrategia,
    retorno_forward,
    retornos_diarios,
    resumen,
    senal_tsmom,
    ventana,
)
from estudios.reporte import escribir_reporte

LOOKBACKS = (7, 14, 28, 56, 90)
HORIZONTES = {"1d": 1, "7d": 7, "14d": 14, "28d": 28}
BURN_IN = 90
START_MONTH = "2017-08"
END_MONTH = "2026-07"  # exclusive: current month has no published dump

PREREGISTRO = {
    "rol": "M1 TSMOM — estudio de adopcion (spec 2026-07-15)",
    "datos": "klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC+ETH",
    "senal": "sign(ret[t-k, t]), k in {7,14,28,56,90}; la posicion decidida al cierre de t se aplica al retorno de t+1",
    "variantes": "long_short (pos=senal) y long_flat (pos=max(senal,0)); posiciones 0 hasta completar lookback",
    "split": "calibracion 2017-08 -> 2023-12; verificacion 2024-01 -> presente (sellada); corte_ms=1704067200000",
    "burn_in": "en verificacion, los 90 dias previos al corte solo alimentan la senal",
    "descriptivo": "retorno forward 1/7/14/28d firmado, por lado — SOLO descriptivo (ventanas superpuestas, errores autocorrelacionados)",
    "umbral_adopcion": (
        "por celda de estrategia de BTC, en calibracion Y verificacion por separado "
        "(verificacion entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, "
        "Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de "
        "r_strat sobre los dias con posicion > 0. 'Casi' = NO PASA. Solo BTC adopta/veta; ETH robustez."
    ),
    "criterio_abandono": "si ninguna celda de M1 ni M2 pasa en BTC -> se congela la busqueda de senal (firmado 2026-07-15)",
    "n_efectivo": "advertencia pre-registrada: BTC tiene ~4 ciclos de mercado independientes; el n efectivo de regimenes es 4, no ~3250 dias",
}


def posiciones_tsmom(closes: List[float], k: int, variante: str) -> List[float]:
    """Position decided at the close of each day (0.0 until the lookback fills)."""
    out: List[float] = []
    for i in range(len(closes)):
        s = senal_tsmom(closes, i, k)
        pos = float(s) if s is not None else 0.0
        if variante == "long_flat" and pos < 0.0:
            pos = 0.0
        out.append(pos)
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
        description="M1: TSMOM base-rate study on daily spot klines.")
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
            "descriptivo": {},
        }
        for k in LOOKBACKS:
            celdas_k: dict = {}
            for variante in ("long_short", "long_flat"):
                pos = posiciones_tsmom(closes, k, variante)
                celdas_k[variante] = metricas_estrategia(rets, pos, eval_desde)
            por_simbolo["estrategia"][str(k)] = celdas_k

            desc: dict = {}
            for nombre_h, h in HORIZONTES.items():
                largos: List[float] = []
                cortos: List[float] = []
                for i in range(max(eval_desde, k), len(rows)):
                    s = senal_tsmom(closes, i, k)
                    if not s:
                        continue
                    fwd = retorno_forward(closes, i, h)
                    if fwd is None:
                        continue
                    (largos if s > 0 else cortos).append(s * fwd)
                desc[nombre_h] = {"long": resumen(largos), "short": resumen(cortos)}
            por_simbolo["descriptivo"][str(k)] = desc
        resultados[symbol] = por_simbolo

    celdas = len(simbolos) * (len(LOOKBACKS) * 2 + len(LOOKBACKS) * len(HORIZONTES) * 2)
    ruta = escribir_reporte(f"momentum-{args.modo}", PREREGISTRO, celdas, resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
