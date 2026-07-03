# Persistencia de corridas + ampliación del histórico del backtest (P0-7 y P0-6)

**Fecha:** 2026-07-03
**Estado:** aprobado por Guille (diseño validado en sesión)
**Referencias:** `docs/mejoras-propuestas.md` §4 (P0-6, P0-7), memoria del fix de OOM
(day-chunking, commit 595447d), `backtest.py`, `backtest_feed.py`, `backtest_report.py`.

## Contexto y problema

El backtest actual imprime el resumen en consola y sobreescribe un único
`backtest_trades.csv` por corrida: no hay forma de comparar corridas ni de auditar
decisiones (P0-7). El histórico disponible es ~1 mes de BTC/USDT y los trades se
bajan por REST paginando de a 1.000 — ampliar a meses por esa vía es inviable en
tiempo y frágil ante rate limits (P0-6). Un día de trades en el JSON actual pesa
~450 MB. Ambas cosas bloquean el ablation de gates (P0-8).

## Objetivo

1. **P0-6:** poder backtestear 3 meses contiguos de BTC/USDT (recomendado:
   2026-04-01 → 2026-07-01), descargados de forma rápida y reanudable.
2. **P0-7:** cada corrida queda persistida (parámetros + métricas + trades) y un
   HTML autocontenido permite comparar todas las corridas visualmente.

**Restricción de memoria (no negociable):** nunca cargar más de un día de trades
en RAM (lección del OOM previo). El generador del HTML solo lee resúmenes
(kilobytes), jamás los CSV de trades.

## No-objetivos

- No se toca la lógica de señales, ejecución ni el cost gate (P0-3 es otro trabajo).
- No se agregan otros activos ni timeframes; solo BTC/USDT spot como hoy.
- No hay servidor web ni base de datos; todo es archivos planos + HTML estático.
- El ablation en sí (P0-8) queda para después; esto solo construye su base.

## Componente 1 — `download_history.py` (nuevo)

CLI: `python download_history.py --start YYYY-MM-DD --end YYYY-MM-DD` (fin exclusivo).

Por cada día del rango, **de a un día por vez** (descargar → convertir → liberar):

1. Si el archivo compacto del día ya existe en `backtest_cache/`, saltear
   (reanudable tras un corte).
2. Descargar el ZIP diario oficial de aggTrades spot:
   `https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-YYYY-MM-DD.zip`.
   Sin API key ni rate limits.
3. Parsear el CSV interno y convertir a formato compacto (ver abajo).
4. Escribir atómico (`.tmp` + `os.replace`), borrar el ZIP.

Detalles del parser que el implementador debe manejar:

- **Timestamps:** los dumps spot usan microsegundos desde 2025-01-01 (antes,
  milisegundos). Detectar por magnitud y normalizar a **milisegundos**.
- **Header:** algunos archivos traen fila de encabezado y otros no; saltear la
  primera fila si no es numérica.
- Columnas relevantes del CSV: `price`, `quantity`, `timestamp`, `isBuyerMaker`
  (isBuyerMaker=True ⇒ agresor vendedor ⇒ `is_sell=True`).

Errores: reintentos con backoff ante fallas de red; si el día no existe en
Binance (HTTP 404), informar y continuar con el siguiente; resumen final con
días OK / saltados / fallidos y exit code ≠ 0 si hubo fallidos.

Las velas 1m **no cambian**: siguen por el camino REST + cache actual (livianas,
~130 requests para 90 días, ya probado).

## Formato compacto de trades (nuevo cache)

Un archivo por día: `backtest_cache/BTCUSDT_aggtrades_YYYY-MM-DD.json.gz`.
Contenido: lista de filas `[ts_ms, price, qty, is_sell]` ordenadas por timestamp
(sin dicts por fila: menos disco y menos RAM). Tamaño esperado: ~40-80 MB/día
(vs. ~450 MB del JSON actual).

Nota de fidelidad: ccxt `fetch_trades` sobre Binance ya usa el endpoint de
aggTrades, así que el contenido es el mismo que el cache viejo; el CVD total es
idéntico. El implementador debe verificarlo con el test de equivalencia (abajo).

## Componente 2 — lector en `backtest_feed.py`

`fetch_trades(...)` (o su reemplazo) resuelve así para cada día:

