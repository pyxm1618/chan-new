from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Sequence

import httpx

from .data import interval_seconds
from .models import RawBar


class BinanceMarket(str, Enum):
    SPOT = "spot"
    USD_M_FUTURES = "usdm"

    @property
    def label(self) -> str:
        return "现货" if self is BinanceMarket.SPOT else "U 本位合约"


@dataclass(frozen=True, slots=True)
class BinanceKlineSnapshot:
    """一份可持续增量刷新的 Binance K 线快照。

    ``closed_bars`` 始终只包含已收盘 K 线，并保留精确的历史深度；
    ``current_bar`` 是唯一一根可能尚未收盘的实时 K 线。结构确认只使用
    ``closed_bars``，实时虚线候选才使用 ``current_bar``。
    """

    symbol: str
    interval: str
    market: BinanceMarket
    history_limit: int
    closed_bars: tuple[RawBar, ...]
    current_bar: RawBar | None
    fetched_at: datetime

    @property
    def all_bars(self) -> tuple[RawBar, ...]:
        if self.current_bar is None:
            return self.closed_bars
        if self.closed_bars and self.current_bar.open_time <= self.closed_bars[-1].open_time:
            return self.closed_bars
        return (*self.closed_bars, self.current_bar)

    @property
    def signature(self) -> tuple:
        last_closed = self.closed_bars[-1] if self.closed_bars else None
        current = self.current_bar
        return (
            len(self.closed_bars),
            _bar_signature(last_closed),
            _bar_signature(current),
        )

    @property
    def closed_signature(self) -> tuple:
        if not self.closed_bars:
            return (0, None, None)
        return (
            len(self.closed_bars),
            self.closed_bars[0].open_time,
            _bar_signature(self.closed_bars[-1]),
        )

    @property
    def gap_count(self) -> int:
        return count_interval_gaps(self.closed_bars, self.interval)


