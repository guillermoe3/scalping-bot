# Ciclo momentum multi-día (M1-M4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correr los cuatro estudios de tasa base pre-registrados (M1 TSMOM, M2 P/MA, M3 vol targeting, M4 costo de instrumento) sobre velas diarias spot 2017-2026 para decidir si el momentum multi-día en BTC sobrevive a la era institucional — sin escribir código del bot.

**Architecture:** Un descargador nuevo de velas diarias spot (`daily_history.py`, mismo patrón mensual de Binance Vision que `klines_history`). Las métricas de estrategia (serie diaria, Sharpe, drawdown, peor mes) entran como funciones puras a `estudios/nucleo.py`. Cuatro scripts de estudio sobre esa librería, con el candado de verificación existente (`ventana` + `--verificacion`) y corte propio 2024-01-01. M3/M4 se implementan y testean ahora pero solo CORREN si M1/M2 pasan (condicionales).

**Tech Stack:** Python 3.12, stdlib pura (urllib, zipfile, gzip, json, csv, statistics, math), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-07-15-ciclo-momentum-multidia-design.md` (leerla antes de la Task 1; los umbrales pre-registrados son ley).

## Global Constraints

- Tests: `.venv/bin/python -m pytest -q` — suite completa verde al final de cada task (base actual: 281 passed).
- Sin dependencias nuevas. Sin pandas/numpy (~3.250 filas por símbolo; `statistics` sobra).
- Código y comentarios en inglés; docs y reportes en español.
- TDD estricto: test que falla → implementación mínima → verde → commit. Commits: imperativo corto en inglés + footer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Descargas mes a mes; un proceso pesado por vez (lección OOM 2026-07-13; acá todo es liviano igual).
- **El candado de verificación es sagrado:** ningún script corre `--modo verificacion` antes del checkpoint humano de la Task 7. Desarrollo/pruebas: solo calibración o fixtures sintéticos.
- Constantes pre-registradas (fuente: la spec; NO se ajustan al ver datos):
  - Corte del ciclo: `corte_ms = 1704067200000` (2024-01-01T00:00:00Z). Calibración 2017-08→2023-12, verificación 2024-01→presente.
  - M1: lookbacks {7, 14, 28, 56, 90} días; variantes long_short y long_flat; forward descriptivo 1/7/14/28 días; burn-in 90 días.
  - M2: MAs {10, 20, 50, 100} días; estrategia long/flat (long si P/MA > 1); quintiles descriptivos a 1/7/14 días; burn-in 100 días.
  - Umbral de adopción M1/M2 (verbatim en cada reporte): *por celda de estrategia de BTC, en calibración Y verificación por separado (verificación entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de r_strat sobre los días con posición > 0. "Casi" = NO PASA. Solo BTC adopta/veta; ETH robustez.*
  - Criterio de abandono (firmado por Guille 2026-07-15): si ninguna celda de M1 ni M2 pasa en BTC → se congela la búsqueda de señal. Sin excepciones.
  - M3 (condicional): σ_target ∈ {0.20, 0.30, 0.40} anualizado; σ realizada de 30 días × √365; tope de exposición 1×. Adopción: mejora max drawdown Y peor mes calendario vs la cruda Y media ≥ ½ de la cruda, en ambas ventanas.
  - M4 (condicional): ventana 2020-01→hoy (cobertura del funding cacheado); serie perp = pata long − funding diario acumulado; sin umbral, el número decide. Aproximación documentada: precio spot + funding de futuros, base ignorada.
  - Convenciones: señal al cierre de t se aplica al retorno de t+1 (sin lookahead); Sharpe = media/desvío × √365; posiciones valen 0 hasta completar lookback.
- Datos: dumps mensuales `data/spot/monthly/klines/{SYMBOL}/1d/`; verificado 2026-07-15: dumps 2017 traen timestamps en ms SIN header; dumps 2026 traen MICROSEGUNDOS — el parser convierte con el umbral `100_000_000_000_000`. El mes corriente (2026-07) no tiene dump: los estudios cargan con end EXCLUSIVO `"2026-07"`.
- Los reportes de estudio generados bajo `backtest_runs/estudios/` SE COMMITEAN (evidencia del ciclo; `.gitignore` ya tiene la negación).
- Si el sandbox bloquea python inline (`python -c` / heredoc), escribir el snippet a un archivo `.py` temporal y ejecutarlo.

---

### Task 1: Descargador de velas diarias spot (`daily_history.py` nuevo)

URLs verificadas (2026-07-15): `https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2017-08.zip` … `2026-06.zip`. CSV de 12 columnas sin header en dumps viejos; timestamps en µs en dumps recientes. Se guarda `[open_time_ms, open, high, low, close, volume]`.

**Files:**
- Create: `daily_history.py`
- Test: `tests/test_daily_history.py`

**Interfaces:**
- Consumes: `funding_history.MonthNotAvailable`, `funding_history._http_get`, `funding_history._iter_months` (patrón ya usado por `klines_history`).
- Produces (Tasks 3-6 consumen):

```python
# daily_history.py
def build_url(symbol: str, month: str) -> str
def parse_daily_csv(fileobj) -> list[list]          # [[ts_ms,o,h,l,c,vol], ...] ordenado
def month_cache_path(symbol: str, month: str) -> str  # backtest_cache/{symbol}_klines1d_{YYYY-MM}.json.gz
def read_month(symbol: str, month: str) -> Optional[list[list]]
def download_range(symbol: str, start_month: str, end_month: str, fetcher=None, sleep=None) -> dict
def cargar_rango(symbol: str, start_month: str, end_month: str) -> list[list]
    # concatena meses cacheados en orden; ValueError si falta un mes intermedio
# CLI: .venv/bin/python daily_history.py --symbol BTCUSDT --start 2017-08 --end 2026-08
```

- [ ] **Step 1: Tests failing-first**

Contenido completo de `tests/test_daily_history.py` (las dos primeras líneas de datos son REALES, copiadas de los dumps el 2026-07-15):

```python
import io
import zipfile

import daily_history
from daily_history import build_url, parse_daily_csv


def test_build_url():
    assert build_url("BTCUSDT", "2017-08") == (
        "https://data.binance.vision/data/spot/monthly/"
        "klines/BTCUSDT/1d/BTCUSDT-1d-2017-08.zip"
    )


def test_parse_daily_csv_real_millisecond_row():
    # real line from BTCUSDT-1d-2017-08.zip
    line = ("1502928000000,4261.48000000,4485.39000000,4200.74000000,"
            "4285.08000000,795.15037700,1503014399999,3454770.05073206,"
            "3427,616.24854100,2678216.40060401,8733.91139481")
    rows = parse_daily_csv(iter([line]))
    assert rows == [[1502928000000, 4261.48, 4485.39, 4200.74, 4285.08, 795.150377]]


def test_parse_daily_csv_real_microsecond_row_and_header():
    # real line from BTCUSDT-1d-2026-06.zip (microsecond timestamps)
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore",
        ("1780272000000000,73674.39000000,74092.00000000,70686.68000000,"
         "71408.90000000,23921.09184000,1780358399999999,1723958338.68287760,"
         "4237773,11600.30396000,835109172.11680740,0"),
    ]
    rows = parse_daily_csv(iter(lines))
    assert rows == [[1780272000000, 73674.39, 74092.0, 70686.68, 71408.9, 23921.09184]]


