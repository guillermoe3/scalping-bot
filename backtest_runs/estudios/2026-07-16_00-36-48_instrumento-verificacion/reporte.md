# instrumento-verificacion

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
    "modo": "verificacion",
    "verificacion": true,
    "symbol": "BTCUSDT"
  },
  "spot_sin_funding": {
    "n_dias": 912,
    "retorno_total": 1.0220019763611754,
    "sharpe": 1.041315010916546,
    "max_drawdown": 0.2674581263807472
  },
  "perp_neto_de_funding": {
    "n_dias": 912,
    "retorno_total": 0.7991116752920095,
    "sharpe": 0.8956713849182201,
    "max_drawdown": 0.28318701194271123
  },
  "drag_retorno_total": 0.22289030106916585
}
```
