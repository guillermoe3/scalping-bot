# funding-calibracion

## Pre-registro

- rol: apuesta principal del ciclo (C1)
- datos: klines 15m + funding futures um, 2020-01 -> 2026-06 (mes corriente sin dump)
- evento: cruce de entrada a la cola: percentil_rodante(rates, i, 90, rates[i]) > 0.90 (alta) o < 0.10 (baja) sobre las 90 lecturas de funding previas; evento si extremo(i) y no extremo(i-1)
- ventana_funding: funding filtrado por ventana(modo) ANTES de detectar eventos; las primeras ~90 lecturas de funding dentro de cualquier ventana no pueden ser eventos (no tienen ventana rodante completa) — aceptado y documentado, no es un bug
- ancla: vela 15m cuyo ts == ts_funding - 900_000 (la que CIERRA en el funding); si falta, se descarta el evento
- horizontes: 8h=32 barras, 24h=96 barras, 72h=288 barras (barras de 15m)
- firma: cola alta (longs crowded) -> tesis SHORT -> retorno * -1; cola baja -> tesis LONG -> retorno * +1
- n_minimo_calibracion: 150 por cola por simbolo
- umbral_adopcion: mediana firmada >= 0.14% Y media mismo signo Y hit_rate > 50% en calibracion, sostenido en verificacion (mismo signo, magnitud >= 1/2 de calibracion)
- decision: solo BTC adopta/veta; ETH es robustez

Celdas miradas: 12

## Resultados

```json
{
  "BTCUSDT": {
    "alta": {
      "8h": {
        "n": 115,
        "media": -0.0019488537629162013,
        "mediana": -0.0007209256110755692,
        "hit_rate": 0.46956521739130436,
        "nota": "n insuficiente — solo descartar o extender datos"
      },
      "24h": {
        "n": 115,
        "media": -0.0006119027848890126,
        "mediana": -0.00015768439039214673,
        "hit_rate": 0.4956521739130435,
        "nota": "n insuficiente — solo descartar o extender datos"
      },
      "72h": {
        "n": 115,
        "media": -0.006431843812089987,
        "mediana": -0.006072584526095422,
        "hit_rate": 0.45217391304347826,
        "nota": "n insuficiente — solo descartar o extender datos"
      }
    },
    "baja": {
      "8h": {
        "n": 183,
        "media": 0.0006369942821871685,
        "mediana": 1.4800538081808416e-05,
        "hit_rate": 0.5027322404371585
      },
      "24h": {
        "n": 183,
        "media": 0.005453979094089026,
        "mediana": 0.002827227639744139,
        "hit_rate": 0.5737704918032787
      },
      "72h": {
        "n": 182,
        "media": 0.013769921713891273,
        "mediana": 0.0063329846652876755,
        "hit_rate": 0.5769230769230769
      }
    }
  },
  "ETHUSDT": {
    "alta": {
      "8h": {
        "n": 111,
        "media": -0.0007229437986150954,
        "mediana": 0.0008697349217663603,
        "hit_rate": 0.5135135135135135,
        "nota": "n insuficiente — solo descartar o extender datos"
      },
      "24h": {
        "n": 111,
        "media": -0.00047335450249767107,
        "mediana": 0.0036749116607773906,
        "hit_rate": 0.5315315315315315,
        "nota": "n insuficiente — solo descartar o extender datos"
      },
      "72h": {
        "n": 111,
        "media": -0.0008153340241471925,
        "mediana": -0.001810007378142532,
        "hit_rate": 0.4774774774774775,
        "nota": "n insuficiente — solo descartar o extender datos"
      }
    },
    "baja": {
      "8h": {
        "n": 173,
        "media": -0.0006896840174147728,
        "mediana": 0.001474747124243213,
        "hit_rate": 0.5664739884393064
      },
      "24h": {
        "n": 173,
        "media": -0.00031337848665491337,
        "mediana": 0.002240337585115621,
        "hit_rate": 0.5317919075144508
      },
      "72h": {
        "n": 173,
        "media": 0.003041882159570893,
        "mediana": 0.005465787585829829,
        "hit_rate": 0.5491329479768786
      }
    }
  }
}
```
