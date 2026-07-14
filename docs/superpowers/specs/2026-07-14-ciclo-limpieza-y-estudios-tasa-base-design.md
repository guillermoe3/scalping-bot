# Ciclo 2026-07: limpieza del pipeline + tres estudios de tasa base

**Fecha:** 2026-07-14
**Estado:** aprobado por Guille (diseño validado en sesión; pendiente revisión
del texto de esta spec)
**Referencias:** `docs/revisiones/accionables-cuarta-opinion-fable5.md`
(accionables A1-A2, B2-B4, C1-C3, D1-D4),
`docs/revisiones/2026-07-14-informe-estado-completo-y-prompt-cuarta-opinion.md`
(evidencia consolidada), `backtest_runs/ablation-2026-07-14.md` (ablación
limpia), `backtest_runs/autopsia-2026-07-13/autopsia-trades.md` (tasas base),
`docs/revisiones/insights-momentum-multidia-btc.md` (plan B si el ciclo
falla), `signals.py`, `state.py`, `context.py`, `order_flow.py`,
`download_history.py`.

## Contexto y problema

La hipótesis de señal squeeze-sobre-niveles quedó rechazada dos veces con
medición limpia (ablación 2026-07-14: PF ~0.30 en toda la matriz; tasas base:
dirección post-squeeze ≈ moneda al aire y volatilidad forward MENOR que la
incondicional). La estructura de costos ya no es el problema (~0.17R por
round-trip maker). Hallazgos accesorios de la misma evidencia: `trend_1h` es
el único gate informativo; `cvd` veta trades buenos (PF 0.30→0.51 al
quitarlo); `regime_known` y `breakout_align` no vetan nada; `macro` y
`ob_imbalance` son imposibles de evaluar en backtest con la infraestructura
actual (el bot en vivo y el simulado no son la misma estrategia).

La cuarta opinión externa (2026-07-14) e ideas propias convergen en el mismo
plan de ciclo: retirar lo muerto, cerrar la brecha backtest≠live, y gastar el
presupuesto del ciclo en **estudios de tasa base baratos** (scripts sobre
datos, sin tocar código del bot) que descarten o promuevan hipótesis nuevas
en horas, no en días de implementación.

Decisiones de alcance tomadas por Guille en sesión (2026-07-14):

- Se retiran `macro` y `ob_imbalance` del bot en vivo (recuperables por git).
- El horizonte de la señal futura es libre (si la evidencia vive en 1h-4h,
  el bot operará ahí; no se defiende el timeframe de 15m).
- ETH-perp entra como segundo activo **de los estudios** (muestra doble,
  medido por separado); el bot sigue mono-activo BTC.

## Objetivo

1. **Limpieza:** el bot queda sin disparador de entrada (estado correcto: no
   operar sin señal validada), sin gates muertos ni gates ciegos, con un test
   invariante que impida reintroducir gates no evaluables en backtest.
2. **Datos:** funding rate (2020→hoy) y klines 15m multi-año, BTCUSDT y
   ETHUSDT, con el mismo patrón de cache compacto de P0-6.
3. **Tres estudios pre-registrados** (C2 sesión, C1 funding, C3 cascadas)
   con umbrales de adopción/descarte fijados en esta spec, ANTES de mirar
   los datos.
4. **Criterio de salida del ciclo** pre-registrado (sección final).

## No-objetivos

- No se implementa ninguna señal nueva en el bot en este ciclo. Si un
  estudio pasa su umbral, el diseño de la señal es un ciclo aparte
  (brainstorming → spec → ablación con el harness existente).
- No se usa ML ni scoring continuo (muestra insuficiente; ratificado por la
  cuarta opinión).
- No se re-optimiza nada de la señal squeeze retirada.
- ETH no entra al bot; solo a los estudios.
- Quedan explícitamente diferidos: filtro de calma (B1 — espera a que exista
  una señal candidata), estudio del ratio taker/CVD (B2 paso 2 — después de
  C1-C3), paper trading con disparador sintético (D3 — decisión aparte al
  cierre del ciclo), modelado de slippage (P2-2).
- El kill switch no cambia (ver B4 abajo).

