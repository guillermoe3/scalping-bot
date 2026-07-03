# Persistencia de corridas + histórico 3 meses — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Descargar 3 meses de aggTrades de BTC/USDT desde data.binance.vision a un cache compacto por día, y persistir cada corrida de backtest (meta + métricas + trades) con un `index.html` autocontenido para comparar corridas.

**Architecture:** Un módulo nuevo `trade_cache.py` define el cache compacto por día (gzip JSON de filas `[ts_ms, price, qty, is_sell]`). `download_history.py` (nuevo, CLI) baja los ZIP diarios oficiales y los convierte. `backtest_feed.py` aprende a leer el formato compacto primero, con fallback al cache viejo y a REST. `backtest_report.py` gana persistencia por corrida y `backtest_html.py` (nuevo) genera el comparador HTML leyendo solo los JSON chicos.

**Tech Stack:** Python 3 stdlib únicamente (urllib, zipfile, gzip, csv, json, subprocess). Sin dependencias nuevas. Tests con pytest.

**Spec:** `docs/superpowers/specs/2026-07-03-backtest-persistencia-historico-design.md`

## Global Constraints

- **Memoria:** nunca cargar más de un día de trades en RAM. El generador HTML lee SOLO `meta.json`/`summary.json`, jamás `trades.csv`.
- **Sin dependencias nuevas:** todo stdlib. `ccxt` ya existe y solo se usa en los caminos actuales.
- Formato compacto: fila = `[ts_ms:int, price:float, qty:float, is_sell:bool]`; archivo = `backtest_cache/BTCUSDT_aggtrades_YYYY-MM-DD.json.gz`; ordenado por `ts_ms`.
- `is_sell=True` ⇔ `isBuyerMaker=True` (el agresor fue vendedor). Equivale al `side=="sell"` de ccxt.
- Timestamps siempre normalizados a **milisegundos** (los dumps spot usan µs desde 2025-01-01; detectar por magnitud: `ts > 100_000_000_000_000` ⇒ µs).
- Carpeta de corridas: `backtest_runs/` (constante module-level `RUNS_DIR`, monkeypatchable en tests).
- Escrituras de cache/corridas atómicas: `.tmp` + `os.replace` (patrón existente en `backtest_feed._write_cache`).
- Los 222 tests existentes deben seguir verdes en cada commit.
- Commits frecuentes, mensajes en inglés como el historial existente, con `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `trade_cache.py` — cache compacto por día

**Files:**
- Create: `trade_cache.py`
- Test: `tests/test_trade_cache.py`

**Interfaces:**
- Produces (usado por Tasks 2, 3, 4):
  - `trade_cache.CACHE_DIR: str = "backtest_cache"` (module-level, tests lo monkeypatchean)
  - `day_str(ts_ms: int) -> str` — `'YYYY-MM-DD'` UTC
  - `day_path(day: str) -> str` — `f"{CACHE_DIR}/BTCUSDT_aggtrades_{day}.json.gz"`
  - `has_day(day: str) -> bool`
  - `read_day(day: str) -> Optional[List[list]]` — None si no existe
  - `write_day(day: str, rows: List[list]) -> None` — atómico, crea CACHE_DIR

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_trade_cache.py
import gzip
import json
import os

import pytest

import trade_cache


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_cache, "CACHE_DIR", str(tmp_path / "cache"))


def test_day_str_converts_ms_to_utc_date():
    # 2026-04-01 00:00:00 UTC = 1775001600000 ms
    assert trade_cache.day_str(1775001600000) == "2026-04-01"
    assert trade_cache.day_str(1775001600000 + 86_399_999) == "2026-04-01"


def test_day_path_uses_cache_dir_and_day():
    path = trade_cache.day_path("2026-04-01")
    assert path.endswith("BTCUSDT_aggtrades_2026-04-01.json.gz")
    assert path.startswith(trade_cache.CACHE_DIR)


def test_read_day_returns_none_when_missing():
    assert trade_cache.read_day("2026-04-01") is None
    assert not trade_cache.has_day("2026-04-01")


def test_write_then_read_roundtrip():
    rows = [[1775001600000, 50000.0, 0.5, True], [1775001600500, 50001.0, 0.2, False]]
    trade_cache.write_day("2026-04-01", rows)
    assert trade_cache.has_day("2026-04-01")
    assert trade_cache.read_day("2026-04-01") == rows


def test_write_day_is_gzip_json_on_disk():
    trade_cache.write_day("2026-04-01", [[1, 2.0, 3.0, True]])
    with gzip.open(trade_cache.day_path("2026-04-01"), "rt") as f:
        assert json.load(f) == [[1, 2.0, 3.0, True]]


def test_write_day_does_not_leave_tmp_file_on_failure(monkeypatch):
    def boom(src, dst):
        raise OSError("interrupted")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        trade_cache.write_day("2026-04-01", [[1, 2.0, 3.0, True]])
    leftovers = [p for p in os.listdir(trade_cache.CACHE_DIR) if p.endswith(".tmp")]
    assert leftovers == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trade_cache.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'trade_cache'`

- [ ] **Step 3: Implement `trade_cache.py`**

```python
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from typing import List, Optional

CACHE_DIR = "backtest_cache"


def day_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def day_path(day: str) -> str:
    return os.path.join(CACHE_DIR, f"BTCUSDT_aggtrades_{day}.json.gz")


def has_day(day: str) -> bool:
    return os.path.exists(day_path(day))


def read_day(day: str) -> Optional[List[list]]:
    path = day_path(day)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_day(day: str, rows: List[list]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = day_path(day)
    tmp_path = path + ".tmp"
    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_trade_cache.py -v`
Expected: 6 passed

- [ ] **Step 5: Run full suite and commit**

Run: `python -m pytest -q` — Expected: todo verde (222 + 6).

```bash
git add trade_cache.py tests/test_trade_cache.py
git commit -m "Add compact per-day gzip trade cache module"
```

---

### Task 2: `download_history.py` — parser del CSV de Binance y URL

**Files:**
- Create: `download_history.py` (parte 1: funciones puras)
- Test: `tests/test_download_history.py`

