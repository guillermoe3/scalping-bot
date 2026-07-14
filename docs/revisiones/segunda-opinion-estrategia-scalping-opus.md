# Segunda opinión — auditoría independiente de la estrategia de scalping BTC

Fecha: 2026-06-19
Documento auditado: `strategy-rationale.md` (mismo repo, fechado 2026-06-19)
Naturaleza: respuesta de auditoría independiente. Pensado para leerse **al lado**
del rationale original; las referencias a "sección N" remiten a las secciones de
ese documento.

---

## 0. Alcance y método (qué se verificó y qué no)

Límite epistémico, explícito porque condiciona el peso de cada hallazgo:

- **Todo lo que se afirma sobre el código está mediado por `strategy-rationale.md`.**
  No se abrió el repositorio. Cada afirmación sobre el comportamiento real de
  `signals.py`, `risk.py`, `regime.py`, `order_flow.py`, `context.py`, etc. es
  lectura del rationale, **no** verificación contra el código fuente. Donde esto
  importa para la conclusión, está marcado como *inferencia a partir del rationale*.
- El método de Bob Volman se contrastó contra **resúmenes y extractos secundarios**
  de sus libros (notas de Forex Factory, extractos públicos), **no** contra el
  texto primario completo (material con copyright). Etiquetado como
  *verificado contra fuentes secundarias*.
- El cálculo de fee drag (sección 4.1) es una **estimación** bajo supuestos
  explícitos; la derivación se incluye para que sea auditable.

Etiquetas de evidencia usadas en este documento:

| Etiqueta | Significado |
|---|---|
| **Verificado (fuente 2ª)** | Contrastado contra fuentes secundarias citadas en la sección 7 |
| **Deducción lógica** | Se sostiene por razonamiento, independiente de cualquier fuente externa |
| **Inferencia (rationale)** | Derivado de la mecánica que describe el rationale; no verificado contra el código |
| **Estimación** | Cálculo cuantitativo bajo supuestos declarados |
| **Observación factual** | Hecho del dominio (p. ej. horario de mercado de SPY) o del propio rationale |
| **A verificar** | No determinable desde el rationale; requiere mirar el código/datos |

---

## 1. Veredicto general

El rationale ya resuelve lo más difícil: es honesto en que **no hay evidencia de
edge neto de fees dentro del repo**. Eso es correcto y condiciona todo lo demás —
no se puede "mejorar la rentabilidad" de una estrategia cuya rentabilidad nunca
se midió.

- La **gestión de riesgo** (sección 8) y los **controles operacionales**
  (sección 9) son lo más sólido del proyecto y están bien fundamentados con
  independencia del edge. Buena gestión de riesgo no genera edge; controla la
  varianza y evita la ruina. Eso el rationale lo dice bien.
- El problema no es el riesgo: es que la **fuente de edge — la señal de entrada —
  es 100% heurística discrecional**, sin una sola corrida de backtest persistida
  que la respalde, y con **dos de los diez gates inertes en simulación** (order
  book imbalance y macro). En consecuencia, el backtest actual y el bot en vivo
  son, estrictamente, **estrategias distintas**.

**Conclusión:** antes de cualquier mejora de lógica, la mejora #1 es construir la
evidencia (sección 5, P0). Las mejoras de lógica de las secciones 5-P1/P2 son
defendibles, pero rearmar la señal de una estrategia no validada es reacomodar
sillas sin saber si el barco flota.

---

## 2. Hallazgo principal — dirección de la squeeze vs. el método de Volman

> Tipo de evidencia: **Verificado (fuente 2ª)** para el método de Volman;
> **Deducción lógica** para la crítica del signo.
> Responde directamente al punto abierto #1 del rationale (sección 2 y 11.1).

### 2.1 Qué hace Volman realmente

En el método de Volman, **la squeeze no trae una dirección asignada de antemano**:

- La compresión es el "resorte que acumula energía" antes de una expansión.
- La **dirección la revela el breakout en sí**, y ese breakout *es* el gatillo de
  entrada: se entra en la dirección en que rompe la compresión, **no antes**.
- La confluencia (25 EMA, número redondo, S&R rota en el mismo punto) sube las
  chances de follow-through, pero nunca se anticipa el lado. La regla central es
  evitar las rupturas sin buildup sólido.

### 2.2 Qué hace el código (según el rationale)

`squeeze_direction = LONG si last_price > key_level` (`signals.py:54-56`) **asigna
la dirección antes del break**, deduciéndola de qué lado del nivel más cercano
está el precio.

