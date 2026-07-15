# Handoff: ejecutar Tasks 10 y 11 del ciclo desde otra cuenta/máquina

Fecha: 2026-07-15
Rama: `worktree-ciclo-estudios` (pusheada a origin hasta `67aef78`)
Plan maestro: `docs/superpowers/plans/2026-07-14-ciclo-limpieza-y-estudios-tasa-base.md`
Spec (los umbrales pre-registrados son ley): `docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md`

Propósito: continuar el ciclo en otra sesión de Claude (otra cuenta, otra
computadora) para repartir el gasto de tokens, y volver a la sesión original
solo con los commits pusheados.

---

## 1. Estado del ciclo al momento del handoff (9/11 tasks aprobadas)

| Task | Estado | Commits | Notas |
|---|---|---|---|
| 1. signals/state sin disparador + invariante D4 | ✅ aprobada | `..cd7b194` | bot sin trigger; gates (spread, trend_1h, cvd) con cvd off |
| 2. Retirar macro BTC-SPY | ✅ aprobada | `..75363dd` | context.py + yfinance eliminados |
| 3. Retirar OB imbalance | ✅ aprobada | `..66aa037` | top-of-book conservado (spread + entradas maker) |
| 4. B4 + README + smoke 3 meses | ✅ aprobada | `..753628f` | smoke abr-jun: 0 trades, 0 señales, cvd off — Componente 1 cerrado |
| 5. funding_history.py | ✅ aprobada | `..34e2ebb` | funding 2020→2026-06 BTC+ETH; paridad 100% s/ dumps publicados |
| 6. klines_history.py | ✅ aprobada | `..7c94bcb` | HALLAZGO: tick cache viejo es SPOT; klines son FUTURES um. Columnas validadas 500/500 vs fapi REST |
| 7. Librería estudios | ✅ aprobada (1 fix) | `..9d03f58` | candado de verificación probado; resumen([]) arreglado |
| 8. Estudio C2 sesión | ✅ aprobada | `..fe73638` | calibración corrida y versionada (96 celdas) |
| 9. Estudio C1 funding | ✅ aprobada (2 fixes CRÍTICOS) | `..67aef78` | ver abajo — leer antes de tocar C3 |
| 10. Estudio C3 cascadas | ⬜ PENDIENTE | — | este handoff |
| 11. Checkpoint + verificación + veredicto | ⬜ PENDIENTE | — | requiere OK humano de Guille ANTES de la verificación |

**Lección de la Task 9 (obligatoria para quien haga la 10):** la revisión
encontró dos bugs críticos que contaminaban la calibración: (a) los
timestamps de funding traen jitter de milisegundos y una búsqueda por
igualdad exacta descartaba 34-48% de los eventos en silencio (fix: floor a
la grilla de 900.000 ms antes de anclar); (b) la definición de evento se
había desviado del texto pre-registrado. Moraleja para C3: anclar SIEMPRE
por floor a la grilla si se cruzan timestamps de fuentes distintas, y
implementar las definiciones pre-registradas al pie de la letra, sin
"mejoras" razonables.

**Resoluciones del controlador ya vigentes (amendments al plan):**
- El mes corriente (2026-07) NO está cacheado (Binance no publicó el dump):
  todo `cargar_klines` termina en end exclusivo `"2026-07"`.
- C3 usa el flujo taker de las klines de FUTUROS (`row[6]` = taker_buy_base,
  validado 500/500 contra fapi REST). NO usar el cache de ticks
  (`BTCUSDT_aggtrades_*`): es de SPOT, mercado distinto, y además en la
  máquina nueva ni siquiera estará descargado.
- `.gitignore` ya tiene la negación `!backtest_runs/estudios/` — los
  reportes de estudio SE COMMITEAN (son la evidencia del ciclo).

---

## 2. Setup en la máquina nueva (una vez)

```bash
git clone https://github.com/guillermoe3/scalping-bot.git
cd scalping-bot
git checkout worktree-ciclo-estudios
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q        # esperado: 279 passed
# datos para C3 (klines BTC; ~25 MB, minutos, gratis):
.venv/bin/python klines_history.py --symbol BTCUSDT --start 2020-01 --end 2026-07
```

