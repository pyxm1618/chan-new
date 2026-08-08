from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from chan_monitor.bar_stream import validate_bar_stream
from chan_monitor.models import RawBar
from chan_monitor.trading_point_reference import run_frozen_trading_point_reference
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


def test_macd_anchor_rejects_forged_next_open_cursor() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _bar(
        interval="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
    )
    anchor = build_macd_anchor((first,))
    forged_next = start + timedelta(hours=1)
    forged = replace(anchor, expected_next_open_time=forged_next)
    tail = _bar(
        interval="5m",
        open_time=forged_next,
        close_time=forged_next + timedelta(minutes=5),
    )

    with pytest.raises(ValueError, match="MacdAnchor.*周期|游标|不连续"):
        build_macd_anchor((tail,), anchor=forged)


def test_macd_anchor_rejects_close_time_past_its_next_open_cursor() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _bar(
        interval="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
    )
    anchor = build_macd_anchor((first,))
    forged_close = start + timedelta(minutes=6)
    forged = replace(anchor, asof=forged_close, last_close_time=forged_close)
    tail = _bar(
        interval="5m",
        open_time=start + timedelta(minutes=5),
        close_time=start + timedelta(minutes=10),
    )

    with pytest.raises(ValueError, match="MacdAnchor.*收盘|游标|周期"):
        build_macd_anchor((tail,), anchor=forged)


def test_reference_rejects_forged_next_open_cursor() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _bar(
        interval="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
    )
    anchor = build_macd_anchor((first,))
    forged_next = start + timedelta(hours=1)
    forged = replace(anchor, expected_next_open_time=forged_next)
    tail = _bar(
        interval="5m",
        open_time=forged_next,
        close_time=forged_next + timedelta(minutes=5),
    )

    with pytest.raises(ValueError, match="MacdAnchor.*周期|游标|不连续"):
        run_frozen_trading_point_reference(
            (), (), raw_bars=(tail,), macd_anchor=forged
        )


def test_reference_rejects_close_time_past_next_open_cursor() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _bar(
        interval="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
    )
    anchor = build_macd_anchor((first,))
    forged_close = start + timedelta(minutes=6)
    forged = replace(anchor, asof=forged_close, last_close_time=forged_close)
    tail = _bar(
        interval="5m",
        open_time=start + timedelta(minutes=5),
        close_time=start + timedelta(minutes=10),
    )

    with pytest.raises(ValueError, match="MacdAnchor.*收盘|游标|周期"):
        run_frozen_trading_point_reference(
            (), (), raw_bars=(tail,), macd_anchor=forged
        )