## Componente 1 — Limpieza del pipeline (`signals.py`, `state.py`, `context.py`, `order_flow.py`, `main.py`)

Estado final del camino de decisión:

- **`check_entry_signal` queda sin disparador:** devuelve `None` siempre,
  con docstring explicando que no hay señal de entrada adoptada y que el
  próximo disparador debe llegar vía estudio aprobado + ablación. El
  framework de gates (nombres, `DISABLED_GATES`, contadores de veto,
  `reset_signal_stats`) se **conserva** — es la infraestructura del harness,
  no la señal.
- **`GATE_NAMES = ("spread", "trend_1h", "cvd")`** con
  `DISABLED_GATES = {"cvd"}` por default (evidencia: quitarlo mejoró PF
  0.30→0.51; se reintroduciría solo si el futuro estudio del ratio taker lo
  justifica). `regime_known`, `breakout_align`, `macro` y `ob_imbalance`
  salen de `GATE_NAMES`.
- **Se retira la tesis direccional del squeeze:** en `signals.py` se
  eliminan `ENTRY_VARIANT`, `_clear_broken` y la detección de ruptura; en
  `state.py` se eliminan `squeeze_direction`, `squeeze_reference_level`,
  `squeeze_price_above_level`, `squeeze_broken`, `squeeze_broken_direction`,
  `squeeze_broken_level`, `squeeze_broken_ttl`. `update_squeeze` conserva su
  condición de armado actual sin cambios (compresión + proximidad a nivel →
  `squeeze_bar_count`, `in_squeeze`, con `_nearest_key_level` intacto); solo
  pierde la asignación de tesis direccional. Queda documentado como candidato
  a filtro de calma futuro (la evidencia dice: compresión → más calma).
- **Se retira `MacroFilter`** (`context.py` queda vacío o se borra el
  módulo, junto con su wiring en `main.py` y la dependencia de yfinance en
  `requirements.txt` si nada más la usa).
- **Se retira el imbalance del order book:** `get_book_imbalance` y la
  recolección de snapshots de profundidad. Cuidado del ejecutor: el best
  bid/ask del book ticker se CONSERVA (lo usan el filtro de spread y las
  entradas maker); solo muere la señal de imbalance por profundidad.
- **`detect_cvd_divergence` se conserva** (lo consume el gate `cvd`,
  desactivado por default pero medible en ablación).
- **La maquinaria de régimen se conserva** (la EMA adaptativa depende de
  ella); solo muere su rol como gate.
- **Test invariante (D4):** `signals.py` declara
  `BACKTEST_EVALUABLE_GATES` (tupla de gates cuyos insumos el motor de
  backtest actualiza realmente) y un test permanente exige
  `set(GATE_NAMES) <= set(BACKTEST_EVALUABLE_GATES)`. Reintroducir un gate
  ciego rompe la suite.
- **B4 (kill switch, verificado en sesión):** la afirmación de la cuarta
  opinión es cierta (el kill switch mira solo PnL realizado) pero es
  inofensiva con el invariante de posición única: se evalúa al cierre del
  trade (cuando no hay posición abierta) y las entradas ya están bloqueadas
  mientras exista una posición o una pendiente. Acción: comentario en
  `safety.after_trade_closed` documentando que la corrección por PnL no
  realizado es obligatoria si algún día hay multi-posición o cierre forzado
  por kill switch. Sin cambio de lógica.

**Criterio de aceptación del componente:** suite completa verde; un backtest
de humo sobre abr-jun 2026 termina con 0 señales y 0 trades; `grep` sin
referencias residuales a los símbolos eliminados fuera de git history.

## Componente 2 — Datos: funding + klines 15m multi-año (`download_history.py`, `trade_cache.py` o módulo nuevo)

- **Funding rate:** dumps mensuales oficiales de
  `data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/`
  (verificado 2026-07-14: BTCUSDT cubre 2020-01 → 2026-06). Bajar BTCUSDT y
  ETHUSDT completos. Volumen trivial (3 registros/día): un CSV compacto por
  símbolo en `backtest_cache/` es suficiente.
