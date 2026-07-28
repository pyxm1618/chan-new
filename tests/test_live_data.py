from __future__ import annotations

from datetime import datetime, timedelta, timezone

from chan_monitor.binance import (
    BinanceKlineClient,
    BinanceKlineSnapshot,
    BinanceMarket,
    make_snapshot,
)
from chan_monitor.chart import build_raw_chart
from chan_monitor.chart_styles import DEFAULT_CHART_STYLE
from chan_monitor.data import demo_bars
from chan_monitor.engine import analyze_bars
from chan_monitor.live import analyze_snapshot, recommended_refresh_seconds
from chan_monitor.metadata import AnalysisMetadata
from chan_monitor.models import RawBar
from chan_monitor.segments import SegmentMode


def _bars(count: int, *, start: datetime, interval: str = "5m") -> list[RawBar]:
    step = timedelta(minutes=5)
    values: list[RawBar] = []
    close = 100.0
    for i in range(count):
        dt = start + i * step
        open_ = close
        close = open_ + (0.5 if i % 4 in {0, 1} else -0.35)
        values.append(
            RawBar(
                symbol="BTCUSDT",
                interval=interval,
                open_time=dt,
                close_time=dt + step - timedelta(milliseconds=1),
                open=open_,
                high=max(open_, close) + 0.2,
                low=min(open_, close) - 0.2,
                close=close,
                volume=10 + i,
                quote_volume=(10 + i) * close,
                trade_count=100 + i,
            )
        )
    return values


def test_refresh_policy_is_interval_aware() -> None:
    assert recommended_refresh_seconds("1m") == 10
    assert recommended_refresh_seconds("5m") == 30
    assert recommended_refresh_seconds("1h") == 120
    assert recommended_refresh_seconds("1d") == 600


def test_snapshot_keeps_5000_closed_plus_one_current_bar() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = _bars(5001, start=start)
    now = bars[-1].open_time + timedelta(minutes=2)
    snapshot = make_snapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=5000,
        existing_closed=bars[:-1],
        latest=bars[-3:],
        fetched_at=now,
    )
    assert len(snapshot.closed_bars) == 5000
    assert snapshot.current_bar == bars[-1]
    assert len(snapshot.all_bars) == 5001
    assert snapshot.gap_count == 0


def test_refresh_snapshot_replaces_current_and_rolls_closed_window() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _bars(5001, start=start)
    first_now = first[-1].open_time + timedelta(minutes=2)
    snapshot = make_snapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=5000,
        existing_closed=first[:-1],
        latest=first[-3:],
        fetched_at=first_now,
    )

    second = _bars(5002, start=start)
    second_now = second[-1].open_time + timedelta(minutes=2)

    class StubClient(BinanceKlineClient):
        def fetch_klines(self, *args, **kwargs):
            limit = kwargs.get("limit")
            if limit is None and len(args) >= 3:
                limit = args[2]
            return second[-int(limit or 3):]

    refreshed = StubClient().refresh_snapshot(snapshot, now=second_now)
    assert len(refreshed.closed_bars) == 5000
    assert refreshed.closed_bars[-1].open_time == second[-2].open_time
    assert refreshed.closed_bars[0].open_time == second[1].open_time
    assert refreshed.current_bar == second[-1]
    assert len({x.open_time for x in refreshed.all_bars}) == 5001


def test_current_bar_never_enters_confirmed_structure_layer() -> None:
    closed = demo_bars(600, symbol="BTCUSDT", interval="5m")
    last = closed[-1]
    step = timedelta(minutes=5)
    current = RawBar(
        symbol=last.symbol,
        interval=last.interval,
        open_time=last.open_time + step,
        close_time=last.close_time + step,
        open=last.close,
        high=last.close + 3,
        low=last.close - 1,
        close=last.close + 2,
        volume=123,
        quote_volume=123 * (last.close + 2),
        trade_count=999,
    )
    snapshot = BinanceKlineSnapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=600,
        closed_bars=tuple(closed),
        current_bar=current,
        fetched_at=current.open_time + timedelta(minutes=2),
    )
    expected = analyze_bars(closed)
    bundle = analyze_snapshot(
        snapshot,
        czsc_compatibility=True,
        min_bi_len=6,
        metadata=AnalysisMetadata.binance_rest(market="Binance 现货", source_url="https://data-api.binance.vision/api/v3/klines"),
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
    )
    assert bundle.confirmed.raw_bars == expected.raw_bars
    assert bundle.confirmed.strokes == expected.strokes
    assert bundle.confirmed.segments == expected.segments
    assert bundle.overlay.live_result.raw_bars[-1] == current
    assert bundle.overlay.provisional_strokes


