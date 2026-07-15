# Ciclo momentum multi-día — estudios de tasa base M1-M4 (spec)

Fecha: 2026-07-15
Estado: aprobada por Guille en sesión de brainstorming (decisiones firmadas
abajo). Insumo: `docs/revisiones/insights-momentum-multidia-btc.md` (evidencia
académica, espacio de diseño y preguntas abiertas que esta spec resuelve).
Antecedente directo: el ciclo de estudios intradía cerró con veredicto
negativo (`backtest_runs/estudios/veredicto-2026-07.md`) y su criterio de
salida pre-registrado habilitó este plan B.

## Propósito

Responder con números UNA pregunta: **¿el momentum multi-día en BTC
sobrevive a la era institucional (2024-2026)?** La literatura documenta el
efecto con muestras que terminan entre 2018 y 2020; el riesgo #1 del pivote
es que la institucionalización post-ETF (enero 2024) lo haya comprimido.
Por eso la ventana 2024→hoy es la verificación intocable, no un detalle.

Cero código del bot en este ciclo. Si algún estudio pasa, el diseño de la
señal (histéresis, gates, harness de ablación) es un ciclo aparte.

## Decisiones firmadas en el brainstorming (2026-07-15)

1. **Criterio de abandono (pre-registrado, sin salida):** si ninguna celda
   de M1 ni de M2 pasa el umbral en BTC, se acepta que la anomalía no
   sobrevivió a la institucionalización y **se congela la búsqueda de
   señal** — no se optimiza nada más, no hay re-testeo programado, fin de
   los pivotes. La infraestructura se conserva.
2. **ETH entra como robustez:** M1/M2 corren también sobre ETH diario,
   reportado por separado, nunca promediado con BTC. Solo BTC adopta/veta.
3. **Alcance:** M1-M4 en un solo ciclo, con M3 y M4 condicionales (solo
   corren si alguna celda de M1 o M2 pasa calibración Y verificación).
4. **Long/flat vs long/short:** no se pre-decide; los estudios miden ambas
   variantes como celdas separadas y la elección posterior sale de los
   números (mismo tratamiento que las dos colas de C1).
5. **Instrumento (spot vs perp):** lo decide M4 con el funding histórico
   real, no una opinión.
6. **Grillas fijas pre-registradas** (abajo); la combinación multi-horizonte
   (S3 del doc de insights) queda para el diseño de señal, si lo hay.
7. **Histéresis:** fuera de este ciclo — es parámetro de señal, no de tasa
   base.

## No-objetivos

- No se escribe código del bot ni se adopta ninguna señal en este ciclo.
- No ML, no scoring continuo, no optimización de lookbacks fuera de la
  grilla pre-registrada.
- No datos multi-venue (solo Binance; consistencia > largo de serie) ni
  cross-sectional multi-activo (queda como opción futura documentada).
- No paper trading.

## Datos

- **Velas diarias de Binance SPOT** (dumps mensuales de Binance Vision:
  `data/spot/monthly/klines/{SYMBOL}/1d/{SYMBOL}-1d-{YYYY-MM}.zip`),
  BTCUSDT y ETHUSDT, 2017-08 → hoy (~3.250 días por símbolo).
- **Por qué spot y no futuros (deliberado, documentado):** la serie spot
  arranca en 2017-08 (los futuros um en 2019-09) y estos estudios solo usan
  el precio de cierre diario — no hay ejecución simulada. NO es la trampa
  spot/futuros del ciclo anterior (aquella era sobre ticks de ejecución;
  ver `docs/mejoras-propuestas.md`). M4 usa además el funding de FUTUROS ya
  cacheado (`backtest_cache/{SYMBOL}_funding.json.gz`, 2020→hoy), que es el
  instrumento donde el funding existe.
- Descargador nuevo siguiendo el patrón mensual existente (reusa
  `_http_get`, `_iter_months`, `MonthNotAvailable` de `funding_history`,
  escritura atómica, cache por mes). Mes corriente sin dump publicado: el
  end de descarga/carga es EXCLUSIVO al mes corriente, igual que en el
  ciclo anterior.
- Paridad: cierre diario de una muestra de meses contra la API REST de spot
  (`api.binance.com/api/v3/klines`), criterio 100% de coincidencia en la
  muestra.

## Split temporal y candado

- **Calibración:** 2017-08-01 → 2023-12-31.
- **Verificación:** 2024-01-01 → hoy, **sellada**. Corte:
  `corte_ms = 1704067200000` (2024-01-01T00:00:00Z), pasado como `corte_ms`
  a `estudios.nucleo.ventana` (mismo candado `verificacion_habilitada` /
  `--verificacion` del ciclo anterior; no se reimplementa).
