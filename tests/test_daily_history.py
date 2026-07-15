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
