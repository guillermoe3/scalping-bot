# Tercera opinión — auditoría de la lógica de implementación (verificada contra el código)

Fecha: 2026-07-02

Cadena documental: `docs/strategy-rationale.md` →
`docs/revisiones/analisis-estrategia-scalping-btc-codex.md` +
`docs/revisiones/segunda-opinion-estrategia-scalping-opus.md` →
`docs/mejoras-propuestas.md` → **este documento**.

Diferencia de método respecto a las dos auditorías externas: ni Opus ni Codex
abrieron el código (ambos lo declaran). Este documento verificó **cada hallazgo
contra el código fuente actual** (HEAD `d5fa194`, 2026-07-02) y agrega hallazgos
estructurales nuevos que solo son visibles leyendo el orden real de ejecución en
`main.py`. Se confirmó además, vía `git log`, que **ningún archivo de lógica de
estrategia cambió desde el 2026-06-19** (fecha de las tres auditorías previas):
lo único posterior es Telegram, hooks de notificación y un fix de memoria del
backtest. Todos los documentos anteriores siguen vigentes contra el código de hoy.

---

## 1. Veredicto

**Coincido con el NO-GO para capital real, y lo endurezco.** El diagnóstico
consolidado de `mejoras-propuestas.md` (estructura de costos rota primero,
lógica de señal después) es correcto y queda ratificado contra el código. Pero
la discusión sobre la squeeze quedó corta en un punto que cambia cómo hay que
arreglarla:

> **El bot no puede entrar en la vela del breakout — por construcción.**
> En `main.py:on_candle_1m`, `update_squeeze` (paso 6) corre **antes** de
> `check_entry_signal` (paso 7). La vela que rompe la compresión (rango >
> 0.4×ATR) hace que `update_squeeze` resetee `in_squeeze = False` y
> `squeeze_direction = None` (`signals.py:57-61`) en esa misma pasada, así que
> cuando el pipeline evalúa la entrada, la squeeze ya no existe. **Toda entrada
> posible ocurre mientras el precio sigue comprimido, nunca en el break.**

