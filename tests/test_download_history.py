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


def test_download_day_garbage_payload_is_failed_not_crash():
    status = download_day("2026-04-01", fetcher=lambda url: b"not a zip", sleep=lambda s: None)
    assert status == "failed"