### 2.3 Diagnóstico

La pregunta del rationale — *"¿`precio > nivel → LONG` está invertido respecto a
Volman?"* — está **mal planteada en el fondo**. No es ni la versión "correcta" ni
la "invertida" de Volman: es un **modelo distinto** (continuación según el lado
donde está parado el precio) que el canon de Volman no plantea, porque el canon
**no asigna dirección desde la compresión** — espera el break.

- **Parche parcial existente:** en régimen `BREAKOUT` el código exige que la
  última vela confirme dirección (`signals.py:112-120`), lo que sí se parece a
  "esperar el break".
- **El agujero:** en `TIGHT_CHANNEL` y `TRADING_RANGE` **no** hay esa
  confirmación, así que ahí el bot **predice** dirección por posición-vs-nivel,
  sin un break que la valide. Ese es el hueco conceptual concreto.

### 2.4 Problema de lógica independiente del nombre (Deducción lógica)

`sign(last_price − key_level)` **no codifica la tesis del trade**, porque no
distingue si `key_level` es un swing **HIGH** (resistencia) o un swing **LOW**
(soporte):

- "Precio arriba del nivel más cercano" puede ser *aguantando sobre un soporte*
  (sesgo alcista) **o** *consolidando debajo de la próxima resistencia, que quedó
  más lejos que el soporte de abajo* (sesgo bajista).
- Mismo signo, tesis opuestas.

Para que la dirección signifique algo, hay que **trackear el tipo de nivel**, no
solo el signo de la distancia.

---

## 3. Resumen del fundamento por componente (coincidencias con el rationale)

Donde el rationale tiene razón y no hace falta repetir el detalle, queda
registrado para trazabilidad:

| Componente | Sección | Fundamento (acuerdo) |
|---|---|---|
| Filtro de régimen vía ATR | 3 | Heurística estándar y razonable; ATR como vara de "vela grande/chica" es práctica común |
| Tendencia multi-TF como bloqueo | 4 | "No operar contra el TF mayor": principio con alto consenso informal, sin prueba estadística acá |
| Filtro de spread | 7 | Control de calidad de ejecución; el filtro menos controversial del pipeline |
| Gestión de riesgo (ATR sizing/stops) | 8 | El bloque mejor fundamentado; independiza el riesgo monetario de la volatilidad del momento |
| Kill switch / reconciliación | 9 | Controles operacionales sólidos; limitan el daño, no generan edge |

---

## 4. Hallazgos que el rationale subestima o no marca

### 4.1 Fee drag + frecuencia — el problema central de cualquier scalper

> Tipo de evidencia: **Estimación** (supuestos abajo) + **Observación factual**
> (el rationale no fija el timeframe base).

El rationale no estima el peso de los fees en términos de **R**, y para scalping
es lo que mata.

**Supuestos:** taker 0.05%/lado (Binance Futures USDT-M, sin descuento BNB) →
~0.10% del notional ida y vuelta; sizing de 0.5% de riesgo por trade; SL a
1.5×ATR.

**Derivación (para que sea auditable):**

```
Sizing:   riesgo_$ = 0.005·B = N · (SL_dist / P)      con SL_dist = 1.5·ATR
  =>      N = 0.005·B·P / (1.5·ATR)

Fee RT:   F = 2 · 0.0005 · N = 0.001 · N
  =>      F = 0.001 · 0.005·B·P / (1.5·ATR)

En unidades de R (R = 0.005·B):
          F/R = 0.001·P / (1.5·ATR) = 0.000667 / ATR%      con ATR% = ATR/P
```

El parcial en TP1 **no** cambia esto: open(N) + close(0.5N) + close(0.5N) da el
mismo ~0.001·N que un cierre único; un loser frenado completo también. Es decir
~0.001·N por trade, gane o pierda.

| ATR% (timeframe base) | Fee por round-trip en R |
|---|---|
| 0.10% | **~0.67 R** |
| 0.20% | ~0.33 R |
| 0.30% | ~0.22 R |
| 0.50% | ~0.13 R |

**Lectura:** si el bot opera en vela de 1m con BTC calmo (ATR% ~0.1%), cada trade
arranca con **~0.67R en contra solo de fees**, antes del slippage. Con SL a −1R,
eso exige un win rate altísimo solo para empatar.

**Hueco del rationale:** el documento **nunca declara el timeframe base de
ejecución**. Aparecen 5m/15m como filtros de tendencia y "velas" para la squeeze,
pero el TF de las entradas no figura. Para un scalper es el dato más importante:
define si el drag es 0.13R o 0.67R. → **A verificar en `config.py`.**

