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
    rows = [[1774915200000, 50000.0, 0.5, True], [1774915200500, 50001.0, 0.2, False]]
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
