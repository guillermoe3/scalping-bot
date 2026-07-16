# instrumento-calibracion

## Pre-registro

- rol: M4 costo de instrumento — CONDICIONAL: corre solo si alguna celda de M1/M2 paso (spec 2026-07-15)
- ventana: 2020-01 -> presente (cobertura del funding cacheado); la calibracion pre-2020 queda fuera de M4 — es comparacion de costos, no test de senal
- series: A (perp) = pata long menos funding acumulado de los dias en posicion; B (spot) = pata long sin funding
- aproximacion: precio SPOT + funding de FUTUROS; la base spot-perp se ignora (documentado)
- decision: sin umbral: la diferencia de retorno total y Sharpe decide el instrumento de la pata long en el ciclo de diseno de senal

Celdas miradas: 2

## Resultados

```json
{
  "celda_base": {
    "estudio": "momentum",
    "parametro": 14,
    "variante": "long_flat",
    "modo": "calibracion",
    "verificacion": false,
    "symbol": "BTCUSDT"
  },
  "spot_sin_funding": {
    "n_dias": 1460,
    "retorno_total": 7.515150831717605,
    "sharpe": 1.4070291536239155,
    "max_drawdown": 0.4919180687461956
  },
  "perp_neto_de_funding": {
    "n_dias": 1460,
    "retorno_total": 4.33198946946111,
    "sharpe": 1.1491921927344335,
    "max_drawdown": 0.5096319050790892
  },
  "drag_retorno_total": 3.183161362256495
}
```