def test_parse_daily_csv_sorts_by_timestamp():
    rows = parse_daily_csv(iter([
        "1503014400000,1,2,0.5,1.5,10,1503100799999,15,3,4,6,0",
        "1502928000000,1,2,0.5,1.5,10,1503014399999,15,3,4,6,0",
    ]))
    assert [r[0] for r in rows] == [1502928000000, 1503014400000]


def test_month_roundtrip_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_history, "CACHE_DIR", str(tmp_path))
    rows = [[1502928000000, 1.0, 2.0, 0.5, 1.5, 10.0]]
    daily_history._write_month("BTCUSDT", "2017-08", rows)
    assert daily_history.read_month("BTCUSDT", "2017-08") == rows
    assert daily_history.read_month("BTCUSDT", "2017-09") is None


def test_download_range_skips_cached_months(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_history, "CACHE_DIR", str(tmp_path))
    daily_history._write_month("BTCUSDT", "2017-08", [[1502928000000, 1, 2, 0.5, 1.5, 10]])
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return _zip_with("BTCUSDT-1d-2017-09.csv",
                         "1504224000000,1,2,0.5,1.5,10,1504310399999,15,3,4,6,0\n")

    counts = daily_history.download_range("BTCUSDT", "2017-08", "2017-10", fetcher=fake_fetch)
    assert counts["cached"] == 1 and counts["downloaded"] == 1
    assert calls == [build_url("BTCUSDT", "2017-09")]


