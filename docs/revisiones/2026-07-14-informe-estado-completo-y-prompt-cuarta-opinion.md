# Informe de estado completo del proyecto + prompt para cuarta opinión externa

Fecha: 2026-07-14
Propósito: (1) dejar en un solo documento la historia completa del proyecto —
plan original, cambios, desarrollo, pruebas y resultados — y (2) servir de
prompt autocontenido para una revisión externa (Fable, Codex u otra IA) que
proponga alternativas de señal, nuevas variables o cambios de algoritmo.

Cadena de documentos previa: `docs/strategy-rationale.md` →
`docs/revisiones/analisis-estrategia-scalping-btc-codex.md` +
`docs/revisiones/segunda-opinion-estrategia-scalping-opus.md` +
`docs/revisiones/tercera-opinion-logica-implementacion-fable.md` →
`docs/mejoras-propuestas.md` (veredicto consolidado + plan P0-P3, con
secciones de estado acumuladas al final).

---

## 1. El plan original (qué era el bot al inicio)

Un bot de scalping discrecional codificado, para BTC/USDT en Binance Futures
(paper y live), basado en el patrón "The Squeeze" de Bob Volman: precio
comprimiéndose en velas chicas contra un nivel clave (soporte/resistencia de
swings recientes) como antesala de una expansión.

**Pipeline de decisión original (10 condiciones en AND, todas debían pasar):**

1. Régimen conocido (BREAKOUT / TIGHT_CHANNEL / TRADING_RANGE, con histéresis)
2. Squeeze armada (rango ≤ 0.4×ATR durante 3 velas, a ≤ 0.5×ATR de un nivel)
3. Sin posición abierta
4. Dirección de squeeze resuelta (según el lado del nivel donde está el precio)
5. Spread aceptable (≤ 5% del ATR)
6. No contra-tendencia del timeframe mayor (EMA 15m)
7. Sin bloqueo macro (correlación BTC-SPY vía yfinance)
8. En régimen BREAKOUT, la última vela confirma la dirección
9. Sin divergencia de CVD en contra (delta de volumen agresor)
10. Sin imbalance del order book en contra (promedio de 5 snapshots)

**Gestión de riesgo (sin cambios sustanciales hasta hoy, y es la parte mejor
fundada):** riesgo fijo 0.5% del balance diario por trade; stop inicial
1.5×ATR; TP1 a 2R cerrando 50%; breakeven tras 0.8×ATR de profit; breathing
stop (expande con el ATR vivo); trailing estructural a swings; salida por
tiempo; abort por colapso de momentum; kill switch diario (−2% o 3 pérdidas
seguidas); reconciliación contra el exchange al arrancar.

**Reloj y ejecución originales:** señal evaluada al cierre de cada vela de
**1 minuto**; entradas y salidas a mercado (**taker**, 0.05% por lado).

**Estado de validación original:** ninguna. El propio
`docs/strategy-rationale.md` (2026-06-19) lo declaró: heurística discrecional
codificada, sin ningún backtest persistido que demostrara edge neto de fees.

---

## 2. La cadena de auditorías (junio 2026) y el veredicto

Tres revisiones (autoauditoría + Codex + Opus, luego una tercera opinión de
Fable verificada contra el código) coincidieron en **NO-GO para capital
real**. Los hallazgos que ordenaron todo el trabajo posterior:

- **El hallazgo más grave no era la señal sino los costos:** medido contra
  datos reales del repo (30 días de velas 1m), el fee round-trip taker en la
  volatilidad mediana de 1m costaba **~1.31R** — más que todo el riesgo
  asumido por trade. Con esa estructura, ni una señal perfecta es rentable.
- **La dirección de la squeeze no era "Volman invertido" sino otro modelo:**
  el canon de Volman no asigna dirección antes del break; el código la
  asignaba por el lado del nivel, sin distinguir si el nivel era soporte o
  resistencia. Quedó planteada la **decisión N1**: ¿fade coherente con el
  tipo de nivel, o entrada por confirmación de ruptura?
- **Backtest y bot en vivo eran estrategias distintas:** 2 de los 10 gates
  (order book, macro) quedan inertes en simulación.
- Plan priorizado P0-P3 en `docs/mejoras-propuestas.md`: arreglar costos,
  ampliar histórico, persistir corridas, ablación de gates, y recién después
  tocar lógica de señal.