- **Klines 15m:** dumps mensuales de
  `data/futures/um/monthly/klines/{SYMBOL}/15m/`, BTCUSDT y ETHUSDT,
   2020-01 → presente, a cache compacto por mes (mismo patrón que el cache
  de días de P0-6).
- **Verificación de paridad (mismo control que P0-6):** para una muestra de
  ≥3 meses, comparar conteos y suma de volumen contra la API REST; documentar
  el resultado en el reporte del componente.
- **Reglas anti-OOM (obligatorias, ver incidente 2026-07-13):** descarga y
  parseo mes a mes, nunca el histórico entero en RAM; un solo proceso pesado
  a la vez; si se lanza como servicio, con `MemoryMax`.

## Componente 3 — Librería mínima de estudios (`estudios/` nuevo)

Módulo compartido pequeño (con tests unitarios TDD) que da a los tres
estudios el mismo esqueleto y hace difícil violar el pre-registro por
accidente (D1 de la cuarta opinión, versión liviana):

- Carga de klines/funding desde el cache, mes a mes.
- Retornos forward firmados a horizontes dados (en % del precio de cierre
  del evento), sin lookahead (el evento en la barra t usa solo datos ≤ t).
- Partición temporal `calibracion` / `verificacion` por fecha fija, con la
  verificación inaccesible salvo flag explícito `--verificacion` (el flujo
  es: iterar mirando solo calibración; una única corrida final con el flag).
- Salida estándar por corrida: JSON de métricas + reporte `.md` en
  `backtest_runs/estudios/<fecha>_<estudio>/`, que SIEMPRE imprime el bloque
  de pre-registro (umbrales, horizontes, n mínimo) y el **número total de
  celdas miradas** (definiciones de evento × horizontes × métricas) para
  contextualizar multiplicidad.

Convención de costos para umbrales: round-trip maker+taker = 0.02% + 0.05% =
**0.07% del notional**. "Neto de costos" en esta spec = magnitud > 0.07%;
"holgado" = > 2× (0.14%).

## Componente 4 — Estudio C2: sesión/hora del día (el más barato, corre primero)

- **Datos:** klines 15m BTCUSDT y ETHUSDT (post Componente 2; si el
  ejecutor quiere un dry-run temprano puede correrlo sobre los 3 meses
  actuales, pero el resultado que cuenta es el multi-año).
- **Evento:** cada vela de 15m, bucketed por hora UTC (24 buckets) y,
  como corte secundario, día hábil vs fin de semana (48 celdas por métrica).
- **Métricas por bucket:** retorno medio y mediano de la vela siguiente,
  |retorno| medio (proxy de volatilidad), volumen medio.
- **Split:** calibración 2020-01→2024-12, verificación 2025-01→presente.
- **Rol pre-registrado: insumo, NO señal.** No hay umbral de adopción; el
  producto es (a) contexto horario para C1/C3 (¿sus efectos se concentran en
  alguna sesión?), (b) candidato a filtro de "no operar" para señales
  futuras. Cualquier patrón direccional que aparezca genera hipótesis nueva,
  no adopción.
- **Extensión opcional (no bloqueante):** separar días con release macro US
  (CPI/FOMC/NFP) si se consigue un calendario histórico confiable sin
  dependencia frágil; si no, se documenta como límite.

## Componente 5 — Estudio C1: funding extremo como condicionante direccional (la apuesta principal)

- **Datos:** funding BTCUSDT y ETHUSDT 2020→hoy + klines 15m (Componente 2).
- **Evento (pre-registrado):** en cada timestamp de funding (cada 8h), el
  funding entra en cola extrema si es > percentil 90 o < percentil 10 de la
  ventana rodante de 30 días (90 observaciones). Para evitar contar racimos
  como eventos independientes, el evento es el **cruce de entrada** a la
  cola (primera observación extrema tras ≥1 no-extrema).
- **Tesis:** funding alto (longs pagan caro) → forward negativo; funding
  bajo → forward positivo. Retorno forward FIRMADO por la tesis.
