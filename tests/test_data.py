from __future__ import annotations

from io import StringIO

from chan_monitor.data import bars_from_csv


def test_parse_seconds_timestamp_snapshot() -> None:
    csv = StringIO(
        "open_timestamp_utc,close_timestamp_utc,open,high,low,close,volume\n"
        "1502942400,1502945999,4261.48,4313.62,4261.32,4308.83,47.181009\n"
    )
    bars = bars_from_csv(csv, symbol="BTCUSDT", interval="1h")
    assert bars[0].open_time.isoformat() == "2017-08-17T04:00:00+00:00"
    assert bars[0].close_time.isoformat() == "2017-08-17T04:59:59+00:00"
    assert bars[0].high == 4313.62


def test_parse_headerless_microseconds_binance_vision() -> None:
    csv = StringIO(
        "1735689600000000,4.1507,4.1587,4.1506,4.1554,539.23,"
        "1735693199999999,2240.398609,13,401.82,1669.981213,0\n"
    )
    bars = bars_from_csv(csv, symbol="TESTUSDT", interval="1h")
    assert bars[0].open_time.isoformat() == "2025-01-01T00:00:00+00:00"
    assert bars[0].close_time.isoformat() == "2025-01-01T00:59:59.999999+00:00"
    assert bars[0].trade_count == 13
