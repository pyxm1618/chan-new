from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from chan_monitor.bar_stream import validate_bar_stream
from chan_monitor.models import RawBar
from chan_monitor.trading_points import build_macd_anchor


def _bar(*, interval: str, open_time: datetime, close_time: datetime) -> RawBar:
    return RawBar(
        symbol="TESTUSDT",
        interval=interval,
        open_time=open_time,
        close_time=close_time,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1.0,
        quote_volume=1.0,
        trade_count=1,
    )


def test_single_bar_with_unsupported_interval_is_not_exactly_continuous() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bar = _bar(
        interval="90s",
        open_time=start,
        close_time=start + timedelta(seconds=90),
    )

    result = validate_bar_stream((bar,))

    assert result.continuous is False
    assert result.issue is not None
    assert "不支持" in result.issue


def test_macd_anchor_rejects_bar_closing_after_next_interval_opens() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    malformed = _bar(
        interval="5m",
        open_time=start,
        close_time=start + timedelta(minutes=6),
    )

    with pytest.raises(ValueError, match="连续|收盘时间"):
        build_macd_anchor((malformed,))
