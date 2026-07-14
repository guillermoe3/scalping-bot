# Autopsia de trades perdedores — señal squeeze 15m (BTC/USDT)

**Fecha:** 2026-07-13 · **Rango analizado:** 2026-04-01 → 2026-07-01 (91 días, 8.736 barras de 15m)
**Código:** commit `9554998` (mismo que la ablación) · **Parámetros:** compression 0.6, min_bars 2, SL inicial = 1,5×ATR, TP1 = 2R

**Validación de réplicas instrumentadas** (conteo de trades vs los `trades.csv` persistidos — coincidencia 1:1 en los 4 casos):

| Réplica | Esperado | Obtenido |
|---|---|---|
| A (fade) base | 28 | 28 ✓ |
| B (break) base | 48 | 48 (+1 parcial) ✓ |
| A sin gate trend_1h | 95 | 95 ✓ |
| B sin gate trend_1h | 78 | 78 (+1 parcial) ✓ |

---

## Hallazgo principal: el trailing stop estructural mata los trades al nacer (bug de ejecución)

Antes de mirar la señal hay que mirar el arma del crimen. En `risk.py`, `_apply_structural_trail()` (líneas 199-222) arrastra el stop hasta el swing más reciente **sin comprobar que el nuevo stop quede del lado correcto del precio actual**. Como la señal entra justo cuando el precio está comprimido pegado a niveles (eso ES el squeeze), casi siempre hay un swing "reciente" al otro lado del precio. En el mismo tick del fill, `manage_position()` (líneas 289-298) aplica el trail y acto seguido comprueba `sl_hit` → el stop recién saltado por encima/debajo del precio dispara la salida inmediata.

Analogía: es como poner la valla de seguridad *dentro* de la casa — nada más entrar por la puerta, ya estás fuera.

**Evidencia (snapshots del stop vivo en el momento de la salida final):**

| Run | Stop al otro lado de la entrada (sin breakeven ganado) | Stop encogido vs 1,5×ATR inicial | Stop intacto o más amplio |
|---|---|---|---|
| A base (n=28) | **26/28** | 2/28 (mediana: quedó al 13% de la distancia inicial) | 0/28 |
| B base (n=48) | **26/48** | 15/48 (mediana: al 3%) | 7/48 |
| A sin-trend (n=95) | **93/95** | 2/95 (al 13%) | 0/95 |
| B sin-trend (n=78) | **58/78** | 14/78 (al 5%) | 6/78 |