**Interfaces:**
- Consumes: nada (funciones puras).
- Produces (usado por Task 3):
  - `build_url(day: str) -> str`
  - `parse_agg_trades_csv(fileobj) -> List[list]` — filas compactas `[ts_ms, price, qty, is_sell]` ordenadas por ts

Formato del CSV diario de spot aggTrades (columnas, a veces con fila header y a veces sin):
`agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker, is_best_match`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_download_history.py
import io

from download_history import build_url, parse_agg_trades_csv


def test_build_url_for_a_day():
    assert build_url("2026-04-01") == (
        "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/"
        "BTCUSDT-aggTrades-2026-04-01.zip"
    )


def test_parse_skips_header_row():
    csv_text = (
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker,is_best_match\n"
        "1,50000.5,0.25,10,12,1774915200123,True,True\n"
    )
    rows = parse_agg_trades_csv(io.StringIO(csv_text))
    assert rows == [[1774915200123, 50000.5, 0.25, True]]


def test_parse_without_header_row():
    csv_text = "1,50000.5,0.25,10,12,1774915200123,False,True\n"
    rows = parse_agg_trades_csv(io.StringIO(csv_text))
    assert rows == [[1774915200123, 50000.5, 0.25, False]]


def test_parse_normalizes_microsecond_timestamps_to_ms():
    csv_text = "1,50000.5,0.25,10,12,1774915200123456,true,true\n"
    rows = parse_agg_trades_csv(io.StringIO(csv_text))
    assert rows[0][0] == 1774915200123


def test_parse_accepts_lowercase_booleans():
    csv_text = "1,50000.5,0.25,10,12,1774915200123,true,true\n"
    assert parse_agg_trades_csv(io.StringIO(csv_text))[0][3] is True


def test_parse_sorts_rows_by_timestamp():
    csv_text = (
        "2,50001.0,0.1,13,13,1774915200500,False,True\n"
        "1,50000.5,0.25,10,12,1774915200123,True,True\n"
    )
    rows = parse_agg_trades_csv(io.StringIO(csv_text))
    assert [r[0] for r in rows] == [1774915200123, 1774915200500]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_download_history.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'download_history'`

- [ ] **Step 3: Implement las funciones puras**

```python
# download_history.py
from __future__ import annotations

import csv
from typing import List

BASE_URL = "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT"
_MICROSECOND_THRESHOLD = 100_000_000_000_000  # ts mayores que esto vienen en µs


def build_url(day: str) -> str:
    return f"{BASE_URL}/BTCUSDT-aggTrades-{day}.zip"


def parse_agg_trades_csv(fileobj) -> List[list]:
    """Convierte el CSV diario de aggTrades de Binance Vision a filas
    compactas [ts_ms, price, qty, is_sell]. Tolera fila de header
    (algunos dumps la traen) y timestamps en µs (dumps spot desde
    2025-01-01)."""
    rows: List[list] = []
    for rec in csv.reader(fileobj):
        if not rec:
            continue
        try:
            price = float(rec[1])
        except (ValueError, IndexError):
            continue  # fila de header u otra basura
        qty = float(rec[2])
        ts = int(rec[5])
        if ts > _MICROSECOND_THRESHOLD:
            ts //= 1000
        is_sell = rec[6].strip().lower() == "true"
        rows.append([ts, price, qty, is_sell])
    rows.sort(key=lambda r: r[0])
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_download_history.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add download_history.py tests/test_download_history.py
git commit -m "Add Binance Vision aggTrades CSV parser and URL builder"
```

---

### Task 3: `download_history.py` — loop de descarga y CLI

**Files:**
- Modify: `download_history.py` (agregar descarga + main)
- Test: `tests/test_download_history.py` (agregar tests)

**Interfaces:**
- Consumes: `trade_cache.has_day/write_day` (Task 1), `build_url`/`parse_agg_trades_csv` (Task 2).
- Produces:
  - `download_day(day: str, fetcher=None, sleep=time.sleep) -> str` — retorna `"downloaded" | "cached" | "missing" | "failed"`
  - `main(argv=None, fetcher=None) -> int` — CLI `--start YYYY-MM-DD --end YYYY-MM-DD` (fin exclusivo); exit 0 si no hubo `failed`, 1 si hubo
  - `fetcher(url: str) -> bytes` inyectable; el default usa urllib. Un 404 se señala lanzando `DayNotAvailable`.

- [ ] **Step 1: Write the failing tests (append al archivo de tests)**

```python
# append a tests/test_download_history.py
import io as _io
import zipfile

import pytest

import trade_cache
from download_history import DayNotAvailable, download_day, main


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_cache, "CACHE_DIR", str(tmp_path / "cache"))


def _zip_bytes(csv_text: str) -> bytes:
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BTCUSDT-aggTrades-2026-04-01.csv", csv_text)
    return buf.getvalue()


GOOD_ZIP = _zip_bytes("1,50000.5,0.25,10,12,1774915200123,True,True\n")


def test_download_day_writes_compact_cache():
    status = download_day("2026-04-01", fetcher=lambda url: GOOD_ZIP)
    assert status == "downloaded"
    assert trade_cache.read_day("2026-04-01") == [[1774915200123, 50000.5, 0.25, True]]


def test_download_day_skips_existing_file():
    calls = []
    trade_cache.write_day("2026-04-01", [[1, 2.0, 3.0, True]])
    status = download_day("2026-04-01", fetcher=lambda url: calls.append(url))
    assert status == "cached"
    assert calls == []


def test_download_day_reports_missing_on_404():
    def fetcher(url):
        raise DayNotAvailable(url)
    assert download_day("2026-04-01", fetcher=fetcher) == "missing"


def test_download_day_retries_then_fails(monkeypatch):
    attempts = []
    def fetcher(url):
        attempts.append(url)
        raise OSError("network down")
    status = download_day("2026-04-01", fetcher=fetcher, sleep=lambda s: None)
    assert status == "failed"
    assert len(attempts) == 3


