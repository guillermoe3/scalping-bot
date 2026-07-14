import gzip
import json

import pytest

import funding_history
from funding_history import build_url, parse_funding_csv


def test_build_url():
    assert build_url("BTCUSDT", "2020-01") == (
        "https://data.binance.vision/data/futures/um/monthly/"
        "fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-01.zip"
    )


def test_parse_funding_csv_skips_header_and_sorts():
    lines = [
        "calc_time,funding_interval_hours,last_funding_rate",
        "1577865600000,8,0.00010000",
        "1577836800000,8,-0.00025000",
    ]
    rows = parse_funding_csv(iter(lines))
    assert rows == [[1577836800000, -0.00025], [1577865600000, 0.0001]]


def test_parse_funding_csv_tolerates_microsecond_timestamps():
    rows = parse_funding_csv(iter(["1577836800000000,8,0.0001"]))
    assert rows == [[1577836800000, 0.0001]]


def test_download_range_merges_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(funding_history, "CACHE_DIR", str(tmp_path))
    payload_by_url = {}

    def fake_fetch(url):
        return payload_by_url[url]

    payload_by_url[build_url("BTCUSDT", "2020-01")] = _zip_with(
        "BTCUSDT-fundingRate-2020-01.csv",
        "1577836800000,8,0.0001\n1577865600000,8,0.0002\n",
    )
    counts = funding_history.download_range("BTCUSDT", "2020-01", "2020-02", fetcher=fake_fetch)
    assert counts["downloaded"] == 1
    assert funding_history.read_funding("BTCUSDT") == [
        [1577836800000, 0.0001], [1577865600000, 0.0002],
    ]
    # re-run: idempotent
    counts = funding_history.download_range("BTCUSDT", "2020-01", "2020-02", fetcher=fake_fetch)
    assert funding_history.read_funding("BTCUSDT") == [
        [1577836800000, 0.0001], [1577865600000, 0.0002],
    ]


def _zip_with(name: str, content: str) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()