Esto convierte el debate "¿la dirección está invertida respecto a Volman?" en
una pregunta mal dimensionada. No es que el bot anticipe el break con un signo
discutible: es que la arquitectura actual **no contempla entrar en el break en
absoluto**. Lo que el bot implementa realmente es un modelo de *fade /
continuación pre-break* ("entrar en la dirección de alejamiento del nivel más
cercano, mientras dura la compresión"), en vela de 1m, pagando taker en ambas
puntas. Combinado con el fee drag medido en `mejoras-propuestas.md` §2.2
(mediana ~1.31R por round-trip en ATR de 1m), el sistema tal como está tiene
expectativa estructuralmente negativa salvo que la señal tuviera una tasa de
acierto implausible.

La condición de revisión del veredicto sigue siendo la de
`mejoras-propuestas.md`: expectancy neta de fees positiva, persistida, en un
backtest fiel a producción — pero con un paso previo nuevo: **decidir
explícitamente qué modelo de entrada se quiere ser** (sección 4, propuesta N1),
porque hoy no se puede "corregir la dirección" sin antes resolver que el break
ni siquiera es alcanzable como momento de entrada.

---

## 2. Validación de las auditorías externas, hallazgo por hallazgo

Verificación directa contra el código de cada afirmación relevante:

| # | Hallazgo (origen) | Veredicto | Evidencia en código |
|---|---|---|---|
| 1 | La squeeze asigna dirección pre-break; Volman no lo hace (Opus §2) | **Confirmado y agravado** | `signals.py:54-56` asigna por signo; además el break es inalcanzable como entrada (sección 3.1) |
| 2 | `sign(price − level)` no distingue soporte de resistencia (Opus §2.4, Codex §4.1) | **Confirmado** | `_nearest_key_level` (`signals.py:15-21`) mezcla `swing_highs + swing_lows` en una sola lista y descarta el tipo |
| 3 | Fee drag alto si el TF base es chico (Opus §4.1) | **Confirmado** | TF base = 1m: squeeze y régimen operan sobre `candles_1m`, ATR período 14 sobre 1m; fees taker 0.05%/lado en `risk.py:64,98,225`. Los números medidos de `mejoras-propuestas.md` §2.2 aplican tal cual |
| 4 | Breathing stop rompe el presupuesto de 0.5% (Opus §4.2) | **Confirmado** | `risk.py:145-165`: solo expande, nunca contrae; el size quedó fijado con `ATR_entry` en `open_position` — la pérdida real en el stop expandido es `0.5% × ATR_live/ATR_entry` |
| 5 | CVD vela-a-vela demasiado fino (Opus §4.4, Codex) | **Confirmado** | `order_flow.py:41-44` compara `[-1]` vs `[-2]` literales, no pivotes |
| 6 | `trend_5m` calculado y sin uso (todos) | **Confirmado, con extra** | No aparece en `signals.py`; además se calcula **dos veces por vela** — `regime.update_mtf_trend` y `context.update_mtf_trends` son funciones duplicadas y ambas corren en `on_candle_1m` (`main.py:59-60`) |
| 7 | Macro SPY stale fuera de horario US (Opus §4.3) | **Confirmado y agravado** | `context.py:72-73`: si yfinance devuelve vacío (mercado cerrado, finde), `_update` retorna temprano **sin limpiar los flags** — un bloqueo activado el viernes puede persistir todo el fin de semana (sección 3.5) |
| 8 | Sin look-ahead (dejado "a verificar" por Opus, resuelto en `mejoras-propuestas.md` §2.1) | **Re-confirmado** | Todo el pipeline de señal corre solo en `on_candle_1m` (vela cerrada); `state.live_1m` solo se usa para volume velocity, no para señal |
| 9 | Filtros inertes en backtest: OB imbalance + macro (todos) | **Confirmado** | `backtest.py`/`backtest_feed.py` no mencionan macro ni snapshots de book; los defaults de `MarketState` dejan `get_book_imbalance` en `(1.0, "neutral")` y los bloqueos macro en `False` toda la corrida |
| 10 | Sin resultados persistidos; cache de un solo mes (todos) | **Sigue vigente al 2026-07-02** | No existe ningún `.csv` en el repo; `backtest_cache/` solo tiene noviembre 2025. La corrida multi-día posterior al fix de memoria validó lógica de señal, no rentabilidad |
| 11 | Falta cost gate (Codex §4.2) | **Confirmado** | Nada en `check_entry_signal` compara distancia a TP1 contra fees+spread |
| 12 | Breakeven debería ser neto, no precio de entrada (Codex §5-P4) | **Confirmado como bug actual** | `risk.py:131-142` mueve el SL exactamente a `entry_price`: una salida "breakeven" pierde ~0.1% del notional en fees (dos legs taker) — todo breakeven es una pérdida |

**Adjudicación de la única discrepancia real entre Opus y Codex:** la tabla de
casos de Codex ("Cambio 1": compresión debajo de resistencia → esperar LONG)
presupone la lectura de ruptura clásica del nivel; Opus demuestra que el canon
de Volman no pre-asigna dirección — el break la revela. `mejoras-propuestas.md`
§3 ya adoptó la versión de Opus y es la correcta. El hallazgo estructural de la
sección 3.1 la refuerza: discutir *qué* dirección pre-asignar es secundario
cuando el momento de entrada canónico (el break) es hoy inalcanzable.

---

## 3. Hallazgos nuevos (no presentes en ningún documento anterior)

### 3.1 La entrada en el break es estructuralmente imposible — Severidad: alta

Descrito en el veredicto. Consecuencia práctica: las dos opciones de fix de
`mejoras-propuestas.md` P1-1 ("derivar la dirección del break real" vs.
"trackear tipo de nivel") no son intercambiables — la primera exige
reestructurar `update_squeeze` para que el estado de squeeze **sobreviva a la
vela que rompe** (p. ej. un estado `squeeze_broken` válido 1-2 velas), no solo
cambiar un signo. Hoy `else: in_squeeze = False` (`signals.py:57-61`) borra la
oportunidad en el mismo tick en que la confirma.

### 3.2 La "confirmación" en régimen BREAKOUT es más débil de lo que Opus asumió — Severidad: media-alta

Opus acreditó `signals.py:112-120` como mitigación parcial ("se parece a
esperar el break"). Verificado contra el código, la mitigación es casi
cosmética: la vela que "confirma" la dirección es, por construcción, una vela
**comprimida** (pasó `is_compressed`: rango ≤ 0.4×ATR, luego cuerpo ≤ 0.4×ATR).
Que una vela de rango minúsculo cierre verde o roja es micro-ruido, no una
confirmación de ruptura. Además la combinación régimen BREAKOUT + squeeze es
casi auto-contradictoria: entrar a BREAKOUT exige 3 velas consecutivas con
cuerpo ≥ 1.5×ATR (`regime.py:69-70` + histéresis de 3), e inmediatamente
después se necesitan 3 velas consecutivas de rango ≤ 0.4×ATR — la señal en ese
régimen probablemente dispare casi nunca, y cuando dispare será por régimen
stale (ver 3.3). El ablation de P0-8 debería medir la frecuencia por régimen
para confirmar esta sospecha.

### 3.3 El régimen nunca decae: staleness ilimitado — Severidad: media

`update_regime` ignora candidatos UNKNOWN (`regime.py:100-101`), lo que
significa que el régimen vigente **persiste indefinidamente** mientras las
velas sean ambiguas. Un tag BREAKOUT puede seguir vivo horas después del spike
que lo causó, y ese tag stale: (a) cambia el período de la EMA
(`indicators.py`), (b) activa la pseudo-confirmación de 3.2, y (c) satisface el
gate 1 del pipeline. La histéresis protege contra flip-flop, pero no hay
mecanismo de expiración. Propuesta: N3 (sección 4).

### 3.4 La dirección de la squeeze puede flip-flopear mientras la squeeze se arma — Severidad: media

`update_squeeze` recalcula `squeeze_direction` y `squeeze_reference_level` en
**cada vela** mientras `in_squeeze` sigue activo, contra el nivel más cercano de
una lista que se reconstruye entera cada cierre (`main.py:63-67`). El nivel de
referencia puede saltar de un swing low a un swing high entre velas (con la
dirección invirtiéndose), y la señal dispara con la foto de la última vela sin
exigir que la dirección haya sido estable durante las 3+ velas de compresión.
Una "compresión de 5 velas" puede haber cambiado de tesis 3 veces y aun así
entrar.

### 3.5 El bloqueo macro puede quedar congelado con datos viejos — Severidad: media (solo live)

Los flags `macro_blocks_*` solo se recalculan si yfinance devuelve datos
(`context.py:72-73` retorna temprano si vacío). Con SPY cerrado (noches, findes,
feriados — la mayoría del tiempo de BTC), el último estado persiste: un bloqueo
de longs activado un viernes con SPY cayendo puede seguir vetando longs todo el
fin de semana, con una correlación que ya no describe nada. Complementa el
hallazgo 7 de Opus con el mecanismo exacto: no es solo dato stale, es **estado
de bloqueo stale sin TTL**.

### 3.6 El estimador de volume velocity no es comparable entre momentos — Severidad: baja-media

`update_volume_velocity` (`momentum.py:15-22`) divide el volumen acumulado de
la vela **en formación** por el tiempo transcurrido dentro de ella. La
velocidad de referencia se captura al entrar (justo tras un cierre → promedio
de vela completa), pero las mediciones posteriores son instantáneas
intra-vela: en los primeros segundos de cada vela nueva el cociente es ruido
puro, y unos segundos tranquilos tras un rollover pueden disparar un
`momentum_abort` espurio (el umbral es <30% de la velocidad de entrada,
chequeado en cada trade tick pasado el minuto 3). Propuesta: ventana rodante de
volumen (p. ej. últimos 60s de trades) en lugar del cociente intra-vela.

---

## 4. Propuestas de cambio

El plan priorizado de `mejoras-propuestas.md` §4 queda **ratificado íntegro**
(P0: medición de frecuencia×costo, maker/post-only, cost gate, timeframe,
modelar filtros inertes, ampliar histórico, persistir resultados, ablation).
No lo repito; lo que sigue se **inserta** en ese plan:

### Nuevas — P0

| # | Propuesta | Dónde | Por qué |
|---|---|---|---|
| N1 | **Decidir el modelo de entrada de forma explícita** antes de tocar `update_squeeze`. Opción A: asumir el modelo fade/pre-break actual como tesis propia (no-Volman), trackeando tipo de nivel (soporte/resistencia) para que el signo tenga significado. Opción B: pasar a entrada por confirmación de break — requiere que el estado de squeeze sobreviva a la vela de ruptura (`squeeze_broken` con TTL de 1-2 velas) y entrada en la dirección del break real. Correr el ablation P0-8 **para ambas variantes** y decidir con datos | `signals.py:26-61`, `state.py` | Sección 3.1 — "corregir la dirección" no es un cambio de signo; el break hoy es inalcanzable como entrada. Reemplaza y precisa a `mejoras-propuestas.md` P1-1 |

### Nuevas — P1

| # | Propuesta | Dónde | Por qué |
|---|---|---|---|
| N2 | **Breakeven neto:** mover el SL a `entry × (1 ± 2×TAKER_FEE_RATE + buffer)`, no al precio de entrada | `risk.py:120-142` | Sección 2, hallazgo 12 — hoy toda salida "breakeven" es una pérdida de ~0.1% del notional |
| N3 | **Expiración de régimen:** tras N velas sin candidato que confirme el régimen vigente (p. ej. 20-30), degradar a UNKNOWN | `regime.py:89-117` | Sección 3.3 — un BREAKOUT stale de hace horas sigue habilitando entradas y cambiando la EMA |
| N4 | **Estabilidad direccional de la squeeze:** congelar `squeeze_direction`/`squeeze_reference_level` al armarse la squeeze, o exigir que la dirección haya sido la misma durante las `SQUEEZE_MIN_BARS`; resetear el contador si la tesis cambia | `signals.py:48-56` | Sección 3.4 — hoy la tesis puede invertirse entre velas sin invalidar la squeeze |
| N5 | **TTL del bloqueo macro:** si no hay dato fresco de SPY en X minutos (mercado cerrado o fetch fallido), limpiar `macro_blocks_*` en vez de congelarlos | `context.py:52-115` | Sección 3.5 — complementa la propuesta P1-5 existente (degradar a sesgo blando o sacar) con el fix mínimo si se mantiene |

### Nuevas — P2

| # | Propuesta | Dónde | Por qué |
|---|---|---|---|
| N6 | **Velocity por ventana rodante:** medir volumen de los últimos 60s de trades en vez de `volumen_vela_viva / elapsed` | `momentum.py:15-22` | Sección 3.6 — evita aborts espurios tras rollover de vela |
| N7 | **Deduplicar el cálculo de tendencia MTF:** `regime.update_mtf_trend` y `context.update_mtf_trends` son la misma función con umbrales duplicados; dejar una | `regime.py:122-139`, `context.py:12-28`, `main.py:59-60` | Higiene de lógica: dos fuentes de verdad para el mismo estado invitan a divergencia silenciosa cuando alguien ajuste un umbral |

### Qué no tocar (ratificación)

Sigue vigente `mejoras-propuestas.md` §5: no optimizar parámetros hasta que el
harness sea fiel a producción y exista el ablation. Agrego: tampoco implementar
el scoring continuo de Codex (P2-3) antes de resolver N1 — cambiar el mecanismo
de agregación de gates sobre un modelo de entrada que aún no se decidió es
optimizar en el orden equivocado.

---

## 5. Síntesis final

- Las dos auditorías externas fueron **notablemente precisas trabajando a
  ciegas**: de 12 afirmaciones verificables contra el código, las 12 se
  confirmaron (dos, agravadas). Ninguna afirmación de Opus o Codex resultó
  falsa. La única corrección es de énfasis, no de hecho: la mitigación del
  régimen BREAKOUT que Opus acreditó es más débil de lo que parecía (3.2).
- El orden de prioridades de `mejoras-propuestas.md` (costos antes que señal)
  es correcto y queda ratificado.
- El aporte nuevo de esta pasada es estructural: el bot es hoy un sistema de
  entrada pre-break por diseño (no por un signo discutible), con varios estados
  que pueden quedar stale sin expiración (régimen, bloqueo macro, tesis de la
  squeeze). Nada de eso es visible sin leer el orden de ejecución de
  `main.py:on_candle_1m`, que es exactamente el límite epistémico que ambas
  auditorías externas declararon.
