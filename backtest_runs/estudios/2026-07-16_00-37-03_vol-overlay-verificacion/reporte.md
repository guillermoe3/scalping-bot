# vol-overlay-verificacion

## Pre-registro

- rol: M3 vol targeting — CONDICIONAL: corre solo si alguna celda de M1/M2 paso calibracion Y verificacion (spec 2026-07-15)
- overlay: exposicion(t) = min(1, sigma_target / sigma_realizada_30d(t)); sigma realizada = desvio de los ultimos 30 retornos diarios x sqrt(365), calculada al cierre de t y aplicada a t+1; tope 1x
- grilla: sigma_target in {0.20, 0.30, 0.40} anualizado
- umbral_adopcion: en calibracion Y verificacion: mejora max drawdown Y peor mes calendario vs la version cruda, Y media de r_strat >= 1/2 de la cruda
- celda_base: la mejor celda ganadora de M1/M2 en BTC (mayor Sharpe de verificacion), pasada por CLI

Celdas miradas: 4

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
  "cruda": {
    "n_dias": 912,
    "n_dias_en_posicion": 480,
    "sharpe": 1.041315010916546,
    "max_drawdown": 0.2674581263807472,
    "media": 0.0009104641936403225,
    "mediana_en_posicion": 0.0009609039416332843,
    "peor_mes": -0.12027316798034693
  },
  "overlay": {
    "0.20": {
      "n_dias": 912,
      "n_dias_en_posicion": 480,
      "sharpe": 1.1096618984190214,
      "max_drawdown": 0.12305015035813593,
      "media": 0.0004541878737818755,
      "mediana_en_posicion": 0.00046328404688804553,
      "peor_mes": -0.04183923878619167
    },
    "0.30": {
      "n_dias": 912,
      "n_dias_en_posicion": 480,
      "sharpe": 1.1171437281056158,
      "max_drawdown": 0.1666201609004866,
      "media": 0.0006730269757394002,
      "mediana_en_posicion": 0.0006949260703320683,
      "peor_mes": -0.062346378792557
    },
    "0.40": {
      "n_dias": 912,
      "n_dias_en_posicion": 480,
      "sharpe": 1.1656294090026575,
      "max_drawdown": 0.1837844974870192,
      "media": 0.000870139174806594,
      "mediana_en_posicion": 0.0008226680474475153,
      "peor_mes": -0.07628134370851902
    }
  }
}
```