- El checkpoint humano se mantiene: calibración → revisión de código y
  congelamiento de scripts → **OK explícito de Guille** → verificación UNA
  vez. Si aparece un bug después, se arregla, se re-corre TODO y el
  veredicto lo declara ("re-corrida post-fix").

## Convenciones de cálculo (comunes a M1-M4)

- Retorno diario: `ret[t] = (close[t] - close[t-1]) / close[t-1]`.
- **Sin lookahead:** la señal calculada con el cierre del día t se aplica al
  retorno del día t+1.
- Serie de estrategia: `r_strat[t+1] = pos(t) × ret[t+1]`, con
  `pos ∈ {-1, 0, +1}` según la variante. Días flat: retorno 0.
- Sharpe anualizado: `media(r_strat) / desvío(r_strat) × √365` (cripto
  opera 365 días). Sin tasa libre de riesgo (se compara contra buy-and-hold
  bajo la misma convención, así que el término se cancela a efectos de la
  comparación).
- Max drawdown: sobre el producto acumulado de `(1 + r_strat)`.
- Buy-and-hold: la misma métrica sobre `ret` crudo de la misma ventana.
- Costos de transacción: NO se modelan en M1-M3 (pre-registrado: con 1-6
  cambios de estado/mes y fees de 0.02-0.05% por lado, el drag anual es
  décimas de % contra movimientos objetivo de decenas de %; fuente:
  sección 6 del doc de insights). M4 modela el único costo material a este
  horizonte: el funding.
- **Advertencia estadística pre-registrada:** los retornos forward a
  7/14/28 días se superponen (errores autocorrelacionados) → son SOLO
  descriptivos; la adopción se evalúa únicamente sobre la serie diaria de
  estrategia (sin superposición). Y el "n efectivo" de regímenes de BTC es
  ~4 ciclos, no ~3.250 días — los claims se redactan con esa humildad.

## Estudio M1 — tasa base TSMOM

- **Señal:** `sign(ret[t-k, t])` = signo del retorno acumulado de los
  últimos k días, k ∈ {7, 14, 28, 56, 90} (grilla fija).
- **Descriptivo (no decide):** retorno forward a 1/7/14/28 días firmado por
  la señal; mediana, media, hit rate; cada lado (señal +1 / señal −1) como
  celda separada. 5k × 4h × 2 lados × 2 símbolos = 80 celdas descriptivas.
- **Adopción (decide):** por lookback, DOS series de estrategia con
  rebalanceo diario al cierre UTC:
  - `long/short`: pos = señal.
  - `long/flat`: pos = max(señal, 0).
  → 5 × 2 = 10 celdas de estrategia por símbolo. Métricas: Sharpe, max
  drawdown, media y mediana de `r_strat`, vs buy-and-hold de la misma
  ventana.

## Estudio M2 — réplica de Detzel (P/MA)

- **Señal:** `P(t) / MA_n(close, t)` con n ∈ {10, 20, 50, 100} (grilla
  fija). Estrategia **long/flat** (long si ratio > 1, flat si ≤ 1 — la
  especificación del paper; sin banda muerta: la histéresis es del
  ciclo de señal).
- **Descriptivo:** contraste de quintiles del ratio (retorno forward 1/7/14
  días del quintil alto vs bajo, calculado solo dentro de calibración y
  solo dentro de verificación, sin mezclar ventanas).
- **Adopción:** 4 celdas de estrategia por símbolo, mismas métricas y
  umbral que M1.
- **Regla de fragilidad pre-registrada:** si M1 pasa y M2 falla (o
  viceversa) en celdas económicamente equivalentes, la discrepancia se
  reporta como evidencia de fragilidad de especificación — no se elige "la
  que dio mejor".

## Umbral de adopción M1/M2 (pre-registrado — verbatim en los reportes)

Una celda de estrategia de BTC **pasa** si, en calibración Y en
verificación evaluadas por separado (la verificación entera, sin
subventanas):

1. Sharpe de la estrategia > Sharpe de buy-and-hold, Y
2. max drawdown de la estrategia < max drawdown de buy-and-hold, Y
3. media de `r_strat` > 0, Y mediana de `r_strat` **sobre los días con
   posición** (pos ≠ 0) > 0. (La mediana se restringe a días en posición
   porque en las variantes long/flat los días flat valen 0 por construcción
   y arrastrarían la mediana a 0 aunque la estrategia funcione.)

ETH se reporta por separado como robustez; no adopta ni veta. Cada reporte
imprime el número total de celdas miradas. "Casi" = NO PASA.