---

## 3. Lo que se desarrolló (cronología de cambios)

| Fecha | Cambio | Resultado |
|---|---|---|
| 2026-07-03 | **Pivot de estructura de costos (P0-2, P0-4):** reloj de señal 1m→15m; filtro de tendencia reemplazado por EMA-80 sobre 15m (≈EMA-20 de 1h, `trend_1h`); entradas convertidas a **limit post-only (maker)** con modelo de fill conservador (solo llena si el precio atraviesa el límite) y timeout de 300s; ruta live GTX. | Fee drag esperado: de ~1.30R a **~0.17R** por round-trip. |
| 2026-07-03 | **P0-6/P0-7:** descargador de dumps oficiales de Binance Vision + cache compacto por día (91 días, abr-jun 2026); persistencia de cada corrida (meta + summary + trades.csv + comparador HTML). Al migrar se descubrió que el cache viejo por REST perdía 0.4-0.75% de los trades. | Smoke de 3 meses: **0 trades en 91 días** — los umbrales de squeeze estaban calibrados para 1m. |
| 2026-07-03 | **Sweep de umbrales de squeeze** (7 variantes de compresión × velas mínimas). | Todas pierden; el win rate CAE al abrir el embudo (25 trades/20% → 173 trades/10%). La dirección fade parecía anti-predictiva; N1 pasó a ser el bloqueante único. |
| 2026-07-12/13 | **N1 + P0-8:** implementadas ambas variantes (A: fade exigiendo coherencia con el tipo de nivel; B: entrada por ruptura confirmada con ventana de 2 velas) + harness de ablación (gates nombrados y desactivables con contadores de veto, flags reproducibles, matriz pre-registrada de 12 corridas). | Primera ablación: A 28 trades / 0% aciertos; B 48 / 8.3%. Ninguna adoptada. **Pero…** |
| 2026-07-13 | **Autopsia de trades:** los números estaban contaminados por un bug de ejecución — el trailing estructural adoptaba stops del lado equivocado del precio y los trades morían en el mismo tick del fill (27/28 de A duraron <1 segundo; las comisiones eran el 94.8% de la pérdida). | La variante A nunca había probado su señal. Además la autopsia midió tasas base limpias (ver sección 4). |
| 2026-07-13/14 | **Fix del trail** (guarda de lado, TDD con tests de regresión failing-first) + **re-corrida completa de la matriz de 12**. | Veredicto limpio (sección 4): ninguna variante se adopta. Rechazo ahora legítimo. |

**Método de trabajo:** todo con TDD (suite hoy en ~300 tests verdes), specs y
planes versionados en `docs/superpowers/`, corridas persistidas en
`backtest_runs/` con commit de git en el meta, criterios de adopción
**pre-registrados antes de correr** (P&L neto > 0 y ≥ 30 trades).

---

## 4. Los resultados (evidencia vigente, medición limpia)

Ventana: 2026-04-01 → 2026-07-01 (91 días de trades tick a tick de Binance
Vision). Reporte: `backtest_runs/ablation-2026-07-14.md`. Autopsia:
`backtest_runs/autopsia-2026-07-13/autopsia-trades.md`.

### 4.1 Ablación re-corrida (post-fix del trail)

| Corrida | Trades | Win rate | P&L neto (sobre $10k) | Profit factor |
|---|---|---|---|---|
| A (fade) base | 25 | 32.0% | −$248.69 | 0.30 |
| A sin gate trend_1h | 83 | 30.1% | −$1,294.75 | 0.30 |
| A sin gate cvd | 31 | 32.3% | −$199.39 | **0.51** |
| B (break) base | 47 | 27.7% | −$574.12 | 0.29 |
| B sin gate trend_1h | 77 | 28.6% | −$836.79 | 0.38 |

Lecturas clave:
- **Ninguna variante es rentable** con ninguna combinación de gates.
- **`trend_1h` es el único gate claramente informativo:** quitarlo multiplica
  la pérdida (filtra trades aún peores que los que deja pasar).
- **El gate `cvd` parece vetar trades buenos:** quitarlo mejora A (PF
  0.30→0.51), aunque sigue perdedora.