def test_cargar_rango_concatenates_and_fails_on_gap(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(daily_history, "CACHE_DIR", str(tmp_path))
    daily_history._write_month("BTCUSDT", "2017-08", [[1502928000000, 1, 2, 0.5, 1.5, 10]])
    daily_history._write_month("BTCUSDT", "2017-09", [[1504224000000, 1, 2, 0.5, 1.5, 10]])
    rows = daily_history.cargar_rango("BTCUSDT", "2017-08", "2017-10")
    assert [r[0] for r in rows] == [1502928000000, 1504224000000]
    with pytest.raises(ValueError, match="missing cached month"):
        daily_history.cargar_rango("BTCUSDT", "2017-08", "2017-11")


def _zip_with(name: str, content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()
```

- [ ] **Step 2: Verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_daily_history.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'daily_history'`).

- [ ] **Step 3: Implementar `daily_history.py`**

Contenido completo:

```python
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
import zipfile
from typing import List, Optional

from funding_history import MonthNotAvailable, _http_get, _iter_months

CACHE_DIR = "backtest_cache"
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
_MICROSECOND_THRESHOLD = 100_000_000_000_000
_MAX_ATTEMPTS = 3


def build_url(symbol: str, month: str) -> str:
    return f"{BASE_URL}/{symbol}/1d/{symbol}-1d-{month}.zip"


def parse_daily_csv(fileobj) -> List[list]:
    rows: List[list] = []
    for rec in csv.reader(fileobj):
        if not rec:
            continue
        try:
            ts = int(rec[0])
        except ValueError:
            continue  # header row
        if ts > _MICROSECOND_THRESHOLD:
            ts //= 1000
        rows.append([ts, float(rec[1]), float(rec[2]), float(rec[3]),
                     float(rec[4]), float(rec[5])])
    rows.sort(key=lambda r: r[0])
    return rows


def month_cache_path(symbol: str, month: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_klines1d_{month}.json.gz")


def read_month(symbol: str, month: str) -> Optional[List[list]]:
    path = month_cache_path(symbol, month)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write_month(symbol: str, month: str, rows: List[list]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = month_cache_path(symbol, month)
    tmp = path + ".tmp"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def download_range(symbol: str, start_month: str, end_month: str,
                   fetcher=None, sleep=None) -> dict:
    """One month at a time; skips months already cached."""
    fetch = fetcher if fetcher is not None else _http_get
    _sleep = sleep if sleep is not None else time.sleep
    counts = {"downloaded": 0, "cached": 0, "missing": 0, "failed": 0}
    for month in _iter_months(start_month, end_month):
        if read_month(symbol, month) is not None:
            counts["cached"] += 1
            print(f"{symbol} {month}: cached")
            continue
        status = "failed"
        for attempt in range(_MAX_ATTEMPTS):
            try:
                payload = fetch(build_url(symbol, month))
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    with zf.open(zf.namelist()[0]) as f:
                        rows = parse_daily_csv(
                            io.TextIOWrapper(f, encoding="utf-8", newline=""))
                _write_month(symbol, month, rows)
                status = "downloaded"
                break
            except MonthNotAvailable:
                status = "missing"
                break
            except Exception:
                if attempt < _MAX_ATTEMPTS - 1:
                    _sleep(2 ** attempt)
        counts[status] += 1
        print(f"{symbol} {month}: {status}")
    return counts


def cargar_rango(symbol: str, start_month: str, end_month: str) -> List[list]:
    """Concatenate cached months in order; a gap is a hard error."""
    rows: List[list] = []
    for month in _iter_months(start_month, end_month):
        mes = read_month(symbol, month)
        if mes is None:
            raise ValueError(f"missing cached month {symbol} {month}")
        rows.extend(mes)
    return rows


def main(argv=None, fetcher=None) -> int:
    parser = argparse.ArgumentParser(
        description="Download monthly daily-kline spot dumps from data.binance.vision.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM (inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM (exclusive)")
    args = parser.parse_args(argv)
    counts = download_range(args.symbol, args.start, args.end, fetcher=fetcher)
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `.venv/bin/python -m pytest tests/test_daily_history.py -v` → PASS.

- [ ] **Step 4: Descarga real (los 2 juegos, uno por vez)**

```bash
.venv/bin/python daily_history.py --symbol BTCUSDT --start 2017-08 --end 2026-08
.venv/bin/python daily_history.py --symbol ETHUSDT --start 2017-08 --end 2026-08
```

Expected: ~107 meses c/u (~25 KB/mes), `failed: 0` (2026-07 → `missing`, aceptable).

- [ ] **Step 5: Paridad contra la API REST de spot**

```bash
.venv/bin/python - <<'EOF'
import json, urllib.request
import daily_history
cached = daily_history.read_month("BTCUSDT", "2026-05")
rest = json.load(urllib.request.urlopen(
    "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d"
    "&startTime=1777593600000&limit=31"))  # 2026-05-01T00:00:00Z
by_ts = {r[0]: r for r in cached}
sample = [k for k in rest if int(k[0]) in by_ts]
bad = [k for k in sample if abs(float(k[4]) - by_ts[int(k[0])][4]) > 1e-6]
print(f"closes match: {len(sample) - len(bad)}/{len(sample)}")
EOF
```

Expected: `closes match: 31/31` (documentar el número real en el commit).

- [ ] **Step 6: Suite completa + commit**

```bash
.venv/bin/python -m pytest -q
git add daily_history.py tests/test_daily_history.py
git commit -m "Add daily spot klines downloader with per-month cache"
```

---

### Task 2: Funciones puras de estrategia en `estudios/nucleo.py`

**Files:**
- Modify: `estudios/nucleo.py` (agregar imports y funciones al final; NO tocar las existentes)
- Test: `tests/test_estudios_nucleo.py` (agregar tests al final)

**Interfaces:**
- Consumes: nada nuevo.
- Produces (Tasks 3-6 consumen EXACTAMENTE esto):

```python
def senal_tsmom(closes: list[float], i: int, k: int) -> Optional[int]
    # sign(closes[i] - closes[i-k]): 1 / -1 / 0; None si i < k
def ratio_ma(closes: list[float], i: int, n: int) -> Optional[float]
    # closes[i] / media(closes[i-n+1 : i+1]); None si i < n-1 o media <= 0
def retornos_diarios(closes: list[float]) -> list[float]
    # [0.0] + retornos simples; misma longitud que closes (el dia 0 no tiene retorno)
def serie_estrategia(retornos: list[float], posiciones: list[float]) -> list[float]
    # r_strat[t-1] = posiciones[t-1] * retornos[t], t = 1..N-1 (longitud N-1)
def sharpe_anualizado(rets: list[float]) -> Optional[float]
    # media/desvio * sqrt(365); None si n < 2 o desvio == 0
def max_drawdown(rets: list[float]) -> float
    # caida pico-a-valle de la curva compuesta, como fraccion positiva
def peor_mes(ts_list: list[int], rets: list[float]) -> Optional[float]
    # peor retorno compuesto por mes calendario UTC; None si vacio o desalineado
def metricas_estrategia(retornos, posiciones, eval_desde=0) -> dict
    # {"n_dias","n_dias_en_posicion","sharpe","max_drawdown","media","mediana_en_posicion"}
def metricas_buy_and_hold(retornos, eval_desde=0) -> dict
    # {"n_dias","sharpe","max_drawdown","media"}
```

- [ ] **Step 1: Tests failing-first (agregar a `tests/test_estudios_nucleo.py`)**

```python
import math

from estudios.nucleo import (
    max_drawdown,
    metricas_buy_and_hold,
    metricas_estrategia,
    peor_mes,
    ratio_ma,
    retornos_diarios,
    senal_tsmom,
    serie_estrategia,
    sharpe_anualizado,
)


def test_senal_tsmom_signo_y_borde():
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert senal_tsmom(closes, 2, 2) == 1     # 101 > 100
    assert senal_tsmom(closes, 3, 2) == -1    # 99 < 102
    assert senal_tsmom(closes, 1, 2) is None  # sin lookback completo
    assert senal_tsmom([100.0, 100.0, 100.0], 2, 2) == 0


def test_ratio_ma_y_borde():
    closes = [100.0, 110.0, 120.0]
    assert ratio_ma(closes, 2, 3) == 120.0 / 110.0
    assert ratio_ma(closes, 1, 3) is None


def test_retornos_diarios():
    rets = retornos_diarios([100.0, 110.0, 99.0])
    assert rets[0] == 0.0
    assert rets[1] == 0.1
    assert abs(rets[2] - (-0.1)) < 1e-12


def test_serie_estrategia_aplica_posicion_del_dia_previo():
    # pos decided at close of t applies to the return of t+1
    assert serie_estrategia([0.0, 0.01, -0.02], [1.0, -1.0, 0.0]) == [0.01, 0.02]


def test_sharpe_anualizado():
    assert abs(sharpe_anualizado([0.01, 0.02, 0.03]) - 2.0 * math.sqrt(365)) < 1e-9
    assert sharpe_anualizado([0.01]) is None
    assert sharpe_anualizado([0.01, 0.01]) is None  # desvio 0


def test_max_drawdown():
    # equity: 1.10 -> 0.88 -> 0.968; peak 1.10 -> dd = 1 - 0.88/1.10 = 0.2
    assert abs(max_drawdown([0.10, -0.20, 0.10]) - 0.2) < 1e-12
    assert max_drawdown([0.01, 0.01]) == 0.0


def test_peor_mes():
    ene = 1767225600000   # 2026-01-01T00:00:00Z
    feb = 1769904000000   # 2026-02-01T00:00:00Z
    ts = [ene, ene + 86_400_000, feb]
    assert abs(peor_mes(ts, [0.01, 0.01, -0.02]) - (-0.02)) < 1e-12
    assert peor_mes([], []) is None


def test_metricas_estrategia_y_buy_and_hold():
    retornos = [0.0, 0.10, -0.20, 0.10]
    posiciones = [1.0, 1.0, 0.0, 1.0]
    m = metricas_estrategia(retornos, posiciones)
    assert m["n_dias"] == 3
    assert m["n_dias_en_posicion"] == 2          # days 1 and 2 held a position
    assert abs(m["max_drawdown"] - 0.2) < 1e-12  # 1.10 -> 0.88 -> 0.88
    assert abs(m["mediana_en_posicion"] - (-0.05)) < 1e-12
    b = metricas_buy_and_hold(retornos)
    assert b["n_dias"] == 3
    assert abs(b["media"] - (0.10 - 0.20 + 0.10) / 3) < 1e-12


def test_metricas_estrategia_eval_desde_recorta_el_burn_in():
    retornos = [0.0, 0.05, 0.10, -0.20]
    posiciones = [1.0, 1.0, 1.0, 1.0]
    m = metricas_estrategia(retornos, posiciones, eval_desde=2)
    assert m["n_dias"] == 2  # solo los dias 2 y 3
```

Run: `.venv/bin/python -m pytest tests/test_estudios_nucleo.py -v` → FAIL (`ImportError`).

- [ ] **Step 2: Implementar (agregar al final de `estudios/nucleo.py`)**

Agregar a los imports del módulo: `import math` y `from datetime import datetime, timezone` (`statistics` ya está importado; el código nuevo usa `statistics.X` como el resto del archivo).

```python
# --- Daily-strategy metrics (M-cycle, spec 2026-07-15) ---

CORTE_MOMENTUM_MS = 1704067200000  # 2024-01-01T00:00:00Z


def senal_tsmom(closes: list[float], i: int, k: int) -> Optional[int]:
    """Sign of the k-day return ending at i; None without a full lookback."""
    if i < k:
        return None
    if closes[i] > closes[i - k]:
        return 1
    if closes[i] < closes[i - k]:
        return -1
    return 0


def ratio_ma(closes: list[float], i: int, n: int) -> Optional[float]:
    """closes[i] over the n-day simple moving average ending at i."""
    if i < n - 1:
        return None
    ma = statistics.fmean(closes[i - n + 1 : i + 1])
    return closes[i] / ma if ma > 0 else None


def retornos_diarios(closes: list[float]) -> list[float]:
    """Simple daily returns, same length as closes (day 0 has no return -> 0.0)."""
    rets = [0.0]
    for t in range(1, len(closes)):
        rets.append(closes[t] / closes[t - 1] - 1.0)
    return rets


def serie_estrategia(retornos: list[float], posiciones: list[float]) -> list[float]:
    """r_strat[t-1] = posiciones[t-1] * retornos[t] (no lookahead by construction)."""
    if len(retornos) != len(posiciones):
        raise ValueError("retornos and posiciones must be aligned")
    return [posiciones[t - 1] * retornos[t] for t in range(1, len(retornos))]


def sharpe_anualizado(rets: list[float]) -> Optional[float]:
    if len(rets) < 2:
        return None
    sd = statistics.stdev(rets)
    if sd == 0:
        return None
    return statistics.fmean(rets) / sd * math.sqrt(365)


def max_drawdown(rets: list[float]) -> float:
    """Peak-to-trough drop of the compounded equity curve (0.2 means -20%)."""
    equity = peak = 1.0
    worst = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = max(worst, 1.0 - equity / peak)
    return worst


def peor_mes(ts_list: list[int], rets: list[float]) -> Optional[float]:
    """Worst compounded calendar-month (UTC) return; ts_list[i] is rets[i]'s day."""
    if not rets or len(ts_list) != len(rets):
        return None
    por_mes: dict = {}
    for ts, r in zip(ts_list, rets):
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        clave = (d.year, d.month)
        por_mes[clave] = por_mes.get(clave, 1.0) * (1.0 + r)
    return min(v - 1.0 for v in por_mes.values())


def metricas_estrategia(retornos: list[float], posiciones: list[float],
                        eval_desde: int = 0) -> dict:
    """Adoption metrics of a daily-rebalanced strategy from day max(1, eval_desde)."""
    idx0 = max(1, eval_desde)
    r_full = serie_estrategia(retornos, posiciones)  # r_full[t-1] is day t
    r_strat = r_full[idx0 - 1:]
    en_pos = [r_full[t - 1] for t in range(idx0, len(retornos))
              if posiciones[t - 1] != 0.0]
    return {
        "n_dias": len(r_strat),
        "n_dias_en_posicion": len(en_pos),
        "sharpe": sharpe_anualizado(r_strat),
        "max_drawdown": max_drawdown(r_strat),
        "media": statistics.fmean(r_strat) if r_strat else None,
        "mediana_en_posicion": statistics.median(en_pos) if en_pos else None,
    }


def metricas_buy_and_hold(retornos: list[float], eval_desde: int = 0) -> dict:
    idx0 = max(1, eval_desde)
    bh = retornos[idx0:]
    return {
        "n_dias": len(bh),
        "sharpe": sharpe_anualizado(bh),
        "max_drawdown": max_drawdown(bh),
        "media": statistics.fmean(bh) if bh else None,
    }
```

- [ ] **Step 3: Suite verde + commit**

```bash
.venv/bin/python -m pytest tests/test_estudios_nucleo.py -q
.venv/bin/python -m pytest -q
git add estudios/nucleo.py tests/test_estudios_nucleo.py
git commit -m "Add daily-strategy metric primitives to the study library"
```

---

### Task 3: Estudio M1 — TSMOM (`estudios/estudio_momentum.py`)

**Files:**
- Create: `estudios/estudio_momentum.py`
- Test: `tests/test_estudio_momentum.py`

**Interfaces:**
- Consumes: `daily_history.cargar_rango`, y de `estudios.nucleo`: `ventana`, `retorno_forward`, `resumen`, `senal_tsmom`, `retornos_diarios`, `metricas_estrategia`, `metricas_buy_and_hold`, `CORTE_MOMENTUM_MS`; `estudios.reporte.escribir_reporte`.
- Produces: reporte `momentum-{modo}`; funciones que M3/M4 importan:

```python
LOOKBACKS = (7, 14, 28, 56, 90)
BURN_IN = 90
START_MONTH = "2017-08"
END_MONTH = "2026-07"   # exclusivo: mes corriente sin dump
def posiciones_tsmom(closes: list[float], k: int, variante: str) -> list[float]
    # variante in {"long_short", "long_flat"}; 0.0 hasta completar lookback
def rows_con_burn_in(symbol: str, modo: str, verificacion: bool) -> tuple[list[list], int]
    # (rows, eval_desde): en verificacion antepone los BURN_IN dias previos al
    # corte (solo alimentan senal); eval_desde marca desde donde se evalua
```

- [ ] **Step 1: Tests failing-first**

Contenido completo de `tests/test_estudio_momentum.py`:

```python
from estudios.estudio_momentum import posiciones_tsmom


def test_posiciones_long_short():
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert posiciones_tsmom(closes, 2, "long_short") == [0.0, 0.0, 1.0, -1.0, -1.0]


def test_posiciones_long_flat_recorta_el_lado_corto():
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert posiciones_tsmom(closes, 2, "long_flat") == [0.0, 0.0, 1.0, 0.0, 0.0]
```

Run: `.venv/bin/python -m pytest tests/test_estudio_momentum.py -v` → FAIL.

- [ ] **Step 2: Implementar `estudios/estudio_momentum.py`**

Contenido completo:

```python
from __future__ import annotations

import argparse
import sys
from typing import List

import daily_history
from estudios.nucleo import (
    CORTE_MOMENTUM_MS,
    metricas_buy_and_hold,
    metricas_estrategia,
    retorno_forward,
    retornos_diarios,
    resumen,
    senal_tsmom,
    ventana,
)
from estudios.reporte import escribir_reporte

LOOKBACKS = (7, 14, 28, 56, 90)
HORIZONTES = {"1d": 1, "7d": 7, "14d": 14, "28d": 28}
BURN_IN = 90
START_MONTH = "2017-08"
END_MONTH = "2026-07"  # exclusive: current month has no published dump

PREREGISTRO = {
    "rol": "M1 TSMOM — estudio de adopcion (spec 2026-07-15)",
    "datos": "klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC+ETH",
    "senal": "sign(ret[t-k, t]), k in {7,14,28,56,90}; la posicion decidida al cierre de t se aplica al retorno de t+1",
    "variantes": "long_short (pos=senal) y long_flat (pos=max(senal,0)); posiciones 0 hasta completar lookback",
    "split": "calibracion 2017-08 -> 2023-12; verificacion 2024-01 -> presente (sellada); corte_ms=1704067200000",
    "burn_in": "en verificacion, los 90 dias previos al corte solo alimentan la senal",
    "descriptivo": "retorno forward 1/7/14/28d firmado, por lado — SOLO descriptivo (ventanas superpuestas, errores autocorrelacionados)",
    "umbral_adopcion": (
        "por celda de estrategia de BTC, en calibracion Y verificacion por separado "
        "(verificacion entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, "
        "Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de "
        "r_strat sobre los dias con posicion > 0. 'Casi' = NO PASA. Solo BTC adopta/veta; ETH robustez."
    ),
    "criterio_abandono": "si ninguna celda de M1 ni M2 pasa en BTC -> se congela la busqueda de senal (firmado 2026-07-15)",
    "n_efectivo": "advertencia pre-registrada: BTC tiene ~4 ciclos de mercado independientes; el n efectivo de regimenes es 4, no ~3250 dias",
}


def posiciones_tsmom(closes: List[float], k: int, variante: str) -> List[float]:
    """Position decided at the close of each day (0.0 until the lookback fills)."""
    out: List[float] = []
    for i in range(len(closes)):
        s = senal_tsmom(closes, i, k)
        pos = float(s) if s is not None else 0.0
        if variante == "long_flat" and pos < 0.0:
            pos = 0.0
        out.append(pos)
    return out


def rows_con_burn_in(symbol: str, modo: str, verificacion: bool):
    """Window rows plus, in verification mode, a signal-only burn-in prefix."""
    todas = daily_history.cargar_rango(symbol, START_MONTH, END_MONTH)
    seleccion = ventana(todas, modo, corte_ms=CORTE_MOMENTUM_MS,
                        verificacion_habilitada=verificacion)
    if modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_MOMENTUM_MS][-BURN_IN:]
        return previos + seleccion, len(previos)
    return seleccion, 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M1: TSMOM base-rate study on daily spot klines.")
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    args = parser.parse_args(argv)
    simbolos = [s.strip() for s in args.symbols.split(",") if s.strip()]

    resultados: dict = {}
    for symbol in simbolos:
        rows, eval_desde = rows_con_burn_in(symbol, args.modo, args.verificacion)
        closes = [r[4] for r in rows]
        rets = retornos_diarios(closes)
        por_simbolo: dict = {
            "buy_and_hold": metricas_buy_and_hold(rets, eval_desde),
            "estrategia": {},
            "descriptivo": {},
        }
        for k in LOOKBACKS:
            celdas_k: dict = {}
            for variante in ("long_short", "long_flat"):
                pos = posiciones_tsmom(closes, k, variante)
                celdas_k[variante] = metricas_estrategia(rets, pos, eval_desde)
            por_simbolo["estrategia"][str(k)] = celdas_k

            desc: dict = {}
            for nombre_h, h in HORIZONTES.items():
                largos: List[float] = []
                cortos: List[float] = []
                for i in range(max(eval_desde, k), len(rows)):
                    s = senal_tsmom(closes, i, k)
                    if not s:
                        continue
                    fwd = retorno_forward(closes, i, h)
                    if fwd is None:
                        continue
                    (largos if s > 0 else cortos).append(s * fwd)
                desc[nombre_h] = {"long": resumen(largos), "short": resumen(cortos)}
            por_simbolo["descriptivo"][str(k)] = desc
        resultados[symbol] = por_simbolo

    celdas = len(simbolos) * (len(LOOKBACKS) * 2 + len(LOOKBACKS) * len(HORIZONTES) * 2)
    ruta = escribir_reporte(f"momentum-{args.modo}", PREREGISTRO, celdas, resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `.venv/bin/python -m pytest tests/test_estudio_momentum.py -v` → PASS.

- [ ] **Step 3: Corrida de calibración (la única de esta task; JAMÁS `--modo verificacion`)**

```bash
.venv/bin/python -m estudios.estudio_momentum --modo calibracion --symbols BTCUSDT,ETHUSDT
```

Expected: reporte con celdas=100; por símbolo ~2.330 días de calibración (2017-08→2023-12); sanity: `n_dias` de buy_and_hold ≈ n_dias de cada celda de estrategia. Sin editorializar sobre los números.

- [ ] **Step 4: Suite completa + commit**

```bash
.venv/bin/python -m pytest -q
git add estudios/estudio_momentum.py tests/test_estudio_momentum.py backtest_runs/estudios/
git commit -m "Add TSMOM base-rate study (M1) and its calibration report"
```

---

### Task 4: Estudio M2 — P/MA, réplica de Detzel (`estudios/estudio_ma.py`)

**Files:**
- Create: `estudios/estudio_ma.py`
- Test: `tests/test_estudio_ma.py`

**Interfaces:**
- Consumes: como Task 3, más `ratio_ma` de nucleo y `rows_con_burn_in`-equivalente propio (burn-in 100).
- Produces: reporte `ma-{modo}`; para M3/M4:

```python
MAS = (10, 20, 50, 100)
BURN_IN = 100
def posiciones_ma(closes: list[float], n: int) -> list[float]
    # long/flat: 1.0 si ratio_ma > 1, si no 0.0 (None -> 0.0)
def rows_con_burn_in(symbol: str, modo: str, verificacion: bool) -> tuple[list[list], int]
```

- [ ] **Step 1: Tests failing-first**

Contenido completo de `tests/test_estudio_ma.py`:

```python
from estudios.estudio_ma import posiciones_ma


def test_posiciones_ma_long_flat():
    closes = [100.0, 100.0, 100.0, 130.0]
    # i=0: sin MA(2) completa -> 0; i=1,2: ratio == 1.0 (no > 1) -> 0
    # i=3: MA = (100+130)/2 = 115, ratio > 1 -> 1
    assert posiciones_ma(closes, 2) == [0.0, 0.0, 0.0, 1.0]
```

Run → FAIL.

- [ ] **Step 2: Implementar `estudios/estudio_ma.py`**

Contenido completo:

```python
from __future__ import annotations

import argparse
import sys
from typing import List

import daily_history
from estudios.nucleo import (
    CORTE_MOMENTUM_MS,
    metricas_buy_and_hold,
    metricas_estrategia,
    ratio_ma,
    retorno_forward,
    retornos_diarios,
    resumen,
    ventana,
)
from estudios.reporte import escribir_reporte

MAS = (10, 20, 50, 100)
HORIZONTES = {"1d": 1, "7d": 7, "14d": 14}
BURN_IN = 100
START_MONTH = "2017-08"
END_MONTH = "2026-07"  # exclusive: current month has no published dump

PREREGISTRO = {
    "rol": "M2 P/MA (replica de Detzel et al. 2021) — estudio de adopcion (spec 2026-07-15)",
    "datos": "klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC+ETH",
    "senal": "P(t)/MA_n(close), n in {10,20,50,100}; long si ratio > 1, flat si <= 1 (sin banda muerta); la posicion decidida al cierre de t se aplica al retorno de t+1",
    "split": "calibracion 2017-08 -> 2023-12; verificacion 2024-01 -> presente (sellada); corte_ms=1704067200000",
    "burn_in": "en verificacion, los 100 dias previos al corte solo alimentan la senal",
    "descriptivo": "contraste de quintiles del ratio (quintil alto vs bajo, forward 1/7/14d) DENTRO de cada ventana — SOLO descriptivo",
    "umbral_adopcion": (
        "por celda de estrategia de BTC, en calibracion Y verificacion por separado "
        "(verificacion entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, "
        "Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de "
        "r_strat sobre los dias con posicion > 0. 'Casi' = NO PASA. Solo BTC adopta/veta; ETH robustez."
    ),
    "regla_fragilidad": "si M1 pasa y M2 falla (o viceversa) en celdas economicamente equivalentes, se reporta como fragilidad de especificacion — no se elige la mejor",
    "criterio_abandono": "si ninguna celda de M1 ni M2 pasa en BTC -> se congela la busqueda de senal (firmado 2026-07-15)",
}


def posiciones_ma(closes: List[float], n: int) -> List[float]:
    """Long/flat position decided at the close of each day (paper spec)."""
    out: List[float] = []
    for i in range(len(closes)):
        ratio = ratio_ma(closes, i, n)
        out.append(1.0 if ratio is not None and ratio > 1.0 else 0.0)
    return out


def rows_con_burn_in(symbol: str, modo: str, verificacion: bool):
    """Window rows plus, in verification mode, a signal-only burn-in prefix."""
    todas = daily_history.cargar_rango(symbol, START_MONTH, END_MONTH)
    seleccion = ventana(todas, modo, corte_ms=CORTE_MOMENTUM_MS,
                        verificacion_habilitada=verificacion)
    if modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_MOMENTUM_MS][-BURN_IN:]
        return previos + seleccion, len(previos)
    return seleccion, 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M2: price-to-MA base-rate study on daily spot klines.")
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    args = parser.parse_args(argv)
    simbolos = [s.strip() for s in args.symbols.split(",") if s.strip()]

    resultados: dict = {}
    for symbol in simbolos:
        rows, eval_desde = rows_con_burn_in(symbol, args.modo, args.verificacion)
        closes = [r[4] for r in rows]
        rets = retornos_diarios(closes)
        por_simbolo: dict = {
            "buy_and_hold": metricas_buy_and_hold(rets, eval_desde),
            "estrategia": {},
            "quintiles": {},
        }
        for n in MAS:
            pos = posiciones_ma(closes, n)
            por_simbolo["estrategia"][str(n)] = metricas_estrategia(rets, pos, eval_desde)

            desc: dict = {}
            for nombre_h, h in HORIZONTES.items():
                pares: List[tuple] = []
                for i in range(max(eval_desde, n - 1), len(rows)):
                    ratio = ratio_ma(closes, i, n)
                    fwd = retorno_forward(closes, i, h)
                    if ratio is None or fwd is None:
                        continue
                    pares.append((ratio, fwd))
                pares.sort(key=lambda p: p[0])
                quinto = len(pares) // 5
                desc[nombre_h] = {
                    "q_bajo": resumen([f for _, f in pares[:quinto]]),
                    "q_alto": resumen([f for _, f in pares[-quinto:]]) if quinto else resumen([]),
                }
            por_simbolo["quintiles"][str(n)] = desc
        resultados[symbol] = por_simbolo

    celdas = len(simbolos) * (len(MAS) + len(MAS) * len(HORIZONTES) * 2)
    ruta = escribir_reporte(f"ma-{args.modo}", PREREGISTRO, celdas, resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run tests → PASS.

- [ ] **Step 3: Corrida de calibración (única; JAMÁS verificación)**

```bash
.venv/bin/python -m estudios.estudio_ma --modo calibracion --symbols BTCUSDT,ETHUSDT
```

Expected: reporte con celdas=56.

- [ ] **Step 4: Suite completa + commit**

```bash
.venv/bin/python -m pytest -q
git add estudios/estudio_ma.py tests/test_estudio_ma.py backtest_runs/estudios/
git commit -m "Add price-to-MA base-rate study (M2) and its calibration report"
```

---

### Task 5: Estudio M3 — overlay de vol targeting (`estudios/estudio_vol_overlay.py`; se implementa ahora, corre solo si M1/M2 pasan)

**Files:**
- Create: `estudios/estudio_vol_overlay.py`
- Test: `tests/test_estudio_vol_overlay.py`

**Interfaces:**
- Consumes: `posiciones_tsmom`/`rows_con_burn_in` de `estudios.estudio_momentum`, `posiciones_ma` (y su `rows_con_burn_in`) de `estudios.estudio_ma`, métricas de nucleo.
- Produces: reporte `vol-overlay-{modo}`. CLI:
  `--estudio {momentum,ma} --parametro K_O_N --variante {long_short,long_flat} --modo ... [--verificacion]`
  (para `--estudio ma` la variante válida es solo `long_flat`).

- [ ] **Step 1: Tests failing-first**

Contenido completo de `tests/test_estudio_vol_overlay.py`:

```python
from estudios.estudio_vol_overlay import VENTANA_SIGMA, exposiciones


def test_exposiciones_cero_durante_burn_in_y_con_sigma_cero():
    rets = [0.0] * (VENTANA_SIGMA + 5)
    exp = exposiciones(rets, 0.30)
    assert all(e == 0.0 for e in exp)  # sigma 0 -> sin exposicion


def test_exposiciones_capped_a_uno_y_monotonas_en_target():
    # alternating +-3% daily: sigma anualizada ~ 0.57 -> target 0.2 da < 1
    rets = [0.03 if i % 2 == 0 else -0.03 for i in range(VENTANA_SIGMA + 10)]
    e_bajo = exposiciones(rets, 0.20)
    e_alto = exposiciones(rets, 5.00)
    t = VENTANA_SIGMA + 5
    assert 0.0 < e_bajo[t] < 1.0
    assert e_alto[t] == 1.0            # cap de exposicion 1x
    assert e_bajo[t] <= e_alto[t]      # monotonia en sigma_target
    assert all(e == 0.0 for e in e_bajo[:VENTANA_SIGMA])
```

Run → FAIL.

- [ ] **Step 2: Implementar `estudios/estudio_vol_overlay.py`**

Contenido completo:

```python
from __future__ import annotations

import argparse
import math
import statistics
import sys
from typing import List

from estudios import estudio_ma, estudio_momentum
from estudios.nucleo import (
    metricas_estrategia,
    peor_mes,
    retornos_diarios,
    serie_estrategia,
)
from estudios.reporte import escribir_reporte

SIGMA_TARGETS = (0.20, 0.30, 0.40)
VENTANA_SIGMA = 30

PREREGISTRO = {
    "rol": "M3 vol targeting — CONDICIONAL: corre solo si alguna celda de M1/M2 paso calibracion Y verificacion (spec 2026-07-15)",
    "overlay": "exposicion(t) = min(1, sigma_target / sigma_realizada_30d(t)); sigma realizada = desvio de los ultimos 30 retornos diarios x sqrt(365), calculada al cierre de t y aplicada a t+1; tope 1x",
    "grilla": "sigma_target in {0.20, 0.30, 0.40} anualizado",
    "umbral_adopcion": "en calibracion Y verificacion: mejora max drawdown Y peor mes calendario vs la version cruda, Y media de r_strat >= 1/2 de la cruda",
    "celda_base": "la mejor celda ganadora de M1/M2 en BTC (mayor Sharpe de verificacion), pasada por CLI",
}


def exposiciones(rets: List[float], sigma_target: float) -> List[float]:
    """Volatility-targeted exposure decided at the close of each day."""
    out: List[float] = []
    for t in range(len(rets)):
        if t < VENTANA_SIGMA:
            out.append(0.0)
            continue
        sd = statistics.stdev(rets[t - VENTANA_SIGMA + 1 : t + 1]) * math.sqrt(365)
        out.append(min(1.0, sigma_target / sd) if sd > 0 else 0.0)
    return out


def _posiciones_base(args, closes: List[float]) -> List[float]:
    if args.estudio == "momentum":
        return estudio_momentum.posiciones_tsmom(closes, args.parametro, args.variante)
    return estudio_ma.posiciones_ma(closes, args.parametro)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M3: volatility-targeting overlay on the winning M1/M2 cell.")
    parser.add_argument("--estudio", required=True, choices=("momentum", "ma"))
    parser.add_argument("--parametro", required=True, type=int,
                        help="lookback k (momentum) or MA length n (ma)")
    parser.add_argument("--variante", default="long_flat",
                        choices=("long_short", "long_flat"))
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args(argv)
    if args.estudio == "ma" and args.variante != "long_flat":
        parser.error("--estudio ma only supports --variante long_flat")

    modulo = estudio_momentum if args.estudio == "momentum" else estudio_ma
    rows, eval_desde = modulo.rows_con_burn_in(args.symbol, args.modo, args.verificacion)
    closes = [r[4] for r in rows]
    rets = retornos_diarios(closes)
    pos_base = _posiciones_base(args, closes)

    idx0 = max(1, eval_desde)
    ts_eval = [rows[t][0] for t in range(idx0, len(rows))]

    def _celda(posiciones: List[float]) -> dict:
        celda = metricas_estrategia(rets, posiciones, eval_desde)
        r_strat = serie_estrategia(rets, posiciones)[idx0 - 1:]
        celda["peor_mes"] = peor_mes(ts_eval, r_strat)
        return celda

    resultados: dict = {"celda_base": vars(args) | {"symbol": args.symbol},
                        "cruda": _celda(pos_base), "overlay": {}}
    for target in SIGMA_TARGETS:
        exp = exposiciones(rets, target)
        pos_overlay = [p * e for p, e in zip(pos_base, exp)]
        resultados["overlay"][f"{target:.2f}"] = _celda(pos_overlay)

    ruta = escribir_reporte(f"vol-overlay-{args.modo}", PREREGISTRO,
                            celdas=1 + len(SIGMA_TARGETS), resultados=resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Nota: `vars(args)` incluye claves booleanas del CLI en el reporte — aceptable, documenta la corrida exacta.

Run tests → PASS.

- [ ] **Step 3: Suite completa + commit (SIN correr el estudio — es condicional)**

```bash
.venv/bin/python -m pytest -q
git add estudios/estudio_vol_overlay.py tests/test_estudio_vol_overlay.py
git commit -m "Add conditional vol-targeting overlay study (M3), not yet run"
```

---

### Task 6: Estudio M4 — costo de instrumento (`estudios/estudio_instrumento.py`; se implementa ahora, corre solo si M1/M2 pasan)

**Files:**
- Create: `estudios/estudio_instrumento.py`
- Test: `tests/test_estudio_instrumento.py`

**Interfaces:**
- Consumes: `funding_history.read_funding` (cache de FUTUROS ya poblado 2020→hoy), `posiciones_tsmom`/`posiciones_ma`, métricas de nucleo. Datos de precio: `daily_history.cargar_rango(symbol, "2020-01", END_MONTH)` — la ventana de M4 arranca en 2020-01 por cobertura del funding (pre-registrado).
- Produces: reporte `instrumento-{modo}`. CLI igual a M3.

- [ ] **Step 1: Tests failing-first**

Contenido completo de `tests/test_estudio_instrumento.py`:

```python
from estudios.estudio_instrumento import funding_por_dia, serie_neta


def test_funding_por_dia_suma_las_lecturas_del_dia_utc():
    dia = 1704067200000  # 2024-01-01T00:00:00Z
    rows = [[dia, 0.0001], [dia + 8 * 3_600_000, 0.0002], [dia + 86_400_000, 0.0005]]
    assert funding_por_dia(rows) == {dia: 0.0003, dia + 86_400_000: 0.0005}


def test_serie_neta_resta_funding_solo_en_dias_long():
    dia0 = 1704067200000
    rows = [[dia0, 0, 0, 0, 100.0, 0], [dia0 + 86_400_000, 0, 0, 0, 102.0, 0]]
    rets = [0.0, 0.02]
    pos_long = [1.0, 1.0]
    por_dia = {dia0 + 86_400_000: 0.001}
    bruta, neta = serie_neta(rows, rets, pos_long, por_dia, eval_desde=0)
    assert bruta == [0.02]
    assert abs(neta[0] - 0.019) < 1e-12
```

Run → FAIL.

- [ ] **Step 2: Implementar `estudios/estudio_instrumento.py`**

Contenido completo:

```python
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Tuple

import daily_history
import funding_history
from estudios import estudio_ma, estudio_momentum
from estudios.nucleo import (
    CORTE_MOMENTUM_MS,
    max_drawdown,
    retornos_diarios,
    sharpe_anualizado,
    ventana,
)
from estudios.reporte import escribir_reporte

START_MONTH = "2020-01"  # funding cache coverage (pre-registered M4 window)
END_MONTH = "2026-07"
_DIA_MS = 86_400_000

PREREGISTRO = {
    "rol": "M4 costo de instrumento — CONDICIONAL: corre solo si alguna celda de M1/M2 paso (spec 2026-07-15)",
    "ventana": "2020-01 -> presente (cobertura del funding cacheado); la calibracion pre-2020 queda fuera de M4 — es comparacion de costos, no test de senal",
    "series": "A (perp) = pata long menos funding acumulado de los dias en posicion; B (spot) = pata long sin funding",
    "aproximacion": "precio SPOT + funding de FUTUROS; la base spot-perp se ignora (documentado)",
    "decision": "sin umbral: la diferencia de retorno total y Sharpe decide el instrumento de la pata long en el ciclo de diseno de senal",
}


def funding_por_dia(funding_rows: List[list]) -> Dict[int, float]:
    """Sum the (three) 8h funding readings of each UTC day."""
    por_dia: Dict[int, float] = {}
    for ts, rate in funding_rows:
        dia = ts - ts % _DIA_MS
        por_dia[dia] = por_dia.get(dia, 0.0) + rate
    return por_dia


def serie_neta(rows: List[list], rets: List[float], pos_long: List[float],
               por_dia: Dict[int, float], eval_desde: int) -> Tuple[List[float], List[float]]:
    """(gross, net-of-funding) daily returns of the long leg from max(1, eval_desde)."""
    idx0 = max(1, eval_desde)
    bruta: List[float] = []
    neta: List[float] = []
    for t in range(idx0, len(rows)):
        r = pos_long[t - 1] * rets[t]
        bruta.append(r)
        dia = rows[t][0] - rows[t][0] % _DIA_MS
        neta.append(r - pos_long[t - 1] * por_dia.get(dia, 0.0))
    return bruta, neta


def _metricas(serie: List[float]) -> dict:
    total = 1.0
    for r in serie:
        total *= 1.0 + r
    return {
        "n_dias": len(serie),
        "retorno_total": total - 1.0,
        "sharpe": sharpe_anualizado(serie),
        "max_drawdown": max_drawdown(serie),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M4: perp-funding drag vs spot for the winning cell's long leg.")
    parser.add_argument("--estudio", required=True, choices=("momentum", "ma"))
    parser.add_argument("--parametro", required=True, type=int)
    parser.add_argument("--variante", default="long_flat",
                        choices=("long_short", "long_flat"))
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args(argv)
    if args.estudio == "ma" and args.variante != "long_flat":
        parser.error("--estudio ma only supports --variante long_flat")

    burn_in = estudio_momentum.BURN_IN if args.estudio == "momentum" else estudio_ma.BURN_IN
    todas = daily_history.cargar_rango(args.symbol, START_MONTH, END_MONTH)
    seleccion = ventana(todas, args.modo, corte_ms=CORTE_MOMENTUM_MS,
                        verificacion_habilitada=args.verificacion)
    if args.modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_MOMENTUM_MS][-burn_in:]
        rows, eval_desde = previos + seleccion, len(previos)
    else:
        rows, eval_desde = seleccion, 0

    closes = [r[4] for r in rows]
    rets = retornos_diarios(closes)
    if args.estudio == "momentum":
        pos = estudio_momentum.posiciones_tsmom(closes, args.parametro, args.variante)
    else:
        pos = estudio_ma.posiciones_ma(closes, args.parametro)
    pos_long = [p if p > 0.0 else 0.0 for p in pos]

    por_dia = funding_por_dia(funding_history.read_funding(args.symbol))
    bruta, neta = serie_neta(rows, rets, pos_long, por_dia, eval_desde)

    resultados = {
        "celda_base": vars(args) | {"symbol": args.symbol},
        "spot_sin_funding": _metricas(bruta),
        "perp_neto_de_funding": _metricas(neta),
        "drag_retorno_total": _metricas(bruta)["retorno_total"] - _metricas(neta)["retorno_total"],
    }
    ruta = escribir_reporte(f"instrumento-{args.modo}", PREREGISTRO,
                            celdas=2, resultados=resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run tests → PASS.

- [ ] **Step 3: Suite completa + commit (SIN correr el estudio — es condicional)**

```bash
.venv/bin/python -m pytest -q
git add estudios/estudio_instrumento.py tests/test_estudio_instrumento.py
git commit -m "Add conditional instrument-cost study (M4), not yet run"
```

---

### Task 7: CHECKPOINT humano + verificación + condicionales + veredicto

**Esta task empieza con una pausa obligatoria:** los scripts deben estar revisados y congelados, y Guille debe revisar los reportes de calibración de M1/M2 y dar el OK explícito ANTES de abrir la ventana de verificación.

**Files:**
- Create: `backtest_runs/estudios/veredicto-momentum-2026-07.md` (a mano, números reales)
- Modify: `docs/mejoras-propuestas.md`

**Interfaces:**
- Consumes: reportes de calibración (Tasks 3-4), scripts congelados (Tasks 3-6).
- Produces: veredicto del ciclo contra el umbral pre-registrado y el criterio de abandono firmado.

- [ ] **Step 1: Confirmar revisión aprobada de Tasks 1-6 y OK de Guille (gate humano)**

- [ ] **Step 2: Corridas de verificación de M1 y M2 (una sola vez, scripts congelados)**

```bash
.venv/bin/python -m estudios.estudio_momentum --modo verificacion --verificacion --symbols BTCUSDT,ETHUSDT
.venv/bin/python -m estudios.estudio_ma       --modo verificacion --verificacion --symbols BTCUSDT,ETHUSDT
```

Si aparece un bug después de estas corridas: se arregla, se re-corre TODO (calibración y verificación) y el veredicto lo declara ("re-corrida post-fix").

- [ ] **Step 3: Evaluar el umbral por celda de BTC (a mano, en el veredicto)**

Para cada celda de estrategia de BTC (M1: 10, M2: 4), comparar contra el buy_and_hold de la MISMA ventana: pasa si Sharpe > B&H Y max_drawdown < B&H Y media > 0 Y mediana_en_posicion > 0, en calibración Y verificación. Tabla completa en el veredicto (celda × ventana × las 4 condiciones). ETH: misma tabla, rotulada robustez.

- [ ] **Step 4: SOLO si alguna celda pasó — correr M3 y M4 sobre la mejor celda (mayor Sharpe de verificación en BTC)**

```bash
# ejemplo si la ganadora fuera M2 con MA(50):
.venv/bin/python -m estudios.estudio_vol_overlay  --estudio ma --parametro 50 --variante long_flat --modo calibracion
.venv/bin/python -m estudios.estudio_vol_overlay  --estudio ma --parametro 50 --variante long_flat --modo verificacion --verificacion
.venv/bin/python -m estudios.estudio_instrumento  --estudio ma --parametro 50 --variante long_flat --modo calibracion
.venv/bin/python -m estudios.estudio_instrumento  --estudio ma --parametro 50 --variante long_flat --modo verificacion --verificacion
```

(Ajustar `--estudio/--parametro/--variante` a la celda ganadora real.) Si ninguna pasó, este step se omite y se documenta.

- [ ] **Step 5: Redactar `backtest_runs/estudios/veredicto-momentum-2026-07.md`**

Estructura fija: tabla por estudio (calibración vs verificación, todas las celdas de estrategia + buy-and-hold), evaluación textual contra el umbral pre-registrado COPIADO verbatim de la spec, conclusión PASA / NO PASA por celda, la regla de fragilidad M1-vs-M2 aplicada, y el cierre según el criterio de salida:
- si alguna celda pasa → "siguiente ciclo: diseño de señal (con M3/M4 respondidos: [números])";
- si ninguna pasa → aplicar el criterio de abandono firmado: "se congela la búsqueda de señal" — sin re-litigarlo, está firmado.

- [ ] **Step 6: Actualizar `docs/mejoras-propuestas.md`**

Agregar al final:

```markdown
**Ciclo momentum multi-día (2026-07, spec:
`docs/superpowers/specs/2026-07-15-ciclo-momentum-multidia-design.md`):**
estudios M1 (TSMOM) y M2 (P/MA) sobre velas diarias spot 2017-2026 con
verificación sellada 2024→presente; M3 (vol targeting) y M4 (funding drag)
condicionales. Veredicto:
`backtest_runs/estudios/veredicto-momentum-2026-07.md`.
[Completar con el resultado real y el paso siguiente.]
```

(El corchete se reemplaza por el resultado real.)

- [ ] **Step 7: Suite completa + commit final**

```bash
.venv/bin/python -m pytest -q
git add backtest_runs/estudios/ docs/mejoras-propuestas.md
git commit -m "Run momentum verification windows and record the cycle verdict"
```

---

## Notas de diseño para el ejecutor

1. **El candado de verificación es sagrado.** Nada corre `--modo verificacion` antes del checkpoint de la Task 7. Para probar flujos: calibración o fixtures sintéticos.
2. **Los umbrales pre-registrados no se ajustan al ver datos.** "Casi" = NO PASA. El criterio de abandono está firmado: si nada pasa, se congela — el veredicto no re-litiga.
3. **Sin editorializar en los reportes:** números y pre-registro. La interpretación va solo en el veredicto, contra el umbral verbatim.
4. **M3 y M4 se escriben y testean ANTES de conocer los resultados de M1/M2** (quedan congelados junto al resto). Solo su EJECUCIÓN es condicional.
5. **La aproximación de M4 (precio spot + funding de futuros) está pre-registrada** — no "mejorarla" agregando basis; se documenta y punto.
6. **Retornos forward superpuestos = solo descriptivos.** La adopción se evalúa únicamente sobre las celdas de estrategia (serie diaria, sin superposición).
7. **ETH nunca adopta ni veta** — sus tablas se rotulan robustez en reporte y veredicto.