La métrica es la de Detzel et al.: el trend-following en BTC se adopta si
**reduce las colas izquierdas sin regalar el retorno ajustado por riesgo**,
no si "le gana al bull".

## Estudio M3 — overlay de vol targeting (condicional)

Corre solo si alguna celda M1/M2 pasó. Sobre la mejor celda ganadora de BTC
(criterio de "mejor": mayor Sharpe de verificación):

- `exposición(t) = min(1, σ_target / σ_realizada_30d(t))`, con σ_realizada
  = desvío de los últimos 30 retornos diarios anualizado (√365), calculada
  al cierre de t y aplicada a t+1. σ_target ∈ {20%, 30%, 40%} anualizado
  (grilla fija). Tope de exposición 1× (sin apalancamiento).
- **Adopción del overlay:** en ambas ventanas, mejora max drawdown Y peor
  mes calendario vs la versión cruda, Y media de `r_strat` ≥ ½ de la cruda.
  Celdas: 3.

## Estudio M4 — costo de instrumento (condicional)

Corre solo si alguna celda M1/M2 pasó. Sobre la pata long de la mejor celda
ganadora, ventana 2020-01→hoy (cobertura del funding cacheado; se documenta
que la calibración pre-2020 queda fuera de M4 — es una comparación de
costos, no un test de señal):

- Serie A (perp): `r_strat` de la pata long menos el funding acumulado de
  los días en posición (suma de las 3 lecturas de 8h por día UTC, del cache
  de funding de futuros).
- Serie B (spot): `r_strat` de la pata long sin funding.
- Métrica: diferencia de retorno total y de Sharpe entre A y B, por
  ventana. **Sin umbral:** el número decide el instrumento de la pata long
  en el ciclo de diseño de señal, y se escribe en el veredicto.

## Criterio de salida del ciclo (pre-registrado)

- **Si al menos una celda de M1 o M2 pasa el umbral en BTC:** siguiente
  ciclo = brainstorming de diseño de señal (histéresis, gates, convivencia
  operativa con el bot actual, harness de ablación), llevando M3/M4 ya
  respondidos.
- **Si ninguna pasa:** se congela la búsqueda de señal, conservando la
  infraestructura. Sin excepciones, sin re-testeo programado (decisión
  firmada por Guille 2026-07-15, punto 1 de "Decisiones firmadas").

## Arquitectura

- `daily_history.py` (nuevo): descargador de velas diarias spot, patrón de
  `klines_history` (cache mensual `backtest_cache/{SYMBOL}_klines1d_{YYYY-MM}.json.gz`,
  filas `[open_time_ms, open, high, low, close, volume]`; imports
  compartidos desde `funding_history`).
- `estudios/nucleo.py`: se reusa tal cual (`ventana` con `corte_ms`
  explícito, `resumen`, `retorno_forward`); se agregan las funciones puras
  nuevas que faltan: serie de estrategia, Sharpe anualizado, max drawdown,
  peor mes. Cada una con test unitario propio.
- `estudios/estudio_momentum.py` (M1), `estudios/estudio_ma.py` (M2),
  `estudios/estudio_vol_overlay.py` (M3), `estudios/estudio_instrumento.py`
  (M4): mismo esqueleto CLI que los estudios C (`--modo`, `--verificacion`,
  `--symbols` donde aplique), reportes vía `escribir_reporte` con el
  pre-registro verbatim y el conteo de celdas.
- Sin pandas/numpy (3.250 filas por símbolo; `statistics` sobra). Sin
  dependencias nuevas.
- Cómputo trivial: todo corre en segundos en la VM; sin restricciones de
  memoria más allá del patrón mes a mes de descarga.

## Testing y proceso

- TDD estricto por task (failing-first con los valores pre-registrados en
  los tests; suite completa verde en cada commit).
- Las funciones de cálculo nuevas (señal TSMOM, P/MA, serie de estrategia,
  Sharpe, drawdown, peor mes, funding diario acumulado) se testean con
  fixtures sintéticos de respuesta conocida a mano.
- El candado de verificación NO se reimplementa: se hereda de
  `nucleo.ventana` (ya testeado en ambos sentidos).
- Flujo SDD igual al ciclo anterior: plan → subagentes Sonnet → revisión
  por task → calibración → congelamiento → checkpoint de Guille →
  verificación única → veredicto (`backtest_runs/estudios/veredicto-momentum-YYYY-MM.md`)
  con los umbrales copiados verbatim y conclusión PASA / NO PASA por celda.
- Los reportes de estudio se commitean (evidencia del ciclo), como en el
  ciclo anterior.