def test_download_day_retry_then_success():
    attempts = []
    def fetcher(url):
        attempts.append(url)
        if len(attempts) < 2:
            raise OSError("flaky")
        return GOOD_ZIP
    status = download_day("2026-04-01", fetcher=fetcher, sleep=lambda s: None)
    assert status == "downloaded"


def test_main_iterates_days_and_returns_zero(capsys):
    fetched = []
    def fetcher(url):
        fetched.append(url)
        return GOOD_ZIP
    rc = main(["--start", "2026-04-01", "--end", "2026-04-03"], fetcher=fetcher)
    assert rc == 0
    assert len(fetched) == 2  # end exclusivo
    out = capsys.readouterr().out
    assert "downloaded: 2" in out


def test_main_returns_one_when_a_day_fails(monkeypatch):
    monkeypatch.setattr("download_history.time.sleep", lambda s: None)
    def fetcher(url):
        raise OSError("down")
    rc = main(["--start", "2026-04-01", "--end", "2026-04-02"], fetcher=fetcher)
    assert rc == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_download_history.py -v`
Expected: los tests nuevos FAIL con `ImportError: cannot import name 'DayNotAvailable'`

- [ ] **Step 3: Implement descarga + CLI (append a download_history.py)**

```python
# append a download_history.py
import argparse
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

import trade_cache

_MAX_ATTEMPTS = 3


class DayNotAvailable(Exception):
    """El ZIP del día no existe en Binance Vision (HTTP 404)."""


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "scalping-bot-backtest"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise DayNotAvailable(url) from exc
        raise


def download_day(day: str, fetcher=None, sleep=time.sleep) -> str:
    """Baja, convierte y cachea un día. Procesa de a un día por vez para
    mantener acotada la memoria (lección del OOM: nunca más de un día de
    trades en RAM)."""
    if trade_cache.has_day(day):
        return "cached"
    fetch = fetcher if fetcher is not None else _http_get

    payload = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            payload = fetch(build_url(day))
            break
        except DayNotAvailable:
            return "missing"
        except Exception:
            if attempt < _MAX_ATTEMPTS - 1:
                sleep(2 ** attempt)
    if payload is None:
        return "failed"

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            rows = parse_agg_trades_csv(io.TextIOWrapper(f, encoding="utf-8", newline=""))
    trade_cache.write_day(day, rows)
    return "downloaded"


def _iter_days(start: str, end: str):
    cursor = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    stop = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    while cursor < stop:
        yield cursor.strftime("%Y-%m-%d")
        cursor += timedelta(days=1)


def main(argv=None, fetcher=None) -> int:
    parser = argparse.ArgumentParser(description="Download daily BTCUSDT aggTrades dumps from data.binance.vision into the compact backtest cache.")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    args = parser.parse_args(argv)

    counts = {"downloaded": 0, "cached": 0, "missing": 0, "failed": 0}
    for day in _iter_days(args.start, args.end):
        status = download_day(day, fetcher=fetcher)
        counts[status] += 1
        print(f"{day}: {status}")
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_download_history.py -v`
Expected: 13 passed

- [ ] **Step 5: Run full suite and commit**

Run: `python -m pytest -q` — Expected: todo verde.

```bash
git add download_history.py tests/test_download_history.py
git commit -m "Add resumable daily downloader CLI for Binance Vision aggTrades"
```

---

### Task 4: `backtest_feed.py` — lectura compact-first y pre-check de días faltantes

**Files:**
- Modify: `backtest_feed.py`
- Test: `tests/test_backtest_feed.py` (agregar tests)

**Interfaces:**
- Consumes: `trade_cache.read_day/has_day/day_str` (Task 1).
- Produces:
  - `fetch_trades(...)` (firma sin cambios) resuelve: compacto → JSON viejo por rango exacto → REST con warning a stderr.
  - `find_missing_days(start_ms: int, end_ms: int) -> List[str]` — días sin cache compacto NI JSON viejo del chunk exacto.
  - `BacktestFeed` gana `self._strict_cache: bool` = True solo cuando NO se inyectó exchange (uso real). En modo estricto, `replay()` corta con `ValueError` si faltan >2 días, listando los días y el comando de descarga. Con exchange inyectado (todos los tests existentes) el comportamiento actual no cambia.

- [ ] **Step 1: Write the failing tests (append a tests/test_backtest_feed.py)**

```python
# append a tests/test_backtest_feed.py — reutiliza _FakeExchange y el fixture
# _isolate_cache_dir existente; ese fixture debe ademas monkeypatchear
# trade_cache.CACHE_DIR (ver Step 3a).
import pytest

import trade_cache
from backtest_feed import BacktestFeed, find_missing_days
from state import MarketState

DAY_MS = 24 * 60 * 60 * 1000
DAY0 = 1775001600000  # 2026-04-01 00:00 UTC


def test_fetch_trades_prefers_compact_cache_over_exchange():
    trade_cache.write_day("2026-04-01", [[DAY0 + 1000, 50000.0, 0.5, True]])
    exchange = _FakeExchange(trades=[])
    result = fetch_trades(exchange, "BTC/USDT", DAY0, DAY0 + DAY_MS)
    assert exchange.fetch_trades_calls == 0
    assert result == [{"timestamp": DAY0 + 1000, "price": 50000.0, "amount": 0.5, "side": "sell"}]


def test_fetch_trades_compact_filters_to_requested_range():
    trade_cache.write_day("2026-04-01", [
        [DAY0 + 1000, 50000.0, 0.5, True],
        [DAY0 + 7_200_000, 50001.0, 0.1, False],
    ])
    result = fetch_trades(None, "BTC/USDT", DAY0, DAY0 + 3_600_000)
    assert len(result) == 1