**Consecuencia en tiempos de vida:** en A base, 27/28 trades duraron <1 segundo (mediana de duración: 0,0 s); en B base, 27/48 duraron <1 s. Ejemplo típico (A, trade #1): long a 66.855,90 con stop inicial a 66.731,19 (correcto, 124 USD abajo); al salir, el stop vivo estaba en **68.070,38 — 1.214 USD POR ENCIMA de la entrada**. Salida en el mismo tick, con motivo "stop_loss", a 0,44 USD de la entrada.

**Implicación:** la conclusión previa de la ablación ("ninguna variante rentable, señal rechazada") mezcla dos cosas. La variante A **nunca llegó a probar su dirección**: murió de ejecución, no de señal. La variante B sí tuvo 18/48 trades que sobrevivieron (los que no tenían un swing al otro lado en el fill) y ahí sí se puede juzgar la señal (ver Q1/Q3). Para separar ambas cosas, todas las métricas de excursión se calculan en dos ventanas: **real** (entrada→salida real, documenta lo que hizo el motor) y **sombra** (entrada→+4h = 16 barras, documenta lo que hizo el precio, ignorando la salida rota).

---

## Q1 — MFE/MAE por trade (en R; 1R = |entrada − stop inicial|)

| Métrica | A fade base (n=28) | B break base (n=48) |
|---|---|---|
| Ganadores / perdedores | 0 / 28 | 4 / 44 |
| Salidas instantáneas (<1 s) | 27/28 | 27/48 |
| **Ventana real** MFE_R media / mediana | 0,014 / 0,001 | 0,182 / 0,002 |
| **Ventana real** MAE_R media / mediana | 0,018 / 0,006 | 0,169 / 0,034 |
| Perdedores que nunca vieron +0,25R (real) | 27/28 | 38/44 |
| Perdedores que nunca vieron +0,5R (real) | 28/28 | 40/44 |
| Perdedores que nunca vieron +1R (real) | 28/28 | 44/44 |
| **Ventana sombra (4h)** MFE_R media / mediana | 1,22 / 0,90 | 1,27 / 0,74 |
| **Ventana sombra (4h)** MAE_R media / mediana | 2,13 / 0,90 | 1,37 / 1,00 |
| Perdedores que nunca vieron +0,25R (sombra) | 1/28 | 7/44 |
| Perdedores que nunca vieron +0,5R (sombra) | 7/28 | 14/44 |
| Perdedores que nunca vieron +1R (sombra) | 16/28 | 25/44 |
| Tocó +1R en 4h / tocó −1R en 4h (sombra) | 12/28 vs 12/28 | 20/48 vs 24/48 |
| Primer toque de ±0,5R: favorable vs adverso (sombra) | 13 vs 15 | 26 vs 21 |

**Interpretación.** En la ventana real las excursiones son ridículas (mediana MFE 0,001-0,002R) porque los trades duran 0 segundos: eso mide el bug, no la señal. En la ventana sombra, la dirección es una **moneda al aire**: en A el precio tocó +1R y −1R exactamente en 12/28 casos cada uno, y en B fue 20 vs 24 con MAE media (1,37R) mayor que MFE (1,27R). No hay patrón de "directamente al stop" (solo 1/28 y 7/44 nunca vieron ni +0,25R en 4h): la señal no está sistemáticamente equivocada de dirección, simplemente **no contiene información direccional**. Ojo: N=28 y N=48 son muestras pequeñas; los intervalos son anchos, pero nada aquí sugiere un borde oculto.

## Q2 — Tasa de whipsaw (tocó +0,5R Y −0,5R antes de salir/4h)

| Ventana | A fade base | B break base |
|---|---|---|
| Real (entrada→salida) | 0/28 (trades de 0 s) | 1/48 |
| Sombra (entrada→4h) | **14/28 (50%)** | **24/48 (50%)** |

**Interpretación.** Exactamente la mitad de las entradas ven el precio cruzar ambos umbrales de ±0,5R en las 4 horas siguientes, en las dos variantes. Eso es lo que se espera de entrar en un punto sin información: el precio oscila alrededor de la entrada sin preferencia. El timing de entrada no aporta precisión alguna (con la advertencia de N pequeño de siempre).

## Q3 — Alineación con la tendencia 1h (réplicas sin el gate trend_1h)

| Grupo | A fade (n=95) | B break (n=78) |
|---|---|---|
| Alineado: n, win rate, P&L medio | 27, 0%, −12,44 USD | 45, 8,9% (4 wins), −12,22 USD |
| Contra-tendencia: n, win rate, P&L medio | 68, 0%, −11,58 USD | 33, 0%, −10,50 USD |

**Interpretación.** En A da igual: el bug mata alineados y contrarios por igual (93/95 con stop al otro lado). En B, **los 4 únicos ganadores están todos en el grupo alineado** (4/45 vs 0/33), lo que encaja con la ablación (quitar trend_1h empeoraba); pero el P&L medio alineado es incluso algo peor (−12,22 vs −10,50) porque los perdedores alineados pierden más. Con 4 ganadores totales, N es demasiado pequeño para concluir nada más fuerte que "si algo se salva, va con la tendencia 1h".

## Q4 — Bruto vs comisiones: ¿churn o dirección?

| Variante | Neto | Comisiones | Bruto (neto+fees) | Fees como % de la pérdida neta |
|---|---|---|---|---|
| A fade base (28 trades) | −354,66 | 336,32 | **−18,34** | **94,8%** |
| B break base (48 trades) | −619,51 | 548,95 | **−70,56** | **88,6%** |

**Interpretación.** El movimiento bruto de precio es casi neutro (−18 USD en A sobre 10.000 de balance) y las comisiones son prácticamente toda la pérdida. Pero cuidado con leerlo como "problema de churn de la señal": el bruto es minúsculo *porque* el bug cierra a centímetros de la entrada — cada trade paga ida y vuelta de fees (~7-27 USD) por un viaje de 0 segundos. Sobre la distancia del stop: como muestra la tabla del bug, el stop vivo en la salida casi nunca conservó la distancia inicial de 1,5×ATR — en A base 26/28 estaban al otro lado de la entrada y los 2 restantes encogidos a ~13% de la distancia original; en B solo 7/48 conservaban la distancia inicial o más.

## Q5 — Tasas base post-squeeze (sin operar): ¿predice algo el squeeze?

300 barras-squeeze de 8.736 (3,4%); 173 con tesis fade direccional. Retornos forward en %; "|ret|" = magnitud media (proxy de volatilidad).

| Horizonte | Media squeeze | Media incond. | Mediana squeeze | Mediana incond. | \|ret\| media squeeze | \|ret\| media incond. |
|---|---|---|---|---|---|---|
| +1 barra | −0,009% | −0,001% | −0,011% | −0,002% | 0,112% | 0,145% |
| +4 barras | +0,006% | −0,006% | +0,018% | −0,003% | 0,225% | 0,290% |
| +8 barras | +0,006% | −0,012% | +0,027% | −0,005% | 0,307% | 0,411% |
| +16 barras | −0,020% | −0,024% | +0,010% | −0,013% | 0,417% | 0,573% |

Retorno "alineado con la tesis fade" (n=173): media −0,012% (+4b), −0,014% (+8b), −0,024% (+16b) — todo ≈ 0 o levemente negativo.

**Interpretación.** Dos rechazos claros. (1) **Dirección:** las medias post-squeeze son indistinguibles de cero (p. ej. +0,006% a +4 barras con desviación 0,292%, o sea <1 error estándar con n=300) y la versión alineada con la tesis fade es levemente negativa. (2) **Volatilidad:** al revés de la premisa "compresión → explosión", tras un squeeze el mercado se mueve **menos** que la media incondicional en todos los horizontes (p. ej. 0,417% vs 0,573% a +16 barras). El squeeze detecta que el mercado está quieto… y lo más probable es que siga quieto. Es un filtro de baja volatilidad, no un gatillo de entrada.

## Q6 — Bonus: tasa base de momentum (cruce de EMA20 en 15m + tendencia 1h alineada)

612 eventos (304 cruces al alza con tendencia long, 308 a la baja con tendencia short). Retorno alineado con la tesis:

| Horizonte | Media tesis | Media incond. | Mediana tesis | Mediana incond. |
|---|---|---|---|---|
| +4 barras | −0,017% | −0,006% | +0,005% | −0,003% |
| +8 barras | −0,006% | −0,012% | +0,016% | −0,005% |

**Interpretación.** Las medianas mejoran marginalmente sobre lo incondicional (+0,016% vs −0,005% a +8 barras) pero las medias no acompañan (−0,006%): la cola de perdedores grandes se come la ventaja mediana. Con n=612 y magnitudes de ~1-2 puntos básicos, esto es **evidencia débil, no un borde explotable tal cual** — como mucho sugiere que "a favor de la tendencia 1h" es mejor suelo que "contra ella", coherente con Q3.

---

## Conclusiones

**(a) Bug vs señal.** La pérdida observada en la ablación es ~90-95% ejecución rota, no señal: el trailing estructural sin guarda de lado (`risk.py:199-222`) puso el stop al otro lado de la entrada en 26/28 (A) y 26/48 (B) trades, cerrándolos en el mismo tick del fill y pagando solo spread+fees (fees = 94,8% y 88,6% de la pérdida neta). **Cualquier evaluación de señales futura es inválida hasta arreglar ese guard** (exigir `trail < precio actual` para longs, `trail > precio` para shorts, o trail solo en barra cerrada). La variante A, en rigor, nunca fue probada.

**(b) ¿Predice algo el squeeze?** No. Con el exit roto puenteado (ventana sombra) la dirección post-entrada es una moneda al aire (12/28 tocan +1R y 12/28 tocan −1R en A; MAE ≥ MFE en ambas variantes; 50% de whipsaw exacto en las dos). Y a nivel de tasa base (300 squeezes, sin operar), ni dirección (medias <1 error estándar de cero, tesis fade levemente negativa) ni la esperada expansión de volatilidad — la volatilidad post-squeeze es *menor* que la incondicional en todos los horizontes. La hipótesis squeeze-sobre-niveles queda rechazada dos veces: como entrada y como premisa física.

**(c) Pista más fuerte para la próxima hipótesis.** Primero el fix del trail (sin él no hay medición posible). Después, lo único con señal de vida en estos datos es la **alineación con la tendencia 1h**: los 4 únicos ganadores de B están en el grupo alineado (4/45 vs 0/33), el gate trend_1h fue el único informativo en la ablación, y las medianas del cruce EMA20+tendencia mejoran (débilmente) lo incondicional. Eso apunta a explorar una hipótesis de **continuación/pullback a favor de la tendencia 1h** — pero exigirá un disparador con más información que el squeeze (que resultó ser un filtro de calma, quizá útil justamente como filtro de "no operar"), y validación con N mucho mayor antes de creérsela.

---

## Datos crudos (apéndice)

Todo en `/home/guille/dev/scalping-bot/backtest_runs/autopsia-2026-07-13/`. Los scripts asumen el repo en `/home/guille/dev/scalping-bot` y su venv.

**Regla de memoria (obligatoria en esta VM de 7,7 GB):** todo proceso pesado (réplicas, escaneo de ticks) se lanza envuelto en:
```
systemd-run --user --scope -p MemoryMax=3G --collect -q \
  /home/guille/dev/scalping-bot/.venv/bin/python <script.py> <args>
```
uno a la vez (nunca en paralelo), y los análisis de ticks siempre en streaming día a día con como máximo 2 días adyacentes en memoria (`DayCache` en `mfe_mae_analysis.py`). Antes de cada lanzamiento: `free -h` y no lanzar con <3 GB disponibles.

| Script | Qué hace | Cómo relanzar |
|---|---|---|
| `instrumented_replay.py` | Réplica del backtest capturando aperturas, cierres y snapshots del stop vivo en cada salida. ~8 min por variante/3 meses. | `<wrapper> instrumented_replay.py <fade\|break> <-\|trend_1h> 0.6 2 2026-04-01 2026-07-01 <prefijo_salida>` |
| `squeeze_shadow_replay.py` | Réplica sin trades que vuelca por cada barra 15m: ts, close, in_squeeze, dirección, trend_1h → `bars_squeeze.json`. | `<wrapper> squeeze_shadow_replay.py 0.6 2 2026-04-01 2026-07-01 bars_squeeze.json` |
| `mfe_mae_analysis.py` | Q1/Q2: MFE/MAE en R por trade, ventana real y sombra (4h), whipsaw ±0,5R. Streaming de ticks día a día. | `<wrapper> mfe_mae_analysis.py rep_X_opened.json rep_X_closed.json <label> mfe_X.json` |
| `summarize_mfe.py` | Agrega los JSON de MFE/MAE en las tablas de Q1/Q2. | `.venv/bin/python summarize_mfe.py mfe_fade_base.json mfe_break_base.json` |
| `trend_alignment_analysis.py` | Q3: win rate y P&L por grupo alineado/contra tendencia 1h. Solo JSON, ligero. | `.venv/bin/python trend_alignment_analysis.py rep_X_opened.json rep_X_closed.json <label> out.json` |
| `fees_gross_analysis.py` | Q4: neto/fees/bruto desde trades.csv + resumen de stops finales. | `.venv/bin/python fees_gross_analysis.py <run>/trades.csv rep_X_stopsnaps.json <label> out.json` |
| `trail_bug_stats.py` | Cuantifica el bug: stops al otro lado de la entrada / encogidos vs 1,5×ATR. | `.venv/bin/python trail_bug_stats.py rep_X_opened.json rep_X_closed.json rep_X_stopsnaps.json <label>` |
| `postsqueeze_baserate.py` | Q5/Q6: tasas base forward post-squeeze y post-cruce EMA20 desde `bars_squeeze.json`. | `.venv/bin/python postsqueeze_baserate.py bars_squeeze.json baserates.json` |
| `run_analyses.sh` | Cadena secuencial completa de análisis (con el wrapper en cada paso); toca `ANALYSES_DONE`/`ANALYSES_FAILED`. | `bash run_analyses.sh` |
| `inspect_records.py` | Tabla por trade: entrada, stop inicial, salida, duración, stop vivo al salir. | `.venv/bin/python inspect_records.py <prefijo_replica>` |

Salidas intermedias: `rep_{fade,break}_{base,notrend}_{opened,closed,stopsnaps}.json` (réplicas), `mfe_{fade,break}_base.json` + `mfe_summary.txt` (Q1/Q2), `trend_align_{fade,break}.json` (Q3), `fees_{fade,break}_base.json` (Q4), `bars_squeeze.json` + `baserates.json` (Q5/Q6), `trail_bug_break_notrend.txt`. Runs persistidos de referencia: `2026-07-12_23-51-17_abla-base`, `2026-07-13_15-58-17_ablb-base`, `2026-07-13_00-14-20_abla-no-trend_1h`, `2026-07-13_16-23-57_ablb-no-trend_1h`.
