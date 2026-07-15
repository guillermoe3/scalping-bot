# funding-calibracion

## Pre-registro

- rol: apuesta principal del ciclo (C1)
- datos: klines 15m + funding futures um, 2020-01 -> 2026-06 (mes corriente sin dump)
- evento: cruce de entrada a la cola: percentil_rodante(rates, i, 90, rates[i]) > 0.90 (alta) o < 0.10 (baja) sobre las 90 lecturas de funding previas; evento si extremo(i) y no extremo(i-1); extremo es booleano (cualquiera de las dos colas): un flip directo alta<->baja NO es evento nuevo
- ventana_funding: funding filtrado por ventana(modo) ANTES de detectar eventos; las primeras ~90 lecturas de funding dentro de cualquier ventana no pueden ser eventos (no tienen ventana rodante completa) — aceptado y documentado, no es un bug
- ancla: vela 15m cuyo ts == ts_funding - 900_000 (la que CIERRA en el funding); ts_funding se pisa a la grilla de 900_000 ms antes de restar (los ts reales traen jitter de ms); si falta la vela, se descarta el evento
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
        "n": 156,
        "media": -0.0011547888136662792,
        "mediana": -0.0010713595008756413,
        "hit_rate": 0.4551282051282051
      },
      "24h": {
        "n": 156,
        "media": -0.0019235006842792351,
        "mediana": -0.0012774966780987258,
        "hit_rate": 0.46794871794871795
      },
      "72h": {
        "n": 156,
        "media": -0.0050964327294425816,
        "mediana": -0.00559660445197583,
        "hit_rate": 0.44871794871794873
      }
    },
    "baja": {
      "8h": {
        "n": 340,
        "media": 0.0007566277811922197,
        "mediana": 0.0005484914556945788,
        "hit_rate": 0.5264705882352941
      },
      "24h": {
        "n": 340,
        "media": 0.006131694530625982,
        "mediana": 0.0029387065429294333,
        "hit_rate": 0.5735294117647058
      },
      "72h": {
        "n": 339,
        "media": 0.009916396143905253,
        "mediana": 0.004631079420904164,
        "hit_rate": 0.5634218289085545
      }
    }
  },
  "ETHUSDT": {
    "alta": {
      "8h": {
        "n": 172,
        "media": -0.00021614935691269876,
        "mediana": 0.000731057817308213,
        "hit_rate": 0.5058139534883721
      },
      "24h": {
        "n": 172,
        "media": -0.0018948288524773377,
        "mediana": 0.001837348046018749,
        "hit_rate": 0.5232558139534884
      },
      "72h": {
        "n": 172,
        "media": -0.009641485757249482,
        "mediana": -0.004779455159490294,
        "hit_rate": 0.4476744186046512
      }
    },
    "baja": {
      "8h": {
        "n": 309,
        "media": -0.00025308780424169016,
        "mediana": 0.001474747124243213,
        "hit_rate": 0.5533980582524272
      },
      "24h": {
        "n": 309,
        "media": 0.0017948092915486208,
        "mediana": 0.0025969556170897952,
        "hit_rate": 0.5372168284789643
      },
      "72h": {
        "n": 309,
        "media": 0.008784691093545318,
        "mediana": 0.011194745195405155,
        "hit_rate": 0.5889967637540453
      }
    }
  }
}
```
