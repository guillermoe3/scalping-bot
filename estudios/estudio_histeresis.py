from __future__ import annotations

import argparse
import sys
from typing import List

import daily_history
from estudios.nucleo import (
    CORTE_HISTERESIS_MS,
    cambios_de_posicion,
    metricas_buy_and_hold,
    metricas_estrategia,
    retornos_diarios,
    ventana,
)
from estudios.reporte import escribir_reporte

K = 14
GRILLA_X = (0.0, 0.02, 0.05, 0.08)
BURN_IN = 14
SYMBOL = "BTCUSDT"  # alcance: solo la celda ganadora del ciclo anterior
START_MONTH = "2017-08"
END_MONTH = "2026-07"  # exclusive: current month has no published dump

PREREGISTRO = {
    "rol": "Ciclo diseno de senal — banda muerta sobre TSMOM k=14 (spec 2026-07-16)",
    "datos": "klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC unicamente",
    "senal": "banda muerta simetrica sobre ret[t-14,t]: entra largo si ret > x, pasa a flat si ret <= -x, si cae en (-x, x] mantiene la posicion del dia anterior (primer dia evaluable sin previa: flat)",
    "grilla_x": "0.0, 0.02, 0.05, 0.08 (fraccion); x=0.0 es control de sanidad, degenera en TSMOM k=14 long_flat sin banda",
    "split": "calibracion 2017-08 -> 2025-06; verificacion 2025-07 -> presente (sellada, ventana NUEVA); corte_ms=1751328000000",
    "burn_in": "en verificacion, los 14 dias previos al corte solo alimentan la senal",
    "umbral_adopcion": (
        "para cada x>0, comparado contra el control x=0.0 de la MISMA ventana, en calibracion Y "
        "verificacion por separado: cambios_de_posicion(x) < cambios_de_posicion(control), Y "
        "sharpe(x) >= sharpe(control), Y max_drawdown(x) <= max_drawdown(control). 'Casi' = NO PASA."
    ),
    "criterio_salida": (
        "si algun x>0 pasa en ambas ventanas -> se adopta el de mayor reduccion de operaciones "
        "entre los que pasan; si ninguno pasa -> se descarta la banda, la senal candidata sigue "
        "siendo TSMOM k=14 long_flat sin banda (firmado 2026-07-16)"
    ),
}


def posiciones_tsmom_banda(closes: List[float], k: int, x: float) -> List[float]:
    """Long/flat position with a symmetric dead band on the k-day return.

    ret > x -> long (1.0); ret <= -x -> flat (0.0); otherwise holds
    yesterday's position. Days before the lookback fills are flat, which
    also seeds the band's "no previous position" default.
    """
    out: List[float] = []
    pos_previa = 0.0
    for i in range(len(closes)):
        if i < k:
            pos = 0.0
        else:
            ret = closes[i] / closes[i - k] - 1.0
            if ret > x:
                pos = 1.0
            elif ret <= -x:
                pos = 0.0
            else:
                pos = pos_previa
        out.append(pos)
        pos_previa = pos
    return out


def rows_con_burn_in(modo: str, verificacion: bool):
    """Window rows plus, in verification mode, a signal-only burn-in prefix."""
    todas = daily_history.cargar_rango(SYMBOL, START_MONTH, END_MONTH)
    seleccion = ventana(todas, modo, corte_ms=CORTE_HISTERESIS_MS,
                        verificacion_habilitada=verificacion)
    if modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_HISTERESIS_MS][-BURN_IN:]
        return previos + seleccion, len(previos)
    return seleccion, 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Signal-design cycle: dead band on TSMOM k=14 (BTC only).")
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    args = parser.parse_args(argv)

    rows, eval_desde = rows_con_burn_in(args.modo, args.verificacion)
    closes = [r[4] for r in rows]
    rets = retornos_diarios(closes)
    idx0 = max(1, eval_desde)

    celdas: dict = {}
    for x in GRILLA_X:
        pos = posiciones_tsmom_banda(closes, K, x)
        m = metricas_estrategia(rets, pos, eval_desde)
        m["cambios_de_posicion"] = cambios_de_posicion(pos[idx0 - 1:])
        celdas[str(x)] = m

    control = celdas[str(GRILLA_X[0])]
    for x in GRILLA_X[1:]:
        c = celdas[str(x)]
        c["pasa_vs_control"] = bool(
            c["sharpe"] is not None
            and control["sharpe"] is not None
            and c["cambios_de_posicion"] < control["cambios_de_posicion"]
            and c["sharpe"] >= control["sharpe"]
            and c["max_drawdown"] <= control["max_drawdown"]
        )

    resultados = {
        SYMBOL: {
            "buy_and_hold": metricas_buy_and_hold(rets, eval_desde),
            "celdas": celdas,
        }
    }
    ruta = escribir_reporte(f"histeresis-{args.modo}", PREREGISTRO, len(GRILLA_X), resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
