import klines_history
from klines_history import build_url, parse_klines_csv


def test_build_url():
    assert build_url("ETHUSDT", "2023-05") == (
        "https://data.binance.vision/data/futures/um/monthly/"
        "klines/ETHUSDT/15m/ETHUSDT-15m-2023-05.zip"
    )


def test_parse_klines_csv_extracts_compact_row_and_skips_header():
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore",
        "1577836800000,7189.43,7190.52,7177.00,7182.44,246.092,1577837699999,1767430.35,2135,113.680,816482.71,0",
    ]
    rows = parse_klines_csv(iter(lines))
    assert rows == [[1577836800000, 7189.43, 7190.52, 7177.0, 7182.44, 246.092, 113.68]]


def test_parse_klines_csv_converts_microsecond_open_time():
    rows = parse_klines_csv(iter([
        "1577836800000000,1,2,0.5,1.5,10,1577837699999999,15,3,4,6,0",
    ]))
    assert rows[0][0] == 1577836800000


def test_month_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_history, "CACHE_DIR", str(tmp_path))
    rows = [[1577836800000, 1.0, 2.0, 0.5, 1.5, 10.0, 4.0]]
    klines_history._write_month("BTCUSDT", "2020-01", rows)
    assert klines_history.read_month("BTCUSDT", "2020-01") == rows
    assert klines_history.read_month("BTCUSDT", "2020-02") is None