**Frecuencia (acoplado):** diez condiciones en AND con cortocircuito recortan
muchísimo la frecuencia. **Selectividad alta + fee por trade alto** es la
combinación más difícil de volver rentable. Nadie midió señales/día que
sobreviven los diez gates ni el costo agregado de fees.

### 4.2 El breathing stop rompe el presupuesto de 0.5%

> Tipo de evidencia: **Inferencia (rationale)** — a partir de la mecánica descrita
> en `risk.py:145-165`; no verificada contra el código.

El sizing fija el notional al entrar usando `1.5·ATR_entry`. Si el ATR en vivo
crece ≥20% y el stop se ensancha a `1.5·ATR_live` (el breathing stop solo expande,
nunca contrae), pero el notional ya quedó fijo, entonces frenarte en el stop
ensanchado da:

```
pérdida_real ≈ 0.5% · (ATR_live / ATR_entry) ≈ 0.6%  en el umbral de 1.2×
```

y más si el ATR sigue creciendo. El rationale presenta 0.5% como riesgo por trade,
pero el breathing stop **quiebra ese invariante hacia arriba** en spikes de
volatilidad. No es fatal, pero el "0.5% fijo" no es fijo.

### 4.3 Filtro macro SPY — dos agujeros además de los que el rationale ya marca

> Tipo de evidencia: **Observación factual** (horario de SPY) + **Deducción
> lógica** (ruido de Pearson).

El rationale ya marca que el filtro no es apto para HFT y que no se backtestea.
Se agregan dos puntos no tratados:

1. **Horario de mercado.** SPY cotiza ~6.5h/día en días hábiles; BTC es 24/7.
   De noche, fines de semana y feriados US — **la mayoría del tiempo de trading
   de BTC** — no hay dato fresco de SPY, así que el gate queda stale o inerte
   buena parte de las horas. El rationale no aclara qué hace el filtro con SPY
   cerrado.
2. **Ruido estadístico.** Una correlación de Pearson rodante sobre 20 muestras es
   muy ruidosa; el umbral 0.8 va a entrar y salir por azar muestral. Sumado al
   delay de 15 min de yfinance contra una estrategia sub-15-min, probablemente
   mete más ruido que señal.

### 4.4 CVD vela-a-vela es demasiado fino

> Tipo de evidencia: **Deducción lógica** (observación metodológica).

El rationale nota que la divergencia se calcula vela-a-vela y no entre pivotes en
una ventana, pero no opina. La divergencia clásica se mide **pivote-a-pivote**
(swing high contra swing high). Vela-a-vela sobre 5 barras dispara con micro-ruido
y va a vetar entradas válidas con frecuencia.

### 4.5 Disciplina de barra cerrada / look-ahead

> Tipo de evidencia: **A verificar** — no determinable desde el rationale.

No aparece tratado y es el bug más común de backtest en scalping: si la squeeze
(3 velas) o la confirmación de régimen (3 velas) se evalúan sobre la **vela en
formación** en lugar de velas **cerradas**, hay look-ahead que no se reproduce en
vivo. Verificar que todo el pipeline corra solo sobre velas cerradas, en backtest
**y** en live. Si difieren, cualquier métrica de backtest queda inflada.

### 4.6 Un solo mes de un solo activo

> Tipo de evidencia: **Observación factual** (del propio rationale, sección 10).

El cache es de noviembre 2025: un régimen, un activo. Aun cuando se corra el
backtest, un mes no alcanza para afirmar edge. Se necesitan varios regímenes
(tendencia alcista, bajista, chop, alta/baja vol) y, idealmente, más de un período.

---

## 5. Mejoras, por prioridad

### P0 — Validación (lo único que importa antes de capital real)

1. **Harness que modele de verdad los filtros hoy inertes** (order book imbalance
   y macro) **o que los saque** del pipeline. Hoy el backtest y el bot live son
   estrategias distintas porque 2 de 10 gates nunca bloquean nada en simulación.
2. **Walk-forward** sobre varios meses y regímenes, con **métricas persistidas**:
   win rate, profit factor, expectancy en R **neta de fees y slippage modelado**,
   max drawdown, distribución de rachas.
3. **Ablation por gate:** medir la squeeze sola, luego squeeze+régimen, luego
   +cada filtro. Sin esto no se sabe si los filtros agregan edge o solo recortan
   frecuencia. Es plausible que varios estén destruyendo trades rentables.
