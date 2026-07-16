# vol-overlay-calibracion

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
    "modo": "calibracion",
    "verificacion": false,
    "symbol": "BTCUSDT"
  },
  "cruda": {
    "n_dias": 2327,
    "n_dias_en_posicion": 1250,
    "sharpe": 1.2609770593750584,
    "max_drawdown": 0.6553363166297628,
    "media": 0.0017360556406718546,
    "mediana_en_posicion": 0.0010101904377421977,
    "peor_mes": -0.3518565894886124
  },
  "overlay": {
    "0.20": {
      "n_dias": 2327,
      "n_dias_en_posicion": 1241,
      "sharpe": 1.4273076371734554,
      "max_drawdown": 0.26866197276610293,
      "media": 0.000665372498118497,
      "mediana_en_posicion": 0.0003381526379393681,
      "peor_mes": -0.07378564392553333
    },
    "0.30": {
      "n_dias": 2327,
      "n_dias_en_posicion": 1241,
      "sharpe": 1.4064044027684537,
      "max_drawdown": 0.3748492409356753,
      "media": 0.0009500455426588721,
      "mediana_en_posicion": 0.0005072289569090522,
      "peor_mes": -0.10857154827080728
    },
    "0.40": {
      "n_dias": 2327,
      "n_dias_en_posicion": 1241,
      "sharpe": 1.3812688452867667,
      "max_drawdown": 0.4367254879445779,
      "media": 0.0011632523760134092,
      "mediana_en_posicion": 0.0006763052758787362,
      "peor_mes": -0.11825645356387937
    }
  }
}
```
