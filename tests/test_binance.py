from datetime import timezone

from chan_monitor.binance import parse_kline_row


def test_parse_binance_kline_row() -> None:
    row = [
        1499040000000,
        "0.01634790",
        "0.80000000",
        "0.01575800",
        "0.01577100",
        "148976.11427815",
        1499644799999,
        "2434.19055334",
        308,
        "1756.87402397",
        "28.46694368",
        "0",
    ]
    bar = parse_kline_row("BTCUSDT", "1m", row)
    assert bar.open_time.tzinfo == timezone.utc
    assert bar.high == 0.8
    assert bar.low == 0.015758
    assert bar.trade_count == 308
