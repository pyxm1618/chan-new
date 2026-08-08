from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .models import RawBar

_INTERVAL_RE = re.compile(r"^(?P<count>[1-9]\d*)(?P<unit>[mhdwM])$")


@dataclass(frozen=True, slots=True)
class BarStreamValidation:
    symbol: str | None
    interval: str | None
    continuous: bool
    issue: str | None = None


def next_open_time(open_time: datetime, interval: str) -> datetime:
    """Return the next fixed-grid bar open time for a Binance-style interval."""
    match = _INTERVAL_RE.fullmatch(interval)
    if match is None:
        raise ValueError(f"不支持的 K 线周期：{interval}")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "m":
        return open_time + timedelta(minutes=count)
    if unit == "h":
        return open_time + timedelta(hours=count)
    if unit == "d":
        return open_time + timedelta(days=count)
    if unit == "w":
        return open_time + timedelta(weeks=count)

    # Calendar months are not a fixed timedelta. Keep the day when possible,
    # otherwise clamp to the last valid day of the destination month.
    month_index = open_time.year * 12 + (open_time.month - 1) + count
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    day = min(open_time.day, calendar.monthrange(year, month)[1])
    return open_time.replace(year=year, month=month, day=day)


def raw_bar_fingerprint(bar: RawBar) -> str:
    payload = "|".join(
        (
            bar.symbol,
            bar.interval,
            bar.open_time.isoformat(),
            bar.close_time.isoformat(),
            format(float(bar.open), ".17g"),
            format(float(bar.high), ".17g"),
            format(float(bar.low), ".17g"),
            format(float(bar.close), ".17g"),
            format(float(bar.volume), ".17g"),
            format(float(bar.quote_volume), ".17g"),
            str(int(bar.trade_count)),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_bar_stream(raw_bars: Sequence[RawBar]) -> BarStreamValidation:
    """Validate identity, order, uniqueness and fixed-grid continuity.

    The function is deliberately conservative. A stream with session gaps or
    missing bars is usable for charting, but it is not exact enough to recover
    an EMA/MACD state from a finite window without a market-calendar-aware
    cursor. In that case ``continuous`` is False rather than silently claiming
    exactness.
    """
    bars = tuple(raw_bars)
    if not bars:
        return BarStreamValidation(None, None, True, None)

    symbol = bars[0].symbol
    interval = bars[0].interval
    if any(bar.symbol != symbol for bar in bars):
        raise ValueError("MACD 输入 K 线包含多个品种")
    if any(bar.interval != interval for bar in bars):
        raise ValueError("MACD 输入 K 线包含多个周期")

    try:
        next_times = tuple(next_open_time(bar.open_time, interval) for bar in bars)
    except ValueError as exc:
        return BarStreamValidation(symbol, interval, False, str(exc))

    for bar, expected_next in zip(bars, next_times):
        if bar.close_time > expected_next:
            return BarStreamValidation(
                symbol,
                interval,
                False,
                (
                    "K 线收盘时间越过下一周期起点："
                    f"{bar.open_time.isoformat()} 的 close_time={bar.close_time.isoformat()}，"
                    f"下一根应从 {expected_next.isoformat()} 开始"
                ),
            )

    for (previous, current), expected in zip(zip(bars, bars[1:]), next_times):
        if current.open_time <= previous.open_time:
            raise ValueError("MACD 输入 K 线必须按 open_time 严格递增且不能重复")
        if current.open_time != expected:
            return BarStreamValidation(
                symbol,
                interval,
                False,
                (
                    "K 线序列不连续："
                    f"{previous.open_time.isoformat()} 后应为 {expected.isoformat()}，"
                    f"实际为 {current.open_time.isoformat()}"
                ),
            )
    return BarStreamValidation(symbol, interval, True, None)