@dataclass(slots=True)
class BinanceKlineClient:
    timeout_seconds: float = 15.0
    max_retries: int = 3
    spot_base_url: str = "https://data-api.binance.vision"
    futures_base_url: str = "https://fapi.binance.com"

    def source_url(self, market: BinanceMarket) -> str:
        endpoint = "/api/v3/klines" if market is BinanceMarket.SPOT else "/fapi/v1/klines"
        base_url = self.spot_base_url if market is BinanceMarket.SPOT else self.futures_base_url
        return f"{base_url}{endpoint}"

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        *,
        market: BinanceMarket = BinanceMarket.SPOT,
        closed_only: bool = True,
        end_time: datetime | None = None,
    ) -> list[RawBar]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit 必须在 1 到 5000 之间")
        symbol = symbol.upper().strip()
        if not symbol:
            raise ValueError("symbol 不能为空")

        request_count = limit + 1 if closed_only else limit
        max_batch = 1000 if market is BinanceMarket.SPOT else 1500
        endpoint = "/api/v3/klines" if market is BinanceMarket.SPOT else "/fapi/v1/klines"
        base_url = self.spot_base_url if market is BinanceMarket.SPOT else self.futures_base_url

        cursor_end = _to_milliseconds(end_time) if end_time else None
        rows: list[list[Any]] = []
        remaining = request_count
        with httpx.Client(base_url=base_url, timeout=self.timeout_seconds) as client:
            while remaining > 0:
                batch_limit = min(max_batch, remaining)
                params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": batch_limit}
                if cursor_end is not None:
                    params["endTime"] = cursor_end
                batch = self._get_with_retry(client, endpoint, params)
                if not isinstance(batch, list):
                    raise RuntimeError(f"Binance 返回格式异常：{batch!r}")
                if not batch:
                    break
                rows = batch + rows
                remaining -= len(batch)
                first_open_ms = int(batch[0][0])
                next_cursor = first_open_ms - 1
                if cursor_end is not None and next_cursor >= cursor_end:
                    break
                cursor_end = next_cursor
                if len(batch) < batch_limit:
                    break

        unique_rows = {int(row[0]): row for row in rows}
        ordered = [unique_rows[key] for key in sorted(unique_rows)]
        bars = [parse_kline_row(symbol, interval, row) for row in ordered]
        if closed_only:
            now = datetime.now(timezone.utc)
            bars = [bar for bar in bars if bar.close_time <= now]
        return bars[-limit:]

    def fetch_snapshot(
        self,
        symbol: str,
        interval: str,
        *,
        history_limit: int = 5000,
        market: BinanceMarket = BinanceMarket.SPOT,
        now: datetime | None = None,
    ) -> BinanceKlineSnapshot:
        """首次加载：精确获取 N 根已收盘 K，再附加一根实时 K。"""
        if history_limit < 30 or history_limit > 5000:
            raise ValueError("history_limit 必须在 30 到 5000 之间")
        explicit_now = _ensure_utc(now) if now is not None else None
        closed = self.fetch_klines(
            symbol,
            interval,
            history_limit,
            market=market,
            closed_only=True,
        )
        latest = self.fetch_klines(
            symbol,
            interval,
            3,
            market=market,
            closed_only=False,
        )
        # 以两次请求均完成后的时间统一划分“已收盘 / 当前 K”，避免恰逢收盘边界时
        # 首次快照少一根历史 K。测试传入 now 时仍严格使用指定时间。
        fetched_at = explicit_now or datetime.now(timezone.utc)
        return make_snapshot(
            symbol=symbol,
            interval=interval,
            market=market,
            history_limit=history_limit,
            existing_closed=closed,
            latest=latest,
            fetched_at=fetched_at,
        )

    def refresh_snapshot(
        self,
        snapshot: BinanceKlineSnapshot,
        *,
        now: datetime | None = None,
    ) -> BinanceKlineSnapshot:
        """增量刷新，仅抓取可能新增或修订的尾部 K 线。

        根据离上次尾 K 的间隔动态扩大请求窗口。即使页面暂停数小时，恢复后也会
        自动补齐缺失 K；只有缺口超过完整历史窗口时才会退化为重新拉取 5000 根。
        """
        fetched_at = _ensure_utc(now or datetime.now(timezone.utc))
        last = snapshot.all_bars[-1] if snapshot.all_bars else None
        if last is None:
            return self.fetch_snapshot(
                snapshot.symbol,
                snapshot.interval,
                history_limit=snapshot.history_limit,
                market=snapshot.market,
                now=fetched_at,
            )

        seconds = interval_seconds(snapshot.interval)
        elapsed = max(0.0, (fetched_at - last.open_time).total_seconds())
        needed = max(3, int(math.floor(elapsed / seconds)) + 4)
        if needed >= snapshot.history_limit:
            # 页面暂停超过完整历史窗口时，旧尾部与新数据之间可能出现无法可靠补齐的缺口；
            # 直接重新拉取精确的 N 根已收盘 K + 当前 K，避免把一根陈旧 K 拼在新窗口前端。
            return self.fetch_snapshot(
                snapshot.symbol,
                snapshot.interval,
                history_limit=snapshot.history_limit,
                market=snapshot.market,
                now=fetched_at,
            )
        latest = self.fetch_klines(
            snapshot.symbol,
            snapshot.interval,
            needed,
            market=snapshot.market,
            closed_only=False,
        )
        return make_snapshot(
            symbol=snapshot.symbol,
            interval=snapshot.interval,
            market=snapshot.market,
            history_limit=snapshot.history_limit,
            existing_closed=snapshot.closed_bars,
            latest=latest,
            fetched_at=fetched_at,
        )

    def _get_with_retry(self, client: httpx.Client, endpoint: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.get(endpoint, params=params)
                if response.status_code in {418, 429} or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"可重试的 Binance HTTP 状态：{response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                retry_after = 0.5 * (2**attempt)
                if isinstance(exc, httpx.HTTPStatusError):
                    header = exc.response.headers.get("Retry-After")
                    if header and header.isdigit():
                        retry_after = max(retry_after, float(header))
                time.sleep(retry_after)
        raise RuntimeError(f"获取 Binance K 线失败：{last_error}") from last_error


def make_snapshot(
    *,
    symbol: str,
    interval: str,
    market: BinanceMarket,
    history_limit: int,
    existing_closed: Sequence[RawBar],
    latest: Sequence[RawBar],
    fetched_at: datetime,
) -> BinanceKlineSnapshot:
    """把历史与尾部更新合并为无重复、严格排序的快照。"""
    fetched_at = _ensure_utc(fetched_at)
    merged = {bar.open_time: bar for bar in existing_closed}
    merged.update({bar.open_time: bar for bar in latest})
    ordered = [merged[key] for key in sorted(merged)]
    closed = [bar for bar in ordered if bar.close_time <= fetched_at]
    current_candidates = [bar for bar in ordered if bar.close_time > fetched_at]
    current = current_candidates[-1] if current_candidates else None
    closed = closed[-history_limit:]
    validate_kline_sequence(closed, interval=interval)
    if current is not None and closed and current.open_time <= closed[-1].open_time:
        current = None
    return BinanceKlineSnapshot(
        symbol=symbol.upper().strip(),
        interval=interval,
        market=market,
        history_limit=history_limit,
        closed_bars=tuple(closed),
        current_bar=current,
        fetched_at=fetched_at,
    )


def validate_kline_sequence(bars: Sequence[RawBar], *, interval: str) -> None:
    """校验排序、重复和 OHLC 周期口径；市场停牌造成的时间缺口不报错。"""
    previous: RawBar | None = None
    expected = interval_seconds(interval)
    for bar in bars:
        if bar.interval != interval:
            raise ValueError(f"K 线周期不一致：期望 {interval}，实际 {bar.interval}")
        if previous is not None:
            if bar.open_time <= previous.open_time:
                raise ValueError("K 线时间必须严格递增且不能重复")
            delta = (bar.open_time - previous.open_time).total_seconds()
            if delta < expected - 1e-6:
                raise ValueError("相邻 K 线时间间隔小于所选周期")
        previous = bar


def count_interval_gaps(bars: Sequence[RawBar], interval: str) -> int:
    expected = interval_seconds(interval)
    return sum(
        (b.open_time - a.open_time).total_seconds() > expected + 1e-6
        for a, b in zip(bars, bars[1:])
    )


def parse_kline_row(symbol: str, interval: str, row: list[Any]) -> RawBar:
    if len(row) < 11:
        raise ValueError(f"K 线数据至少需要 11 个字段，实际为 {len(row)}")
    return RawBar(
        symbol=symbol,
        interval=interval,
        open_time=_from_milliseconds(int(row[0])),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=_from_milliseconds(int(row[6])),
        quote_volume=float(row[7]),
        trade_count=int(row[8]),
    )


def _bar_signature(bar: RawBar | None) -> tuple | None:
    if bar is None:
        return None
    return (
        bar.open_time,
        bar.close_time,
        round(bar.open, 12),
        round(bar.high, 12),
        round(bar.low, 12),
        round(bar.close, 12),
        round(bar.volume, 12),
        bar.trade_count,
    )


def _from_milliseconds(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _to_milliseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("end_time 必须带时区")
    return int(value.timestamp() * 1000)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("时间必须带时区")
    return value.astimezone(timezone.utc)