- `regime_known` y `breakout_align` no vetan nada (corridas idénticas a
  base). `macro` y `ob_imbalance` siguen inertes en backtest (sin medir).

### 4.2 Tasas base (sin operar — la evidencia más contundente)

Del estudio de 300 squeezes y ventanas forward sobre los mismos 3 meses:

- **Dirección post-squeeze: moneda al aire.** Retornos medios
  indistinguibles de cero (<1 error estándar); la versión alineada con la
  tesis fade es levemente negativa.
- **La premisa física "compresión → explosión" es falsa en estos datos:**
  tras un squeeze el mercado se mueve MENOS que el promedio incondicional en
  todos los horizontes (|ret| a +16 velas: 0.417% vs 0.573%). El squeeze
  detecta calma… y predice más calma. Sirve como filtro de "no operar", no
  como gatillo.
- **La única pista con vida: alineación con la tendencia 1h.** Los 4 únicos
  ganadores del dataset original estaban todos alineados (4/45 vs 0/33 en
  contra), coherente con la ablación. Pero la tasa base del disparador obvio
  (cruce de EMA-20 en 15m + tendencia 1h a favor, n=612) da una mejora de
  apenas 1-2 puntos básicos en la mediana y la media no acompaña: **evidencia
  débil, no un borde explotable tal cual.**

### 4.3 Conclusión vigente

La hipótesis squeeze-sobre-niveles en 15m queda **rechazada dos veces**
(como entrada operada y como premisa de tasa base), con estructura de costos
ya arreglada y medición limpia. Cualquier trabajo futuro de señal debe partir
de una **hipótesis nueva** y pasar por el harness de ablación existente antes
de tocar producción. Pendientes no bloqueantes: cost gate (P0-3, sin señal
rentable no urge), modelar los gates inertes (P0-5), paper trading en vivo
para validar el modelo de fills maker.

---

## 5. Prompt para la cuarta opinión (copiar desde acá)