def test_fetch_trades_falls_back_to_rest_with_warning(capsys):
    trades = [{"timestamp": DAY0 + 1, "price": 1.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(trades=trades)
    result = fetch_trades(exchange, "BTC/USDT", DAY0, DAY0 + 5000)
    assert exchange.fetch_trades_calls >= 1
    assert "download_history.py" in capsys.readouterr().err


def test_find_missing_days_reports_uncached_days():
    trade_cache.write_day("2026-04-02", [[DAY0 + DAY_MS + 1, 1.0, 1.0, False]])
    missing = find_missing_days(DAY0, DAY0 + 3 * DAY_MS)
    assert missing == ["2026-04-01", "2026-04-03"]


@pytest.mark.asyncio
async def test_replay_strict_raises_when_many_days_missing():
    feed = BacktestFeed.__new__(BacktestFeed)  # sin __init__: no crear exchange real
    feed._strict_cache = True
    with pytest.raises(ValueError) as exc:
        await feed.replay(DAY0, DAY0 + 4 * DAY_MS)
    assert "2026-04-01" in str(exc.value)
    assert "download_history.py" in str(exc.value)


def test_injected_exchange_disables_strict_cache():
    feed = BacktestFeed(MarketState(), exchange=_FakeExchange())
    assert feed._strict_cache is False
```

Nota: si el proyecto no usa `pytest-asyncio`, mirar cómo los tests async existentes de `tests/test_backtest_feed.py` corren corrutinas (probablemente `asyncio.run(...)` inline) y usar el mismo patrón en vez del marker.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest_feed.py -v`
Expected: los nuevos FAIL (`ImportError: cannot import name 'find_missing_days'`)

- [ ] **Step 3a: Actualizar el fixture de aislamiento existente**

En `tests/test_backtest_feed.py` (y en `tests/test_backtest.py`, que tiene el mismo fixture), extender `_isolate_cache_dir` para cubrir ambos módulos:

```python
@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("backtest_feed.CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("trade_cache.CACHE_DIR", str(tmp_path / "cache"))
```

- [ ] **Step 3b: Implement en `backtest_feed.py`**

Agregar `import sys` e `import trade_cache` arriba. Reemplazar el comienzo de `fetch_trades` y agregar helpers:

```python
def _single_day_key(start_ms: int, end_ms: int) -> Optional[str]:
    """Si [start_ms, end_ms) cae dentro de un mismo día UTC, retorna su
    'YYYY-MM-DD'; si cruza medianoche retorna None (el replay ya viene
    chunked por día, así que el caso normal es un solo día)."""
    day_start = (start_ms // DAY_MS) * DAY_MS
    if end_ms > day_start + DAY_MS:
        return None
    return trade_cache.day_str(start_ms)


def _compact_to_ccxt(rows: List[list], start_ms: int, end_ms: int) -> List[dict]:
    return [
        {"timestamp": ts, "price": price, "amount": qty, "side": "sell" if is_sell else "buy"}
        for ts, price, qty, is_sell in rows
        if start_ms <= ts < end_ms
    ]


def find_missing_days(start_ms: int, end_ms: int) -> List[str]:
    missing: List[str] = []
    for chunk_start, chunk_end in _day_chunks(start_ms, end_ms):
        day = trade_cache.day_str(chunk_start)
        if trade_cache.has_day(day):
            continue
        if os.path.exists(_cache_path("BTC/USDT", "trades", chunk_start, chunk_end)):
            continue
        missing.append(day)
    return missing


def fetch_trades(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[dict]:
    """Returns ccxt-normalized trade dicts covering [start_ms, end_ms)."""
    if use_cache:
        day = _single_day_key(start_ms, end_ms)
        if day is not None:
            rows = trade_cache.read_day(day)
            if rows is not None:
                return _compact_to_ccxt(rows, start_ms, end_ms)

    path = _cache_path(symbol, "trades", start_ms, end_ms)
    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached
        print(
            f"[backtest] sin cache compacto para {trade_cache.day_str(start_ms)}; "
            f"bajando por REST (lento). Sugerido: python download_history.py "
            f"--start {trade_cache.day_str(start_ms)} --end <dia siguiente al ultimo>",
            file=sys.stderr,
        )
    # ... el resto del cuerpo actual (loop REST + filtro + _write_cache) queda igual
```

En `BacktestFeed.__init__`, antes de resolver el default:

```python
        self._strict_cache = exchange is None
        self._exchange = exchange if exchange is not None else _build_exchange()
```

En `BacktestFeed.replay`, al comienzo:

```python
    async def replay(self, start_ms: int, end_ms: int) -> None:
        if self._strict_cache:
            missing = find_missing_days(start_ms, end_ms)
            if len(missing) > 2:
                first, last = missing[0], missing[-1]
                raise ValueError(
                    f"Faltan {len(missing)} dias de trades en cache: {', '.join(missing)}. "
                    f"Correr: python download_history.py --start {first} --end {last} "
                    f"(--end es exclusivo: usar el dia siguiente a {last})"
                )
        for chunk_start, chunk_end in _day_chunks(start_ms, end_ms):
            await self._replay_chunk(chunk_start, chunk_end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest_feed.py tests/test_backtest.py -v`
Expected: todos passed (los viejos siguen verdes: usan exchange inyectado ⇒ no estricto, y sin cache compacto caen al camino REST actual).

- [ ] **Step 5: Run full suite and commit**

Run: `python -m pytest -q` — Expected: todo verde.

```bash
git add backtest_feed.py tests/test_backtest_feed.py tests/test_backtest.py
git commit -m "Read compact day cache first in backtest feed with strict missing-day check"
```

---

### Task 5: `backtest_report.py` — downsample de equity y persistencia por corrida

**Files:**
- Modify: `backtest_report.py`
- Test: `tests/test_backtest_report.py` (agregar tests)

**Interfaces:**
- Consumes: `compute_summary`, `write_trade_log_csv` (existentes).
- Produces (usado por Tasks 6 y 7):
  - `downsample_equity(nets: List[float], max_points: int = 500) -> List[list]` — puntos `[indice_trade, equity_acumulado]`, 1-based tras el primer trade; conserva primero y último; `[]` si no hay trades
  - `git_commit_info() -> dict` — `{"commit": str, "dirty": bool}`; `{"commit": "unknown", "dirty": False}` si git falla
  - `make_run_dir_name(now_dt: datetime, label: Optional[str]) -> str` — `YYYY-MM-DD_HH-MM-SS` + `_<label-saneado>` si hay label (label saneado: lowercase, solo `[a-z0-9_-]`, resto → `-`)
  - `write_run(base_dir: str, dir_name: str, meta: dict, summary: dict, equity_curve: List[list], trade_records: List[dict]) -> str` — crea `base_dir/dir_name/` con `meta.json`, `summary.json` (= `{"metrics": summary, "equity_curve": [...], "final_equity": float}`) y `trades.csv`; retorna la ruta del dir

- [ ] **Step 1: Write the failing tests (append a tests/test_backtest_report.py)**

```python
# append a tests/test_backtest_report.py
import json
import os
from datetime import datetime, timezone

from backtest_report import (
    downsample_equity,
    git_commit_info,
    make_run_dir_name,
    write_run,
)


def test_downsample_equity_empty_and_single():
    assert downsample_equity([]) == []
    assert downsample_equity([5.0]) == [[1, 5.0]]


def test_downsample_equity_accumulates():
    assert downsample_equity([1.0, -2.0, 3.0]) == [[1, 1.0], [2, -1.0], [3, 2.0]]


def test_downsample_equity_caps_points_and_keeps_endpoints():
    nets = [1.0] * 2000
    points = downsample_equity(nets, max_points=500)
    assert len(points) <= 500
    assert points[0] == [1, 1.0]
    assert points[-1] == [2000, 2000.0]


def test_git_commit_info_shape():
    info = git_commit_info()
    assert set(info) == {"commit", "dirty"}
    assert isinstance(info["commit"], str) and isinstance(info["dirty"], bool)


def test_make_run_dir_name_sanitizes_label():
    dt = datetime(2026, 7, 3, 15, 30, 45, tzinfo=timezone.utc)
    assert make_run_dir_name(dt, None) == "2026-07-03_15-30-45"
    assert make_run_dir_name(dt, "Sin CVD/v2!") == "2026-07-03_15-30-45_sin-cvd-v2-"


def test_write_run_creates_the_three_files(tmp_path):
    meta = {"start": "2026-04-01", "label": None}
    summary = {"total_trades": 1, "win_rate": 1.0, "total_net_pnl": 5.0,
               "profit_factor": float("inf"), "max_drawdown": 0.0,
               "max_consecutive_losses": 0}
    run_dir = write_run(str(tmp_path), "2026-07-03_15-30-45", meta, summary, [[1, 5.0]], [])
    assert json.load(open(os.path.join(run_dir, "meta.json")))["start"] == "2026-04-01"
    data = json.load(open(os.path.join(run_dir, "summary.json")))
    assert data["equity_curve"] == [[1, 5.0]]
    assert data["final_equity"] == 5.0
    assert data["metrics"]["total_trades"] == 1
    assert os.path.exists(os.path.join(run_dir, "trades.csv"))
```

Nota: `profit_factor` puede ser `float("inf")`, que `json.dump` serializa como `Infinity` (no-JSON estricto pero legible por `json.load`); serializarlo como el string `"inf"` en `summary.json` para que el HTML lo muestre bien — convertir en `write_run` con `_jsonable()` (ver implementación).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest_report.py -v`
Expected: nuevos FAIL con ImportError

- [ ] **Step 3: Implement (append a backtest_report.py)**

```python
# append a backtest_report.py
import json
import math
import os
import re
import subprocess
from datetime import datetime
from typing import List, Optional


def downsample_equity(nets: List[float], max_points: int = 500) -> List[list]:
    points: List[list] = []
    equity = 0.0
    for i, n in enumerate(nets, start=1):
        equity += n
        points.append([i, equity])
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    sampled = [points[round(k * step)] for k in range(max_points - 1)]
    sampled.append(points[-1])
    return sampled


def git_commit_info() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip() != ""
        return {"commit": commit, "dirty": dirty}
    except Exception:
        return {"commit": "unknown", "dirty": False}


def make_run_dir_name(now_dt: datetime, label: Optional[str]) -> str:
    name = now_dt.strftime("%Y-%m-%d_%H-%M-%S")
    if label:
        name += "_" + re.sub(r"[^a-z0-9_-]", "-", label.lower())
    return name


def _jsonable(value):
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return value


def write_run(base_dir: str, dir_name: str, meta: dict, summary: dict,
              equity_curve: List[list], trade_records: List[dict]) -> str:
    run_dir = os.path.join(base_dir, dir_name)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    payload = {
        "metrics": {k: _jsonable(v) for k, v in summary.items()},
        "equity_curve": equity_curve,
        "final_equity": equity_curve[-1][1] if equity_curve else 0.0,
    }
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(payload, f, indent=2)
    write_trade_log_csv(trade_records, os.path.join(run_dir, "trades.csv"))
    return run_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest_report.py -v`
Expected: todos passed

- [ ] **Step 5: Run full suite and commit**

```bash
python -m pytest -q
git add backtest_report.py tests/test_backtest_report.py
git commit -m "Add per-run persistence with downsampled equity curve"
```

---

### Task 6: `backtest_html.py` — comparador HTML autocontenido

**Files:**
- Create: `backtest_html.py`
- Test: `tests/test_backtest_html.py`

**Interfaces:**
- Consumes: la estructura de carpetas de `write_run` (Task 5): `<base>/<run>/meta.json` + `summary.json`.
- Produces (usado por Task 7):
  - `collect_runs(base_dir: str) -> tuple` — `(runs, corrupt)`: `runs` = lista de `{"name", "meta", "summary"}` orden alfabético inverso (más nuevo primero); `corrupt` = nombres de subdirs con JSON faltante/ilegible
  - `render_index(runs: list, corrupt: list) -> str` — documento HTML completo autocontenido
  - `write_index(base_dir: str) -> str` — escribe `<base>/index.html`, retorna la ruta

**IMPORTANTE para el implementador:** antes de escribir el código del sparkline/tabla, cargar el skill `dataviz` (Skill tool) y aplicar su guía de color y forma al HTML. El código de abajo es la línea base funcional; dataviz puede mejorar colores/espaciado pero la estructura y los tests mandan. **Nunca leer `trades.csv` acá** — solo los dos JSON chicos por corrida.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backtest_html.py
import json
import os

from backtest_html import collect_runs, render_index, write_index


def _make_run(base, name, pnl=10.0, corrupt=False):
    d = os.path.join(base, name)
    os.makedirs(d)
    if corrupt:
        open(os.path.join(d, "meta.json"), "w").write("{not json")
        return
    json.dump({"start": "2026-04-01", "end": "2026-07-01", "label": "base",
               "git_commit": "abc1234", "created_utc": "2026-07-03T15:30:45Z"},
              open(os.path.join(d, "meta.json"), "w"))
    json.dump({"metrics": {"total_trades": 3, "win_rate": 0.66, "total_net_pnl": pnl,
                           "profit_factor": 2.0, "max_drawdown": 1.0,
                           "max_consecutive_losses": 1},
               "equity_curve": [[1, 4.0], [2, -1.0], [3, pnl]],
               "final_equity": pnl},
              open(os.path.join(d, "summary.json"), "w"))


def test_collect_runs_empty_dir(tmp_path):
    runs, corrupt = collect_runs(str(tmp_path))
    assert runs == [] and corrupt == []


def test_collect_runs_reads_runs_and_flags_corrupt(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    _make_run(str(tmp_path), "2026-07-02_10-00-00")
    _make_run(str(tmp_path), "2026-07-03_10-00-00", corrupt=True)
    runs, corrupt = collect_runs(str(tmp_path))
    assert [r["name"] for r in runs] == ["2026-07-02_10-00-00", "2026-07-01_10-00-00"]
    assert corrupt == ["2026-07-03_10-00-00"]


def test_render_index_contains_rows_sparkline_and_no_external_refs(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    runs, corrupt = collect_runs(str(tmp_path))
    html = render_index(runs, corrupt)
    assert "2026-07-01_10-00-00" in html
    assert "<svg" in html and "polyline" in html
    assert "http://" not in html and "https://" not in html  # autocontenido
    assert "<script src" not in html and "<link" not in html


def test_render_index_zero_runs_renders_page():
    html = render_index([], [])
    assert "<table" in html or "Sin corridas" in html


def test_render_index_escapes_labels(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    runs, _ = collect_runs(str(tmp_path))
    runs[0]["meta"]["label"] = "<script>alert(1)</script>"
    assert "<script>alert(1)" not in render_index(runs, [])


def test_write_index_creates_file(tmp_path):
    _make_run(str(tmp_path), "2026-07-01_10-00-00")
    path = write_index(str(tmp_path))
    assert path.endswith("index.html")
    assert os.path.exists(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest_html.py -v`
Expected: FAIL con `ModuleNotFoundError`

- [ ] **Step 3: Cargar el skill dataviz y luego implementar `backtest_html.py`**

Baseline (ajustar estética según dataviz, manteniendo autocontención y tests):

```python
from __future__ import annotations

import html
import json
import os
from typing import List, Tuple

_COLS = [
    ("name", "Corrida"), ("label", "Etiqueta"), ("range", "Rango"),
    ("commit", "Commit"), ("total_trades", "Trades"), ("win_rate", "Win rate"),
    ("total_net_pnl", "P&L neto"), ("profit_factor", "Profit factor"),
    ("max_drawdown", "Max DD"), ("max_consecutive_losses", "Racha perd."),
    ("equity", "Equity"),
]


def collect_runs(base_dir: str) -> Tuple[List[dict], List[str]]:
    runs: List[dict] = []
    corrupt: List[str] = []
    if not os.path.isdir(base_dir):
        return runs, corrupt
    for name in sorted(os.listdir(base_dir), reverse=True):
        run_dir = os.path.join(base_dir, name)
        if not os.path.isdir(run_dir):
            continue
        try:
            with open(os.path.join(run_dir, "meta.json")) as f:
                meta = json.load(f)
            with open(os.path.join(run_dir, "summary.json")) as f:
                summary = json.load(f)
            runs.append({"name": name, "meta": meta, "summary": summary})
        except (OSError, ValueError):
            corrupt.append(name)
    return runs, corrupt


def _sparkline_svg(points: List[list], width: int = 140, height: int = 36) -> str:
    if not points:
        return f'<svg width="{width}" height="{height}"></svg>'
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    y_min, y_max = min(ys + [0.0]), max(ys + [0.0])
    x_span = (xs[-1] - xs[0]) or 1
    y_span = (y_max - y_min) or 1
    coords = " ".join(
        f"{(x - xs[0]) / x_span * width:.1f},{height - (y - y_min) / y_span * height:.1f}"
        for x, y in points
    )
    color = "#2e7d32" if ys[-1] >= 0 else "#c62828"
    zero_y = height - (0.0 - y_min) / y_span * height
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<line x1="0" y1="{zero_y:.1f}" x2="{width}" y2="{zero_y:.1f}" stroke="#ccc" stroke-width="1"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{coords}"/></svg>'
    )


def _fmt(value, spec: str = "") -> str:
    if value is None or value == "inf":
        return "∞" if value == "inf" else "—"
    try:
        return format(value, spec) if spec else str(value)
    except (TypeError, ValueError):
        return html.escape(str(value))


def _row(run: dict) -> str:
    meta, m = run["meta"], run["summary"]["metrics"]
    cells = [
        html.escape(run["name"]),
        html.escape(str(meta.get("label") or "—")),
        html.escape(f"{meta.get('start', '?')} → {meta.get('end', '?')}"),
        html.escape(str(meta.get("git_commit", "?"))),
        _fmt(m.get("total_trades")),
        _fmt(m.get("win_rate"), ".1%"),
        _fmt(m.get("total_net_pnl"), "+.2f"),
        _fmt(m.get("profit_factor"), ".2f"),
        _fmt(m.get("max_drawdown"), ".2f"),
        _fmt(m.get("max_consecutive_losses")),
        _sparkline_svg(run["summary"].get("equity_curve", [])),
    ]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


_STYLE = """body{font-family:system-ui,sans-serif;margin:2rem;color:#222}
table{border-collapse:collapse;width:100%}th,td{padding:.45rem .6rem;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap}
th{cursor:pointer;background:#f5f5f5;position:sticky;top:0}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
.warn{color:#b26a00}.wrap{overflow-x:auto}"""

_SORT_JS = """document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
const tb=th.closest('table').querySelector('tbody');const dir=th.dataset.dir=th.dataset.dir==='a'?'d':'a';
[...tb.rows].sort((x,y)=>{const a=x.cells[i].innerText,b=y.cells[i].innerText;
const na=parseFloat(a.replace(/[^\\d.-]/g,'')),nb=parseFloat(b.replace(/[^\\d.-]/g,''));
const c=(isNaN(na)||isNaN(nb))?a.localeCompare(b):na-nb;return dir==='a'?c:-c;})
.forEach(r=>tb.appendChild(r));}));"""


def render_index(runs: List[dict], corrupt: List[str]) -> str:
    headers = "".join(f"<th>{html.escape(title)}</th>" for _, title in _COLS)
    body = "".join(_row(r) for r in runs)
    warn = ""
    if corrupt:
        names = ", ".join(html.escape(c) for c in corrupt)
        warn = f'<p class="warn">Corridas ilegibles (ignoradas): {names}</p>'
    empty = "<p>Sin corridas todavía. Corré un backtest para ver resultados acá.</p>" if not runs else ""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Backtest runs — scalping-bot</title><style>{_STYLE}</style></head><body>
<h1>Corridas de backtest</h1>{warn}{empty}
<div class="wrap"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>
<p>Click en un encabezado ordena por esa columna. Detalle completo de cada corrida en su carpeta (trades.csv).</p>
<script>{_SORT_JS}</script></body></html>"""


def write_index(base_dir: str) -> str:
    runs, corrupt = collect_runs(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, "index.html")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render_index(runs, corrupt))
    os.replace(tmp, path)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest_html.py -v`
Expected: 6 passed

- [ ] **Step 5: Verificación visual + full suite + commit**

Generar una muestra y abrirla NO es posible sin browser; verificar al menos que el HTML de 2 corridas de fixture se escribe y contiene 2 `<tr>` de datos (los tests ya lo cubren). Luego:

```bash
python -m pytest -q
git add backtest_html.py tests/test_backtest_html.py
git commit -m "Add self-contained HTML run comparator built from run summaries"
```

---

### Task 7: `backtest.py` — wiring: `--label`, carpeta por corrida, index y `--rebuild-index`

**Files:**
- Modify: `backtest.py`
- Modify: `backtest_report.py` (CLI `--rebuild-index` al final)
- Modify: `.gitignore`
- Test: `tests/test_backtest.py` (agregar/ajustar)

**Interfaces:**
- Consumes: `write_run`, `make_run_dir_name`, `downsample_equity`, `git_commit_info` (Task 5); `write_index` (Task 6).
- Produces:
  - `backtest.RUNS_DIR: str = "backtest_runs"` (module-level, monkeypatchable)
  - `backtest.py --label mi-etiqueta` opcional
  - `python backtest_report.py --rebuild-index` regenera el index a mano
  - `run_backtest` sigue retornando el dict `summary` (tests existentes intactos)

- [ ] **Step 1: Write the failing tests (append a tests/test_backtest.py)**

```python
# append a tests/test_backtest.py
import json
import os


@pytest.fixture(autouse=True)
def _isolate_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("backtest.RUNS_DIR", str(tmp_path / "runs"))


def test_run_creates_run_dir_with_meta_summary_and_index(tmp_path):
    # reutilizar el armado de klines/trades/exchange del test e2e existente
    # (test_main_runs_end_to_end_and_writes_a_csv) — copiar su setup aquí.
    klines_1m, trades = _sample_day()  # ver nota abajo
    exchange = _FakeExchange(klines_1m, trades)
    rc = backtest.main(
        ["--start", START, "--end", END, "--out", str(tmp_path / "t.csv"), "--label", "Mi Prueba"],
        exchange=exchange,
    )
    assert rc == 0
    import backtest as bt
    run_dirs = [d for d in os.listdir(bt.RUNS_DIR) if os.path.isdir(os.path.join(bt.RUNS_DIR, d))]
    assert len(run_dirs) == 1
    assert run_dirs[0].endswith("_mi-prueba")
    run = os.path.join(bt.RUNS_DIR, run_dirs[0])
    meta = json.load(open(os.path.join(run, "meta.json")))
    assert meta["label"] == "Mi Prueba"
    assert "git_commit" in meta and "start" in meta
    assert os.path.exists(os.path.join(run, "summary.json"))
    assert os.path.exists(os.path.join(run, "trades.csv"))
    assert os.path.exists(os.path.join(bt.RUNS_DIR, "index.html"))
```

Nota: `_sample_day()`, `START`, `END` no existen — extraer el setup del test e2e existente `test_main_runs_end_to_end_and_writes_a_csv` a un helper compartido en el mismo archivo y reutilizarlo en ambos tests (DRY; no duplicar los datos sintéticos).

Además, test del rebuild:

```python
def test_backtest_report_rebuild_index_cli(tmp_path, monkeypatch, capsys):
    import backtest_report
    rc = backtest_report.main_cli(["--rebuild-index", "--runs-dir", str(tmp_path)])
    assert rc == 0
    assert os.path.exists(os.path.join(str(tmp_path), "index.html"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: nuevos FAIL (`AttributeError: module 'backtest' has no attribute 'RUNS_DIR'`, `main_cli` inexistente)

- [ ] **Step 3: Implement**

En `backtest.py`:

```python
# imports nuevos
import time
from backtest_report import compute_summary, downsample_equity, git_commit_info, make_run_dir_name, write_run, write_trade_log_csv
from backtest_html import write_index

RUNS_DIR = "backtest_runs"
```

En `parse_args`: `parser.add_argument("--label", default=None, help="Etiqueta corta para identificar la corrida en el comparador")`.

En `run_backtest`, después de `write_trade_log_csv(...)`:

```python
    closes = [r for r in trade_records if not r["is_partial"]]
    equity_curve = downsample_equity([r["total_trade_net"] for r in closes])
    git_info = git_commit_info()
    meta = {
        "start": args.start, "end": args.end, "balance": args.balance,
        "spread_pct": args.spread_pct, "label": args.label, "out": args.out,
        "git_commit": git_info["commit"], "git_dirty": git_info["dirty"],
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round(time.monotonic() - t0, 1),
        "format_version": 1,
    }
    dir_name = make_run_dir_name(datetime.now(timezone.utc), args.label)
    run_dir = write_run(RUNS_DIR, dir_name, meta, summary, equity_curve, trade_records)
    index_path = write_index(RUNS_DIR)
    print(f"Run guardada en: {run_dir}")
    print(f"Comparador: {index_path}")
    return summary
```

con `t0 = time.monotonic()` capturado al inicio de `run_backtest`.

En `backtest_report.py`, al final:

```python
def main_cli(argv=None) -> int:
    import argparse
    from backtest_html import write_index
    parser = argparse.ArgumentParser(description="Backtest report utilities.")
    parser.add_argument("--rebuild-index", action="store_true")
    parser.add_argument("--runs-dir", default="backtest_runs")
    args = parser.parse_args(argv)
    if args.rebuild_index:
        print(write_index(args.runs_dir))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main_cli())
```

En `.gitignore` agregar la línea `backtest_runs/` y también `backtest_trades.csv` (el CSV suelto de `--out`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: todos passed, incluidos los e2e viejos (que ahora también crean run dir, aislado por el fixture autouse).

- [ ] **Step 5: Run full suite and commit**

```bash
python -m pytest -q
git add backtest.py backtest_report.py tests/test_backtest.py .gitignore
git commit -m "Persist every backtest run and regenerate the HTML comparator"
```

---

### Task 8: Migración de datos reales, equivalencia y descarga de los 3 meses

Esta task corre contra datos reales (red + disco), no es de código. Ejecutar en orden y **reportar cada resultado; si la equivalencia no da idéntica, NO borrar nada y reportar la diferencia**.

**Files:**
- Modify: `docs/mejoras-propuestas.md` (marcar estado de P0-6/P0-7 al final)
- Delete (solo tras equivalencia OK): los 3 `backtest_cache/BTCUSDT_trades_*.json`

- [ ] **Step 1: Identificar los días del cache viejo**

```bash
python3 - <<'EOF'
from datetime import datetime, timezone
for a, b in [(1780963200000, 1781049600000), (1781049600000, 1781136000000), (1781136000000, 1781222400000)]:
    print(datetime.fromtimestamp(a/1000, tz=timezone.utc).date(), "→", datetime.fromtimestamp(b/1000, tz=timezone.utc).date())
EOF
```

Anotar los 3 días (consecutivos). Llamarlos D1, D2, D3 (D4 = día siguiente a D3).

- [ ] **Step 2: Backtest baseline con el cache viejo (ANTES de descargar)**

```bash
python backtest.py --start D1 --end D4 --label baseline-cache-viejo | tee /tmp/claude-1000/-home-guille-dev-scalping-bot/*/scratchpad/baseline.txt
```

(usar el scratchpad real de la sesión). Expected: corre sin red (cache viejo por rango exacto), imprime resumen y guarda la run.

- [ ] **Step 3: Descargar esos mismos días en formato compacto**

```bash
python download_history.py --start D1 --end D4
```

Expected: `D1: downloaded`, `D2: downloaded`, `D3: downloaded`, `downloaded: 3, cached: 0, missing: 0, failed: 0`.

- [ ] **Step 4: Backtest con cache compacto y comparación**

```bash
python backtest.py --start D1 --end D4 --label equivalencia-compacto | tee .../equivalencia.txt
diff <(grep -E "Trades|Win rate|P&L|Profit|drawdown|consecutive" .../baseline.txt) \
     <(grep -E "Trades|Win rate|P&L|Profit|drawdown|consecutive" .../equivalencia.txt)
```

Expected: diff vacío (mismas métricas). Si difiere: STOP, no borrar nada, reportar ambas salidas al usuario.

- [ ] **Step 5: Borrar los JSON viejos de trades (solo si Step 4 dio idéntico)**

```bash
rm backtest_cache/BTCUSDT_trades_1780963200000_1781049600000.json \
   backtest_cache/BTCUSDT_trades_1781049600000_1781136000000.json \
   backtest_cache/BTCUSDT_trades_1781136000000_1781222400000.json
python backtest.py --start D1 --end D4 --label post-borrado  # debe seguir corriendo (compacto)
```

- [ ] **Step 6: Descargar los 3 meses (larga, en background, reanudable)**

```bash
python download_history.py --start 2026-04-01 --end 2026-07-01
```

Correr en background (Bash `run_in_background: true`), monitorear el avance. Expected final: `downloaded: 90` (menos los 3 ya `cached`), `failed: 0`. Si algún día da `missing` (gap de Binance), anotarlo y seguir.

- [ ] **Step 7: Smoke del backtest de 3 meses**

```bash
python backtest.py --start 2026-04-01 --end 2026-07-01 --label tres-meses-base
```

Correr en background; puede tardar. Expected: termina sin OOM, imprime resumen, crea run dir e index.html con la corrida visible. Vigilar RSS del proceso si es posible (`ps -o rss= -p <pid>`, debe mantenerse acotado, no crecer día a día).

- [ ] **Step 8: Actualizar docs y commit final**

En `docs/mejoras-propuestas.md`, sección de estado (línea ~174), actualizar: P0-6 y P0-7 implementados (citar este plan y el spec), quedan P0-3 y P0-8.

```bash
git add docs/mejoras-propuestas.md
git commit -m "Record P0-6 and P0-7 as done in the improvement docs"
```

---

## Self-Review (hecho al escribir el plan)

- Cobertura del spec: descarga (T2-T3), formato compacto (T1), lector con fallback y pre-check (T4), persistencia por corrida con `--label` (T5, T7), HTML autocontenido con sparklines y tolerancia a corruptos (T6), `--rebuild-index` (T7), migración/limpieza/equivalencia (T8), `.gitignore` (T7), memoria un-día-por-vez (T1/T3/T4, constraint global). Criterios de éxito 1-4 cubiertos por T8 y las suites.
- Sin placeholders: todo step con código o comando concreto.
- Consistencia de firmas revisada entre tasks (trade_cache, download_history, backtest_report, backtest_html, backtest).