def test_chart_draws_same_color_dashed_provisional_pen_and_segment() -> None:
    closed = demo_bars(1000, symbol="BTCUSDT", interval="5m")
    last = closed[-1]
    current = RawBar(
        symbol=last.symbol,
        interval=last.interval,
        open_time=last.open_time + timedelta(minutes=5),
        close_time=last.close_time + timedelta(minutes=5),
        open=last.close,
        high=last.close + 4,
        low=last.close - 2,
        close=last.close + 1,
        volume=10,
        quote_volume=10 * last.close,
        trade_count=10,
    )
    snapshot = BinanceKlineSnapshot(
        symbol="BTCUSDT", interval="5m", market=BinanceMarket.SPOT,
        history_limit=1000, closed_bars=tuple(closed), current_bar=current,
        fetched_at=current.open_time + timedelta(minutes=1),
    )
    bundle = analyze_snapshot(
        snapshot, czsc_compatibility=True, min_bi_len=6,
        metadata=AnalysisMetadata.binance_rest(market="Binance 现货", source_url="https://data-api.binance.vision/api/v3/klines"),
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
    )
    fig = build_raw_chart(bundle.confirmed, live_overlay=bundle.overlay)
    traces = {trace.name: trace for trace in fig.data}
    assert traces["笔"].line.color == DEFAULT_CHART_STYLE.stroke.color
    assert traces["未确认笔（同色虚线）"].line.color == DEFAULT_CHART_STYLE.stroke.color
    assert traces["未确认笔（同色虚线）"].line.dash == "dash"
    if bundle.overlay.provisional_segments:
        assert traces["未确认线段（同色虚线）"].line.color == DEFAULT_CHART_STYLE.segment.color
        assert traces["未确认线段（同色虚线）"].line.dash == "dash"


def test_5000_five_minute_bars_complete_full_structure_pipeline_deterministically() -> None:
    bars = demo_bars(5000, symbol="BTCUSDT", interval="5m")
    first = analyze_bars(bars)
    second = analyze_bars(bars)
    assert len(first.raw_bars) == 5000
    assert len(first.merged_bars) == 3721
    assert len(first.fractals) == 851
    assert len(first.strokes) == 338
    assert len(first.segments) == 61
    assert len(first.feature_elements) == 307
    assert len(first.feature_fractals) == 63
    assert len(first.unfinished_segment_strokes) == 3
    assert max(
        position
        for element in first.feature_elements
        for position in element.stroke_positions
    ) == len(first.strokes) - 1
    assert first.strokes == second.strokes
    assert first.segments == second.segments
    assert first.central_zones == second.central_zones
    assert first.segment_central_zones == second.segment_central_zones
    assert first.trading_points == second.trading_points


def _kline_row(open_time: datetime, *, close_after: timedelta, price: float) -> list[object]:
    open_ms = int(open_time.timestamp() * 1000)
    close_ms = int((open_time + close_after).timestamp() * 1000)
    return [
        open_ms,
        f"{price:.2f}",
        f"{price + 1:.2f}",
        f"{price - 1:.2f}",
        f"{price + 0.5:.2f}",
        "10",
        close_ms,
        "1000",
        100,
        "5",
        "500",
        "0",
    ]


def test_spot_pagination_returns_exact_5000_closed_bars_without_duplicates() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = [
        _kline_row(start + i * timedelta(minutes=5), close_after=timedelta(minutes=5) - timedelta(milliseconds=1), price=100 + i)
        for i in range(5000)
    ]
    # 模拟交易所返回的一根当前 K；close_time 放到未来，closed_only 必须排除它。
    rows.append(_kline_row(datetime(2099, 1, 1, tzinfo=timezone.utc), close_after=timedelta(minutes=5), price=9999))

    class PagingClient(BinanceKlineClient):
        calls: list[dict[str, object]]

        def __init__(self) -> None:
            super().__init__()
            self.calls = []

        def _get_with_retry(self, client, endpoint, params):
            self.calls.append(dict(params))
            end_time = int(params.get("endTime", 2**63 - 1))
            eligible = [row for row in rows if int(row[0]) <= end_time]
            return eligible[-int(params["limit"]):]

    client = PagingClient()
    bars = client.fetch_klines("BTCUSDT", "5m", 5000, market=BinanceMarket.SPOT, closed_only=True)
    assert len(bars) == 5000
    assert len(client.calls) == 6
    assert len({x.open_time for x in bars}) == 5000
    assert bars[0].open_time == start
    assert bars[-1].open_time == start + 4999 * timedelta(minutes=5)