- **Horizontes:** 8h, 24h, 72h desde el cierre de la vela 15m del evento.
- **Métricas:** mediana firmada, media firmada, hit rate direccional.
- **n mínimo (pre-registrado):** 150 eventos por cola y por símbolo en
  calibración; si no se alcanza, el estudio solo puede concluir "descartar o
  extender datos".
- **Split:** calibración 2020-01→2024-12, verificación 2025-01→presente
  (la era institucional queda entera del lado intocable, a propósito).
- **Umbral de adopción (pre-registrado):** para BTC, en AL MENOS un
  horizonte: mediana firmada ≥ 0.14% (2× costos) Y media del mismo signo Y
  hit rate > 50% — en calibración Y sostenido en verificación (mismo signo,
  magnitud ≥ la mitad de la de calibración). ETH se reporta por separado
  como robustez; no adopta ni veta por sí solo.
- **Celdas totales:** 2 colas × 3 horizontes × 2 símbolos = 12 por métrica
  (se imprime en el reporte).

## Componente 6 — Estudio C3: reversión post-movimiento extremo (proxy de cascada)

- **Datos:** cache tick de 91 días de BTCUSDT (abr-jun 2026). ETH no tiene
  ticks locales: queda fuera de C3 y se documenta.
- **Evento (pre-registrado):** vela 15m cuyo retorno tiene |z| > 3 contra el
  desvío estándar de los retornos 15m de las 24h previas (96 velas), Y cuyo
  flujo taker es unidireccional: |buy − sell| / (buy + sell) ≥ 0.6 en la
  vela (calculado de los ticks).
- **Tesis:** sobre-extensión mecánica → reversión parcial. Forward firmado
  CONTRA el movimiento, a 1h, 4h, 8h.
- **Métricas:** mediana, media, hit rate.
- **Split:** calibración 2026-04-01→2026-05-31, verificación
  2026-06-01→2026-07-01.
- **Límite pre-registrado (clave):** n esperado 30-60. Con n < 50 en total,
  el estudio SOLO puede concluir "descartar" o "extender datos" — nunca
  "adoptar". Con n ≥ 50 y señal fuerte (mediana ≥ 0.14% firmada, media del
  mismo signo en calibración y verificación), la conclusión máxima es
  "extender datos y re-testear", porque un split de 91 días no soporta más.

## Testing

- Componente 1: TDD estricto; tests failing-first para el estado final de
  `check_entry_signal` (siempre `None`), la ausencia de campos eliminados,
  `DISABLED_GATES` default y el invariante D4. La suite existente que
  referencie símbolos eliminados se poda en el mismo commit que los elimina.
- Componente 2: tests del parser de funding (formato real de los CSV de
  Binance Vision) y del cache; verificación de paridad documentada.
- Componente 3: tests unitarios de forward returns (sin lookahead, bordes de
  serie), percentil rodante, particiones por fecha y del candado
  `--verificacion`.
- Componentes 4-6: los estudios son scripts deterministas sobre la librería
  testeada; su "test" es el reporte persistido con el bloque de pre-registro
  impreso. Ninguna corrida de verificación antes de congelar el código del
  estudio (revisión del script primero, corrida después).

## Ejecución

Orden: Componente 1 → 2 → 3 → C2 → C1 → C3. Ejecución con subagentes
(preferencia registrada: diseño/supervisión acá, implementación delegada),
worktree aislado, review por task como en ciclos anteriores.

## Criterio de salida del ciclo (pre-registrado)

- **Si C1 pasa su umbral** (o C3 termina en "extender y re-testear" con
  señal fuerte): siguiente ciclo = brainstorming corto de diseño de señal
  (disparador + gates) sobre la hipótesis ganadora, y de ahí al harness de
  ablación de siempre. C2 aporta contexto, no dispara ciclos por sí solo.
- **Si los tres fallan:** NO se prueban más combinaciones intradía. Se abre
  la decisión del plan B ya documentado
  (`docs/revisiones/insights-momentum-multidia-btc.md`: momentum multi-día,
  con sus propios estudios M1-M4 pre-esbozados) o se congela la búsqueda de
  señal conservando la infraestructura. Esa decisión es de Guille, con ambos
  caminos por escrito.
