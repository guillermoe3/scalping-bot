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