def test_refresh_after_history_window_forces_clean_full_reload() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = _bars(31, start=start)
    snapshot = make_snapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=30,
        existing_closed=bars[:30],
        latest=bars[29:31],
        fetched_at=bars[-1].open_time + timedelta(minutes=2),
    )

    class ReloadClient(BinanceKlineClient):
        full_reload_called = False

        def fetch_snapshot(self, symbol, interval, *, history_limit, market, now=None):
            self.full_reload_called = True
            return snapshot

        def fetch_klines(self, *args, **kwargs):
            raise AssertionError("窗口超限时不应尝试把旧数据与增量尾部拼接")

    client = ReloadClient()
    refreshed = client.refresh_snapshot(snapshot, now=snapshot.fetched_at + timedelta(minutes=31 * 5))
    assert client.full_reload_called
    assert refreshed is snapshot


def test_confirmed_analysis_is_reused_until_a_bar_closes_then_recomputed() -> None:
    closed = demo_bars(400, symbol="BTCUSDT", interval="5m")
    last = closed[-1]
    step = timedelta(minutes=5)

    def make_current(delta: float) -> RawBar:
        return RawBar(
            symbol=last.symbol,
            interval=last.interval,
            open_time=last.open_time + step,
            close_time=last.close_time + step,
            open=last.close,
            high=last.close + max(delta, 0) + 1,
            low=last.close + min(delta, 0) - 1,
            close=last.close + delta,
            volume=20,
            quote_volume=20 * (last.close + delta),
            trade_count=200,
        )

    metadata = AnalysisMetadata.binance_rest(
        market="Binance 现货",
        source_url="https://data-api.binance.vision/api/v3/klines",
    )
    first_current = make_current(1)
    first_snapshot = BinanceKlineSnapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=400,
        closed_bars=tuple(closed),
        current_bar=first_current,
        fetched_at=first_current.open_time + timedelta(minutes=1),
    )
    first_bundle = analyze_snapshot(
        first_snapshot,
        czsc_compatibility=True,
        min_bi_len=6,
        metadata=metadata,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
    )

    second_current = make_current(3)
    second_snapshot = BinanceKlineSnapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=400,
        closed_bars=tuple(closed),
        current_bar=second_current,
        fetched_at=second_current.open_time + timedelta(minutes=2),
    )
    second_bundle = analyze_snapshot(
        second_snapshot,
        czsc_compatibility=True,
        min_bi_len=6,
        metadata=metadata,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        previous=first_bundle,
    )
    assert second_bundle.confirmed is first_bundle.confirmed
    assert second_bundle.overlay.live_result.raw_bars[-1] == second_current

    newly_closed = [*closed[1:], second_current]
    next_current = RawBar(
        symbol=last.symbol,
        interval=last.interval,
        open_time=second_current.open_time + step,
        close_time=second_current.close_time + step,
        open=second_current.close,
        high=second_current.close + 1,
        low=second_current.close - 1,
        close=second_current.close + 0.2,
        volume=5,
        quote_volume=5 * second_current.close,
        trade_count=50,
    )
    third_snapshot = BinanceKlineSnapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=400,
        closed_bars=tuple(newly_closed),
        current_bar=next_current,
        fetched_at=next_current.open_time + timedelta(minutes=1),
    )
    third_bundle = analyze_snapshot(
        third_snapshot,
        czsc_compatibility=True,
        min_bi_len=6,
        metadata=metadata,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        previous=second_bundle,
    )
    assert third_bundle.confirmed is not second_bundle.confirmed
    assert third_bundle.confirmed.raw_bars[-1] == second_current
    assert len(third_bundle.confirmed.raw_bars) == 400