1. Existe `BTCUSDT_aggtrades_YYYY-MM-DD.json.gz` → usarlo.
2. Existe el JSON viejo del día exacto → usarlo (compatibilidad temporal).
3. Nada → fallback al REST actual **con warning** sugiriendo
   `download_history.py`, salvo rangos largos (>2 días sin cache), donde se corta
   con error listando los días faltantes y el comando exacto para bajarlos.

El replay sigue siendo por chunks de un día (`_day_chunks` intacto). La
conversión de filas compactas a eventos se hace al construir el timeline del día,
como hoy.

## Componente 3 — persistencia por corrida

Al terminar cada corrida, `backtest.py` crea
`backtest_runs/<YYYY-MM-DD_HH-MM-SS>[_<label>]/` con:

- `meta.json`: start, end, balance, spread_pct, label (nuevo flag `--label`,
  opcional, saneado para nombre de carpeta), commit de git (`git rev-parse
  --short HEAD` + flag dirty), timestamp de la corrida, duración, versión del
  formato.
- `summary.json`: las métricas actuales de `compute_summary` + curva de equity
  reducida a ≤500 puntos. Cada punto es el equity acumulado (suma de
  `total_trade_net`) después de un trade cerrado; el eje x es el índice del
  trade. Si hay >500 trades, downsample uniforme conservando siempre el primer
  y el último punto; guardar también el equity final exacto sin downsample.
- `trades.csv`: mismo formato/campos que hoy.

`--out` se mantiene por compatibilidad (sigue escribiendo el CSV suelto); el
resumen se sigue imprimiendo en consola. La corrida imprime al final la ruta de
la carpeta creada y de `index.html`.

## Componente 4 — comparador `backtest_runs/index.html`

Se regenera al final de cada corrida (y con `python backtest_report.py
--rebuild-index` para regenerarlo a mano). Entrada: **solo** los `meta.json` +
`summary.json` de cada subcarpeta de `backtest_runs/` (kilobytes cada uno;
corridas con archivos corruptos/incompletos se listan con aviso, no rompen la
página).

Salida: HTML autocontenido (CSS/JS inline, sin CDN, abre con doble click):

- Tabla con una fila por corrida: etiqueta, fecha de corrida, rango backtesteado,
  commit, trades, win rate, P&L neto, profit factor, max drawdown, máx. pérdidas
  consecutivas. Ordenable por columna (JS vanilla mínimo).
- Curva de equity por corrida como SVG inline (sparkline) generada desde los
  ≤500 puntos del summary.
- El implementador debe cargar el skill `dataviz` antes de escribir el código de
  los gráficos.

## Migración y limpieza

1. Re-descargar con el script los 3 días que hoy existen en JSON viejo.
2. Correr el test de equivalencia (mismo resumen de backtest con cache viejo vs.
   compacto en un día).
3. Recién entonces borrar los 3 JSON viejos de trades (~1.3 GB). Los caches de
   klines quedan como están.
4. Agregar `backtest_runs/` y `*.json.gz` de cache a `.gitignore` si no están
   cubiertos.

## Testing

- Unit: parser del CSV de Binance (header/no header, ms/µs, isBuyerMaker→is_sell),
  construcción de URL por fecha, salteo de días existentes, escritura atómica.
- Unit: lector compacto en el feed produce los mismos eventos que el camino viejo
  (fixture chica sintética en ambos formatos).
- **Equivalencia end-to-end:** backtest de 1 día cacheado en formato viejo vs. el
  mismo día re-descargado compacto ⇒ mismo `summary` (mismos trades, mismo P&L).
- Unit: escritura de `meta.json`/`summary.json`/`trades.csv`, downsample de
  equity (bordes: 0 trades, 1 trade, >500 trades).
- Unit: generador de HTML con 0, 1 y N corridas; corrida corrupta no rompe; el
  HTML no referencia recursos externos.
- Los 222 tests existentes siguen verdes (el fallback REST preserva el
  comportamiento actual cuando no hay cache compacto).

## Criterios de éxito

1. `download_history.py --start 2026-04-01 --end 2026-07-01` completa los 90
   días, reanudable, con uso de RAM acotado (un día a la vez).
2. Un backtest de los 3 meses corre sin OOM y produce carpeta de corrida +
   `index.html` actualizado.
3. Dos corridas con labels distintos aparecen como dos filas comparables en el
   HTML, cada una con su curva de equity.
4. Suite de tests completa en verde.