Para la Task 11 (verificación de C2 y C1) hace falta también:

```bash
.venv/bin/python klines_history.py --symbol ETHUSDT --start 2020-01 --end 2026-07
.venv/bin/python funding_history.py --symbol BTCUSDT --start 2020-01 --end 2026-08
.venv/bin/python funding_history.py --symbol ETHUSDT --start 2020-01 --end 2026-08
```

Requisitos: Python 3.12, git con acceso de push al repo. No hace falta
`.env` ni claves de exchange (los estudios no tocan el bot).

---

## 3. Task 10 — prompt para pegar en la sesión de Claude de la otra cuenta

> Trabajá en el repo scalping-bot, rama `worktree-ciclo-estudios` (NO en
> master). Ejecutá la **Task 10** del plan
> `docs/superpowers/plans/2026-07-14-ciclo-limpieza-y-estudios-tasa-base.md`
> (estudio C3 cascadas: `estudios/estudio_cascadas.py` + test), leyendo
> antes la spec
> `docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md`
> y la sección 1 del handoff
> `docs/superpowers/plans/2026-07-15-handoff-tasks-10-11-otra-cuenta.md`
> (lección de la Task 9 y resoluciones vigentes).
>
> Reglas duras, sin excepción:
> 1. TDD estricto: el test del brief primero, mostrar el fallo (RED), recién
>    después implementar (GREEN). Suite completa verde antes de commitear
>    (`.venv/bin/python -m pytest -q`, base actual: 279 passed).
> 2. Solo `--modo calibracion`. JAMÁS ejecutar `--modo verificacion` ni
>    pasar `--verificacion` — la ventana de verificación está sellada hasta
>    el checkpoint humano de la Task 11.
> 3. Los valores pre-registrados del plan no se ajustan por ningún motivo:
>    |z| > 3 contra el desvío de los retornos de las 96 velas previas;
>    flujo unidireccional |2·taker_buy − vol| / vol ≥ 0.6; horizontes 1h=4,
>    4h=16, 8h=32 barras; retorno forward firmado CONTRA la dirección del
>    movimiento; corte calibración/verificación de C3 = 1780272000000
>    (2026-06-01T00:00:00Z), pasado como corte_ms a ventana(); regla de
>    n<50 impresa en el pre-registro del reporte.
> 4. Datos: `cargar_klines("BTCUSDT", "2026-03", "2026-07")`; el mes 2026-03
>    solo alimenta la ventana de sigma — los eventos se cuentan desde
>    2026-04-01. ETH queda fuera de C3 (documentarlo en el reporte, como
>    dice la spec).
> 5. El directorio de reporte de calibración generado bajo
>    `backtest_runs/estudios/` se commitea junto al código. Sin
>    editorializar sobre si los resultados "pintan bien": solo números y
>    pre-registro.
> 6. Commit: mensaje imperativo corto en inglés
>    ("Add cascade-reversion base-rate study (C3) and its calibration
>    report"), y push a `worktree-ciclo-estudios`.
>
> Esperable: pocos eventos (decenas) — eso NO es un bug; la regla de n<50
> existe justamente para eso. Si la corrida crashea o da 0 eventos, parar y
> reportar el error en vez de ajustar umbrales.

## 4. Revisión de la Task 10 (en la otra cuenta, antes del checkpoint)

Después del commit de la Task 10, en una conversación NUEVA de esa misma
cuenta (contexto fresco, sin el sesgo del implementador):

> Revisá el último commit de la rama `worktree-ciclo-estudios` del repo
> scalping-bot (diff: `git show <sha>`). Es el estudio C3 del plan
> `docs/superpowers/plans/2026-07-14-ciclo-limpieza-y-estudios-tasa-base.md`
> (Task 10) — un estudio de tasa base cuyos números alimentan una decisión
> pre-registrada, así que la correctitud de la detección de eventos es lo
> único que importa. Verificá especialmente: (1) el z-score usa SOLO las 96
> velas previas (sin lookahead; stdev de retornos, no de precios); (2) el
> flujo unidireccional se calcula |2·taker_buy − vol|/vol ≥ 0.6 con
> taker_buy = columna 6 de las filas del cache; (3) el retorno forward va
> firmado CONTRA la dirección del movimiento; (4) los eventos se cuentan
> solo desde 2026-04-01 aunque los datos carguen desde 2026-03; (5) el
> corte de C3 es 1780272000000 y se pasó como corte_ms (no usa el corte
> global de 2025); (6) no existe NINGÚN artefacto de modo verificación; (7)
> el pre-registro del reporte trae la regla de n<50 y no hay
> editorialización. Reportá hallazgos por severidad (Critical/Important/
> Minor) con archivo:línea. Si hay Critical o Important, arreglalos con
> TDD, re-corré la calibración, eliminá de git el reporte contaminado en el
> mismo commit del fix (como se hizo en la Task 9) y pusheá.

## 5. Task 11 — SOLO después del OK de Guille

La Task 11 tiene un candado humano. Orden estricto:

1. **Checkpoint (Guille):** con los tres reportes de calibración commiteados
   (C2 sesión, C1 funding, C3 cascadas — en `backtest_runs/estudios/`),
   Guille revisa y da el OK explícito para abrir la ventana de verificación.
   Sin ese OK, no se corre nada más.
2. **Corridas de verificación (una sola vez, scripts congelados, cero
   tokens):**

```bash
.venv/bin/python -m estudios.estudio_sesion   --modo verificacion --verificacion --symbols BTCUSDT,ETHUSDT
.venv/bin/python -m estudios.estudio_funding  --modo verificacion --verificacion --symbols BTCUSDT,ETHUSDT
.venv/bin/python -m estudios.estudio_cascadas --modo verificacion --verificacion
```

   Si tras estas corridas aparece un bug en un script: se arregla, se
   re-corre TODO (calibración y verificación) y el veredicto lo declara
   explícitamente ("re-corrida post-fix").

3. **Veredicto** (`backtest_runs/estudios/veredicto-2026-07.md`, se
   commitea): tabla por estudio (calibración vs verificación, todas las
   celdas), evaluación contra el umbral pre-registrado de la spec COPIADO
   verbatim, y una de tres conclusiones por estudio: PASA / NO PASA /
   N INSUFICIENTE. El umbral de C1 (el único con adopción):
   *para BTC, en al menos un horizonte: mediana firmada ≥ 0.14% Y media del
   mismo signo Y hit rate > 50%, en calibración Y sostenido en verificación
   (mismo signo, magnitud ≥ ½ de la de calibración). ETH solo robustez.*
   NO decidir el rumbo del proyecto en el veredicto — solo dejar planteada
   la bifurcación de la spec (si C1 pasa → diseño de señal; si todo falla →
   Guille elige entre plan B momentum multi-día o congelar).
4. **Actualizar `docs/mejoras-propuestas.md`** con la sección de estado del
   ciclo (texto base en la Task 11 del plan), completando el resultado real.
   Incluir una línea documentando el hallazgo de la Task 6: el replay del
   backtest usa ticks de SPOT mientras el bot opera FUTUROS — ablaciones
   futuras deberían bajar aggTrades de futuros (data.binance.vision los
   publica).
5. Commit + push de todo.

## 6. Al volver a la sesión original

Decirle a la sesión original: "Tasks 10 y 11 pusheadas" (o hasta dónde se
llegó). Esa sesión hará fetch, verificará el estado contra este documento y
cerrará el ciclo: revisión final de toda la rama (puede correrse también en
la otra cuenta con `/code-review` sobre la rama completa — es el gasto
grande del modelo caro; traer los hallazgos de vuelta) y decisión de merge
a master con Guille.

Hallazgos menores acumulados para esa revisión final (del ledger de la
sesión original): help-string en español en `--enable-gate` y sin test e2e
del flag (T1); test de depth con blast radius angosto (T3); imports muertos
en funding_history/tests y `IndexError` posible en fila corta de
`parse_funding_csv` (T5); loop de retry duplicado entre downloaders e
`import pytest` sin uso (T6); narrativa base-vs-quote volume en el reporte
de T8 y `--symbols` sin strip (T8).
