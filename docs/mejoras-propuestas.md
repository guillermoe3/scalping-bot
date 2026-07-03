# Mejoras propuestas para el bot — veredicto y plan de acción

Fecha: 2026-06-19

Cadena de documentos: `docs/strategy-rationale.md` (rationale propio) →
`docs/revisiones/analisis-estrategia-scalping-btc-codex.md` +
`docs/revisiones/segunda-opinion-estrategia-scalping-opus.md` (dos auditorías
externas independientes) → **este documento** (veredicto consolidado + plan
de mejoras).

---

## 1. Veredicto consolidado

**NO-GO para capital real, todavía.** Los dos reportes externos coinciden en
esta conclusión con el rationale original, y la verificación propia hecha
para este documento (sección 2) la refuerza con un hallazgo cuantitativo
nuevo que ninguno de los tres documentos anteriores tenía: **medido contra
datos reales de BTC del propio repo, el costo de fees por round-trip se come
entre 0.7R y 1.3R en la volatilidad típica de 1 minuto — antes de evaluar si
la señal de entrada acierta algo.**

Esto cambia el orden de prioridades. La pregunta abierta original ("¿la
dirección de la squeeze está invertida?") es real y hay que resolverla, pero
**no es el problema más grave**: aunque la señal fuera perfecta, el bot tal
como está configurado (velas de 1m, órdenes taker) puede no ser rentable por
estructura de costos. Hay que resolver el problema de costos/frecuencia antes
o en paralelo a cualquier ajuste de lógica de señal — optimizar la señal
sobre una estructura de costos rota es ruido.

Condición para revisar este veredicto: completar P0 (sección 4) y obtener
expectancy neta de fees positiva y persistida en al menos un backtest
walk-forward fiel a producción.

---

## 2. Hallazgos verificados de forma independiente para este documento

Ninguno de los dos reportes externos abrió el código fuente (ambos lo
declaran explícitamente como límite epistémico). Para este veredicto sí se
verificó contra el repo:

### 2.1 No hay look-ahead — punto que Opus dejó como "a verificar", ahora resuelto

`main.py:31-110` (`wire_strategy`) muestra que `check_entry_signal`,
`update_squeeze`, `update_regime` y `detect_swing_points` se ejecutan
**únicamente** dentro de `on_candle_1m` (`main.py:47-85`), que dispara al
**cierre** de cada vela de 1m — nunca sobre la vela en formación
(`state.live_1m`). El pipeline de entrada opera estrictamente sobre velas
cerradas, en vivo y en backtest (mismo handler, ver `wire_strategy`
reutilizado por `backtest.py`). **Limpio: sin look-ahead en la señal.**

### 2.2 Fee drag medido contra datos reales del propio repo (no estimado)

Opus estimó el fee drag con un ATR% de ejemplo (0.10%–0.50%) sin tener el
dato real. Se calculó el ATR real de BTC en velas de 1m sobre
`backtest_cache/BTCUSDT_klines1m_1779235200000_1781827200000.json` (~30 días,
noviembre 2025, 43,185 velas, Wilder ATR período 14 — mismo cálculo que
`indicators.py:12-32`):

| Percentil | ATR como % del precio (vela 1m) |
|---|---:|
| p10 | 0.021% |
| p25 | 0.030% |
| p50 (mediana) | **0.051%** |
| p75 | 0.084% |
| p90 | 0.126% |
| media | 0.064% |

Aplicando la fórmula de Opus (`F/R = 0.000667 / ATR%`, derivada de
`ACCOUNT_RISK_PCT=0.005`, `INITIAL_SL_ATR=1.5`, `TAKER_FEE_RATE=0.0005`/lado):

| ATR% | Fee round-trip en R |
|---|---:|
| p25 (0.030%) | ~2.22R |
| **p50 (0.051%)** | **~1.31R** |
| p75 (0.084%) | ~0.79R |
| p90 (0.126%) | ~0.53R |

**Lectura:** en la mitad de las velas de 1m de un mes real de BTC, el costo
de fees de ida y vuelta **supera el riesgo total asumido en el trade**
(1.31R > 1R). Un trade que llega a TP1 (2R) en condiciones de volatilidad
mediana cierra, neto de fees, en torno a **0.7R**, no 2R. Esto es **antes**
de spread real y slippage. Es el hallazgo más grave de toda la cadena de
auditoría — más urgente que la duda sobre la dirección de la squeeze, porque
aplica sin importar si la señal acierta o no.

---

## 3. Adjudicación de la discrepancia squeeze: rationale vs. Opus

El rationale original (`strategy-rationale.md`, sección 2) planteó la duda
como "¿está invertida la dirección?". El reporte de Opus (sección 2 de su
documento) refina esa pregunta de forma más precisa, y se adopta esa
versión como la correcta para este plan de mejoras:

- El método canónico de Volman **no asigna dirección antes del break** — la
  compresión es la "energía acumulada", y el breakout en sí revela y
  confirma la dirección.
- `signals.py:54-56` (`squeeze_direction = LONG si last_price > key_level`)
  asigna dirección **antes** del break, por posición relativa al nivel. No es
  la versión "invertida" de Volman: es un **modelo distinto**
  (continuación según el lado del nivel donde está el precio) que el canon
  no contempla.
- Problema adicional, independiente del nombre: `sign(price - key_level)` no
  distingue si el nivel más cercano es un swing **high** (resistencia) o un
  swing **low** (soporte) — el mismo signo puede representar tesis opuestas
  según cuál sea.
- Mitigación parcial ya existente: en régimen `BREAKOUT` el código exige que
  la última vela confirme la dirección (`signals.py:112-120`), lo cual sí se
  parece a "esperar el break". El agujero está en `TIGHT_CHANNEL` y
  `TRADING_RANGE`, donde no hay esa confirmación.

---

## 4. Plan de mejoras, priorizado

### P0 — Bloqueante antes de cualquier capital real

| # | Mejora | Dónde | Por qué (hallazgo) |
|---|---|---|---|
| 1 | Medir frecuencia real de señales que pasan los 10 gates sobre un rango amplio, y multiplicarla por el fee drag medido (sección 2.2) para saber si hace falta más de lo que cualquier win rate razonable puede compensar | nuevo script de análisis sobre `backtest.py` | Sección 2.2 — el fee drag puede dominar el resultado con independencia de la señal |
| 2 | Evaluar pasar entradas/salidas de taker a maker (post-only) en modo live | `execution.py:55-79`, `config.py:74` (agregar `MAKER_FEE_RATE`) | Sección 2.2 — pasar de 0.05%/lado a fee maker reduce el fee round-trip a una fracción; es la palanca individual más efectiva para revertir la tabla de la sección 2.2 |
| 3 | Agregar un *cost gate* antes de abrir posición: rechazar si la distancia esperada a TP1 no cubre fees + spread + margen de seguridad | `signals.py:check_entry_signal`, nueva condición antes del `return direction` final | Mismo hallazgo — hoy nada impide abrir un trade cuyo TP1 no cubre ni los fees |
| 4 | Subir el timeframe base de la señal (1m → 3m/5m) **o** confirmar que el fee maker (#2) ya resuelve el problema sin tocar el timeframe | `config.py:16` (`ATR_PERIOD`), `indicators.py:86-90`, `signals.py` (squeeze sobre `candles_1m`) | El ATR% crece con el timeframe — un ATR mayor relativo al fee fijo reduce el drag en R sin cambiar nada de la lógica de señal |
| 5 | Modelar de verdad en backtest los dos filtros hoy inertes (order book imbalance, macro) — o sacarlos del pipeline en vivo hasta poder modelarlos | `order_flow.py`, `context.py`, `backtest_feed.py` | Backtest y bot en vivo son hoy estrategias distintas (2 de 10 gates nunca bloquean en simulación) |
| 6 | Ampliar el rango histórico del backtest — hoy solo hay cache de un mes (nov 2025) de un solo activo | `backtest_cache/`, `backtest.py --start/--end` | Un mes/un régimen no alcanza para afirmar edge; faltan tramos de tendencia, rango y alta/baja volatilidad |
| 7 | Persistir resultados de cada corrida (CSV + resumen), no solo imprimir en consola | `backtest_report.py`, `backtest.py` | Sin esto no hay manera de comparar corridas ni de auditar decisiones futuras |
| 8 | Ablation de los 10 gates: squeeze sola → +régimen → +tendencia 15m → +CVD → +spread → +OB → +macro, midiendo expectancy neta de fees en cada paso | nuevo modo de `backtest.py` o script aparte | Con 10 condiciones en AND, es probable que varios filtros solo recorten frecuencia sin mejorar expectancy — hoy no se sabe cuáles |

### P1 — Fixes de lógica de señal (medir con el harness de P0 antes de fijar parámetros)

| # | Mejora | Dónde | Por qué |
|---|---|---|---|
| 1 | Redefinir la dirección de la squeeze: derivarla del break real (vela que rompe la compresión), igual que ya se exige en régimen `BREAKOUT` — o, como mínimo, trackear si el nivel más cercano es swing high o swing low en vez de solo el signo de la distancia | `signals.py:26-61` (`update_squeeze`), `state.py` (agregar tipo de nivel) | Sección 3 |
| 2 | Resolver que el *breathing stop* rompe el presupuesto de riesgo de 0.5%: o re-sizear la posición al expandir el stop, o documentar que el riesgo deja de ser fijo (`0.5% × ATR_live/ATR_entry`) | `risk.py:145-165` | Verificado contra el código: el stop solo se expande, nunca se contrae, pero el tamaño de la posición ya quedó fijado con el ATR de entrada |
| 3 | Cambiar la divergencia de CVD de vela-a-vela a pivote-a-pivote (swing high vs swing high) | `order_flow.py:20-46` | La divergencia clásica se mide entre pivotes; vela-a-vela sobre 5 barras dispara con micro-ruido y puede vetar entradas válidas |
| 4 | Decidir el rol de `trend_5m`: usarlo como filtro/score o eliminarlo — hoy se calcula y no participa en `check_entry_signal` | `regime.py:135-139` (cálculo) vs. `signals.py` (sin uso) | Código muerto en un módulo de decisión es deuda que confunde a quien audite después |
| 5 | Degradar el filtro macro BTC-SPY a sesgo blando (no bloqueo duro) o sacarlo hasta poder backtestearlo; documentar explícitamente qué hace con SPY fuera de horario (BTC opera 24/7, SPY ~6.5h/día en días hábiles) | `context.py:31-129` | El filtro queda con datos stale la mayor parte del tiempo de trading de BTC; además, Pearson rodante sobre 20 muestras es ruidoso y el delay de 15min de yfinance no calza con una estrategia sub-15min |

### P2 — Instrumentación y ejecución

| # | Mejora | Dónde | Por qué |
|---|---|---|---|
| 1 | Registrar feature vector completo por trade (régimen, ATR, spread, distancia a nivel, tipo de nivel, dirección squeeze, trend_5m/15m, CVD, OB ratio, macro state, costo estimado, fill teórico vs real) | `execution.py` (payload de `on_trade_closed`), `backtest_report.py` | Sin esto no se puede auditar por qué un trade ganó o perdió, ni hacer el ablation de P0-8 con detalle |
| 2 | Modelar slippage explícito en el backtest, sobre todo en entradas de breakout (peor caso de fill por adverse selection) | `backtest_feed.py` (spread sintético ya existe; falta slippage) | Hoy solo se simula spread fijo (`BACKTEST_SYNTHETIC_SPREAD_PCT`), no slippage por tamaño/velocidad |
| 3 | Evaluar convertir los 10 gates binarios en un score continuo con umbral, en vez de AND estricto (propuesta de Codex) | `signals.py:check_entry_signal` | Permite distinguir una señal fuerte con una objeción débil de una señal mediocre que pasa de casualidad — **trade-off:** pierde interpretabilidad por gate individual; no implementar antes de tener el ablation de P0-8, que es lo que diría si vale la pena |

### P3 — Validación final, antes de considerar capital real

1. Walk-forward: ajustar parámetros solo in-sample, evaluar out-of-sample, sobre varios regímenes (tendencia alcista, bajista, rango, alta/baja volatilidad).
2. Paper trading con el código de producción real (no el backtest), comparando fills teóricos vs. reales durante un período sostenido.
3. Solo después de P0–P3 con resultados positivos y persistidos: considerar capital real, empezando con el tamaño mínimo posible.

---

## 5. Qué no tocar todavía

No optimizar los parámetros actuales (`SQUEEZE_COMPRESSION_ATR`,
`SQUEEZE_MIN_BARS`, `INITIAL_SL_ATR`, `TP1_RR`, etc., todos en `config.py`)
hasta que el harness de backtest sea fiel a producción (P0-2, P0-5, P0-7) y
exista el ablation (P0-8). Ajustar parámetros hoy es optimizar contra una
medición que no representa ni el costo real (fees subestimados en R) ni el
comportamiento real del bot en vivo (2 gates inertes en simulación).

---

## 6. Estado (2026-07-03)

Implementado el pivot de estructura de costos (P0-2 y P0-4 de la sección 4): señal
movida de 1m a 15m y entradas convertidas a maker post-only con timeout
(plan: `docs/superpowers/plans/2026-07-02-pivot-senal-15m-entradas-maker.md`).
Fee drag por round-trip esperado: de ~1.30R a ~0.17R (entrada maker + salidas taker,
ATR% p50 de 15m medido en 0.280%).

**P0-6 y P0-7 implementados** (2026-07-03, plan:
`docs/superpowers/plans/2026-07-03-backtest-persistencia-historico.md`, spec:
`docs/superpowers/specs/2026-07-03-backtest-persistencia-historico-design.md`):

- **P0-6:** `download_history.py` baja los dumps diarios oficiales de
  data.binance.vision a un cache compacto por día (`trade_cache.py`, ~6 MB/día
  vs ~450 MB del JSON viejo). Hay 91 días cacheados (2026-04-01 → 2026-07-01).
  Al migrar se descubrió que el cache viejo por REST **perdía 0.4-0.75% de los
  trades** (paginación `since = last_ts + 1` saltea trades del mismo ms en el
  borde de página); se verificó fila por fila que el viejo era subconjunto
  estricto del nuevo antes de borrarlo.
- **P0-7:** cada corrida de backtest persiste `meta.json` (parámetros + commit
  git) + `summary.json` (métricas + curva de equity) + `trades.csv` en
  `backtest_runs/<timestamp>_<label>/`, con flag `--label`, y regenera un
  comparador HTML autocontenido (`backtest_runs/index.html`,
  `backtest_report.py --rebuild-index` para reconstruirlo).
- Smoke de 3 meses (abr-jun 2026): corre en ~11 min, pico de RAM 2.2 GB
  (chunked por día, sin OOM). **Resultado: 0 trades en 91 días** — la señal
  actual (squeeze 15m + 10 gates en AND) no disparó ni una vez en todo el
  trimestre. Ese hallazgo refuerza la urgencia del ablation: hoy no se sabe
  qué gate (o combinación) está vetando todo.

Siguen pendientes: cost gate explícito (P0-3) y ablation de gates (P0-8),
ahora desbloqueado por la base de P0-6/P0-7.
