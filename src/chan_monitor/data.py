from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .models import RawBar


OHLC_COLUMNS = {"open", "high", "low", "close"}
OPEN_TIME_COLUMNS = ("open_time", "open_timestamp_utc")
CLOSE_TIME_COLUMNS = ("close_time", "close_timestamp_utc")


def bars_from_csv(path_or_buffer, *, symbol: str, interval: str) -> list[RawBar]:
    """读取标准 CSV 或常见 Binance 历史快照格式。

    支持：
    - 标准格式：open_time / close_time 为可解析的时间；
    - Binance 镜像格式：open_timestamp_utc / close_timestamp_utc 为秒级 Unix 时间戳；
    - Binance Vision 原始格式：无表头的 12 列 kline CSV（毫秒或微秒时间戳）。
    """
    df = pd.read_csv(path_or_buffer)
    if not OHLC_COLUMNS.issubset(df.columns):
        # Binance Vision CSV 没有表头，pandas 会把第一行当成列名；重新按无表头读取。
        try:
            if hasattr(path_or_buffer, "seek"):
                path_or_buffer.seek(0)
            raw = pd.read_csv(path_or_buffer, header=None)
        except Exception as exc:  # pragma: no cover - 保留原始错误上下文
            missing = OHLC_COLUMNS - set(df.columns)
            raise ValueError(f"CSV 缺少字段：{', '.join(sorted(missing))}") from exc
        if raw.shape[1] < 9:
            missing = OHLC_COLUMNS - set(df.columns)
            raise ValueError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
        raw = raw.iloc[:, :12]
        raw.columns = [
            "open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote", "ignore",
        ][: raw.shape[1]]
        df = raw

    open_col = next((x for x in OPEN_TIME_COLUMNS if x in df.columns), None)
    if open_col is None:
        raise ValueError("CSV 缺少 open_time 或 open_timestamp_utc")
    close_col = next((x for x in CLOSE_TIME_COLUMNS if x in df.columns), None)

    open_times = _parse_time_series(df[open_col])
    if close_col:
        close_times = _parse_time_series(df[close_col])
    else:
        close_times = open_times + pd.to_timedelta(interval_seconds(interval), unit="s") - pd.Timedelta(milliseconds=1)

    bars: list[RawBar] = []
    for i, row in df.iterrows():
        bars.append(
            RawBar(
                symbol=symbol,
                interval=interval,
                open_time=open_times.iloc[i].to_pydatetime(),
                close_time=close_times.iloc[i].to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
                quote_volume=float(row.get("quote_volume", 0.0)),
                trade_count=int(row.get("trade_count", 0)),
            )
        )
    return bars


def demo_bars(count: int = 180, *, symbol: str = "DEMOUSDT", interval: str = "1h") -> list[RawBar]:
    """确定性的波形数据，刻意插入若干包含关系。仅用于测试。"""
    import math
    import random

    rng = random.Random(20260726)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars: list[RawBar] = []
    previous_close = 100.0
    step = timedelta(seconds=interval_seconds(interval))
    for i in range(count):
        center = 100 + 8 * math.sin(i / 8.0) + 3 * math.sin(i / 2.7)
        open_ = previous_close
        close = center + rng.uniform(-0.8, 0.8)
        high = max(open_, close) + rng.uniform(0.5, 1.8)
        low = min(open_, close) - rng.uniform(0.5, 1.8)
        if i in {20, 21, 52, 53, 54, 99, 130, 131} and bars:
            prev = bars[-1]
            high = prev.high - 0.15
            low = prev.low + 0.15
            open_ = min(max(open_, low), high)
            close = min(max(close, low), high)
        dt = start + i * step
        bars.append(
            RawBar(
                symbol=symbol,
                interval=interval,
                open_time=dt,
                close_time=dt + step - timedelta(milliseconds=1),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=100 + rng.random() * 50,
                quote_volume=(100 + rng.random() * 50) * close,
                trade_count=100 + i,
            )
        )
        previous_close = close
    return bars


def save_bars_csv(bars: list[RawBar], path: str | Path) -> None:
    pd.DataFrame(
        [
            {
                "open_time": x.open_time.isoformat(),
                "close_time": x.close_time.isoformat(),
                "open": x.open,
                "high": x.high,
                "low": x.low,
                "close": x.close,
                "volume": x.volume,
                "quote_volume": x.quote_volume,
                "trade_count": x.trade_count,
            }
            for x in bars
        ]
    ).to_csv(path, index=False)


def _parse_time_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="raise")
        max_abs = float(numeric.abs().max())
        # 秒约 1e9，毫秒约 1e12，微秒约 1e15。
        unit = "us" if max_abs >= 1e14 else "ms" if max_abs >= 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True)
    return pd.to_datetime(series, utc=True)


def interval_seconds(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    factors = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if unit == "M":
        return value * 30 * 86400
    if unit not in factors:
        raise ValueError(f"不支持的周期：{interval}")
    return value * factors[unit]