> **Contexto.** Sos un revisor externo (cuarta opinión) de un proyecto de bot
> de trading para BTC/USDT en Binance Futures. El proyecto ya pasó por tres
> auditorías y dos ciclos de medición rigurosa; no busques errores de
> proceso — el proceso está bien (TDD, criterios pre-registrados, ablación
> por gate, autopsia de trades, fix de un bug de ejecución y re-medición
> limpia). Lo que se busca es **dirección estratégica**: la hipótesis de
> señal original está muerta y hay que decidir qué probar después, o si no
> probar nada.
>
> **Si tenés acceso al repo**, leé en este orden:
> `docs/mejoras-propuestas.md` (historia completa con estados),
> `backtest_runs/ablation-2026-07-14.md` (evidencia vigente),
> `backtest_runs/autopsia-2026-07-13/autopsia-trades.md` (tasas base),
> `signals.py`, `risk.py`, `config.py`. Si no tenés acceso, el resumen de
> evidencia de abajo es fiel y suficiente.
>
> **Qué es el bot hoy:** señal evaluada al cierre de velas de 15m; entrada
> maker post-only con timeout (fee drag ~0.17R por round-trip, ya no es el
> problema); riesgo 0.5%/trade, stop 1.5×ATR, TP1 2R parcial, trailing
> estructural, salidas por tiempo/momentum; kill switch. El disparador era
> "squeeze de Volman": compresión de rango contra un nivel de swing.
>
> **Evidencia medida (91 días tick a tick, abr-jun 2026, BTC/USDT):**
> 1. El squeeze NO predice dirección (retornos forward ≈ 0, n=300) y NO
>    predice expansión de volatilidad — al contrario, tras un squeeze el
>    mercado se mueve menos que el promedio (0.417% vs 0.573% de |retorno| a
>    4 horas). Dos modelos de entrada sobre ese disparador (rebote en el
>    nivel y ruptura confirmada) pierden con profit factor ~0.30 en toda la
>    matriz de ablación de gates.
> 2. El único filtro que aporta es la tendencia de 1h (EMA-80 sobre 15m):
>    los 4 únicos trades ganadores iban a favor de ella (4/45 alineados vs
>    0/33 en contra) y quitarla multiplica las pérdidas.
> 3. Pero la tasa base del disparador obvio de continuación (cruce de EMA-20
>    de 15m a favor de la tendencia 1h, n=612) da solo +1-2 puntos básicos de
>    mediana a 1-2 horas, con media negativa: la cola de perdedores grandes
>    se come la ventaja. No es un edge explotable tal cual.
> 4. El filtro de divergencia de CVD (delta de volumen) parece vetar trades
>    buenos: quitarlo mejora el profit factor de 0.30 a 0.51 (sigue perdedor).
> 5. Datos disponibles hoy: 91 días de trades tick a tick + klines 1m/15m,
>    un solo activo (BTC/USDT), sin funding rate, sin open interest, sin
>    liquidaciones, order book solo en vivo (no historizable con lo actual).
>
> **Preguntas concretas (respondé cada una, con tu nivel de confianza):**
>
> 1. **¿Hay razones para creer que existe un edge capturable en BTC 15m para
>    un bot retail de este estilo**, dado que dos hipótesis direccionales
>    murieron y las tasas base dan planas? ¿O la conclusión honesta es que
>    este espacio (señales de price action puro sobre un solo activo en
>    timeframe intradía) está arbitrado y hay que moverse de espacio (otro
>    timeframe, otro mecanismo, carry/funding, o no operar)?
> 2. **¿Qué variables NUEVAS agregarías antes que seguir recombinando las
>    existentes?** Candidatas que consideramos: funding rate (histórico
>    gratuito en Binance), open interest, liquidaciones, hora del día/sesión,
>    día de la semana, volatilidad realizada multi-horizonte, distancia a
>    máximos/mínimos de 24h, dominancia/correlación con ETH. ¿Cuáles tienen
>    mejor prior de aportar información direccional en 15m-4h y por qué?
>    ¿Alguna que no esté en la lista?
> 3. **¿Cambiarías el algoritmo de decisión?** Hoy es un disparador + gates
>    binarios en AND. Alternativas: score continuo con umbral, régimen
>    primero (clasificar tendencia/rango y elegir sub-estrategia), reversión
>    a la media en vez de momentum/continuación, o un clasificador simple
>    entrenado con features (con las trampas de overfitting que eso trae con
>    ~25-80 trades por trimestre). ¿Qué recomendás y qué NO, con este tamaño
>    de muestra?
> 4. **¿Qué dice la evidencia pública** (papers, bots open source con track
>    record verificable, literatura de microestructura cripto) sobre qué
>    funciona en intradía BTC para retail sin ventaja de latencia? Si vas a
>    citar estrategias conocidas (grid, DCA, market making pasivo, momentum
>    multi-día, carry de funding), evaluá cada una contra NUESTRA
>    infraestructura (un activo, datos tick de 3 meses, ejecución maker ya
>    construida, gestión de riesgo ATR sólida) y contra el riesgo de
>    supervivencia/marketing en la evidencia pública.
> 5. **Método para el próximo ciclo:** ¿validás el enfoque "degustación
>    primero" (estudios de tasa base con scripts sobre los datos existentes,
>    sin tocar el bot, para descartar hipótesis en horas en vez de días) y
>    qué diseño de estudio proponés para las 2-3 hipótesis que más te
>    convenzan? Incluí: definición exacta del evento, horizonte forward,
>    métrica (mediana Y media, no solo una), tamaño de muestra mínimo y
>    umbral pre-registrado para "pasa a implementación".
>
> **Restricciones para tus propuestas:** sin capital real hasta tener edge
> neto de fees demostrado y persistido; presupuesto de cómputo modesto (VM
> chica — los estudios deben correr día a día, no cargar 3 meses en RAM);
> preferencia fuerte por hipótesis falsables rápido y con criterio de
> adopción pre-registrado; el harness de ablación existente es reutilizable
> y toda señal nueva debe poder expresarse como disparador + gates para
> pasar por él. No propongas optimizar parámetros de la señal muerta.

---

## 6. Nota de método para quien lea la respuesta externa

Al recibir la cuarta opinión, contrastarla con
`superpowers:receiving-code-review` en mente: verificar técnicamente las
afirmaciones antes de implementar nada, exigir que cada propuesta venga con
su estudio de tasa base barato antes de escribir código del bot, y registrar
el criterio de adopción ANTES de correr la medición (como se hizo con la
ablación). Las dos hipótesis anteriores murieron correctamente: eso no es un
fracaso del proceso, es el proceso funcionando.