4. **Slippage explícito en las entradas:** entrar en breakouts es el peor
   escenario de fill (adverse selection).

### P1 — Fixes de lógica (defendibles, pero medirlos con el harness primero)

1. **Dirección de la squeeze:** derivarla del **break real** (vela que rompe la
   compresión), no de `last_price` vs nivel. Si se mantiene lógica posición-vs-nivel,
   **trackear el tipo de nivel** (resistencia/soporte), no el signo de la distancia.
2. **Breathing stop:** o re-sizear al ensanchar, o documentar que el riesgo por
   trade es `0.5%·(ATR_live/ATR_entry)`, no 0.5% fijo.
3. **CVD pivote-a-pivote** en vez de vela-a-vela.
4. **`trend_5m`:** usarlo como filtro o borrarlo. Código muerto en un módulo de
   decisión es deuda que confunde al próximo que audite.
5. **Macro SPY:** degradar a sesgo blando o sacar hasta validar, y resolver
   explícitamente qué hace con SPY cerrado.

### P2 — Costo de ejecución

1. **Medir** frecuencia real de señal y fee drag agregado con datos.
2. **Evaluar entradas maker/post-only** para bajar de taker (0.05%) a maker —
   cambia toda la tabla de la sección 4.1 — asumiendo el riesgo de no-fill en un
   breakout rápido. En scalping, pasar de taker a maker suele ser la diferencia
   entre edge negativo y positivo.

---

## 6. Tabla resumen de hallazgos

| # | Hallazgo | Tipo de evidencia | Severidad | Ref. (rationale / código) |
|---|---|---|---|---|
| 1 | La squeeze asigna dirección pre-break; Volman no lo hace | Verificado (fuente 2ª) | Alta | `signals.py:54-56`; secc. 2 |
| 2 | `sign(price−level)` no distingue soporte de resistencia | Deducción lógica | Alta | `signals.py:54-56` |
| 3 | Fee drag en R altísimo si el TF base es chico | Estimación | Alta | secc. 8; `config.py` (a verificar) |
| 4 | Timeframe base de ejecución no declarado | Observación factual | Alta | `config.py` (a verificar) |
| 5 | 10 gates en AND → frecuencia no medida vs. fees | Deducción lógica | Alta | secc. 1, 10 |
| 6 | Breathing stop rompe el presupuesto de 0.5% | Inferencia (rationale) | Media | `risk.py:145-165` |
| 7 | Macro SPY inerte fuera del horario US (24/7 vs 6.5h) | Observación factual | Media | `context.py`; secc. 6 |
| 8 | Pearson 20-muestras + delay 15m: más ruido que señal | Deducción lógica | Media | `context.py:118-128` |
| 9 | CVD vela-a-vela demasiado ruidoso vs. pivote-a-pivote | Deducción lógica | Media | `order_flow.py:20-46`; secc. 5.1 |
| 10 | Disciplina de barra cerrada / look-ahead | A verificar | Alta si presente | pipeline completo |
| 11 | Backtest sobre un solo mes / un solo activo | Observación factual | Media | secc. 10 |
| 12 | Filtros inertes en backtest (OB imbalance + macro) | Observación factual | Alta | secc. 5.2, 6, 10 |
| 13 | `trend_5m` calculado pero sin uso | Observación factual | Baja | `regime.py:135-139` |

---

## 7. Fuentes

Método de Volman — contrastado contra resúmenes/extractos secundarios (no el texto
primario, por copyright):

- Forex Factory — "Understanding Price Action by Bob Volman (notes and examples)":
  https://www.forexfactory.com/thread/733640-understanding-price-action-by-bob-volman-notes-and
- Forex Factory — "Mastering Price Action Trading: Key Insights from Bob Volman":
  https://www.forexfactory.com/thread/1314402-mastering-price-action-trading-key-insights-from-bob

Conceptos estadísticos referenciados (de dominio público, sin fuente única):
clustering de volatilidad / modelos tipo GARCH (baja vol tiende a preceder
expansiones); fragilidad del Pearson rodante con N pequeño; adverse selection en
fills de breakout. El rationale ya los ancla correctamente.

---

## 8. Nota de alcance

Esto es análisis de **diseño y metodología del sistema**, no una recomendación de
operar con capital, y no proviene de un asesor financiero. La conclusión del propio
rationale — **sin evidencia de edge todavía** — es la que debería mandar sobre
cualquier decisión de capital real.
