from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_monitor.chart import build_raw_chart
from chan_monitor.data import bars_from_csv
from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.models import (
    Fractal, FractalMark, MergedBar, RawBar, Segment, Stroke, StrokeDirection,
    TradingPointStatus, TradingPointType,
)
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.trading_point_reference import compare_trading_points_with_reference
from chan_monitor.trading_points import detect_trading_points, validate_trading_points


def _fractal(dt: datetime, mark: FractalMark, value: float, index: int) -> Fractal:
    high = value if mark is FractalMark.TOP else value + 0.5
    low = value - 0.5 if mark is FractalMark.TOP else value
    elements = []
    for j, offset in enumerate((-2, -1, 0)):
        t = dt + timedelta(minutes=offset)
        raw = RawBar("TESTUSDT", "1m", t, t + timedelta(minutes=1), low + 0.1, high, low, high - 0.1, 1, 1, 1)
        elements.append(MergedBar.from_raw(raw, id_=index * 100 + j))
    return Fractal("TESTUSDT", dt, mark, high, low, value, tuple(elements), index)


def _stroke(a: Fractal, b: Fractal, index: int, duration: int) -> Stroke:
    direction = StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
    bars = []
    steps = max(3, duration + 2)
    total = b.dt - a.dt
    for j in range(steps):
        ratio0, ratio1 = j / steps, (j + 1) / steps
        t = a.dt + total * ratio0
        open_ = a.value + (b.value - a.value) * ratio0
        close = a.value + (b.value - a.value) * ratio1
        wiggle = abs(b.value - a.value) * 0.01 + 0.02
        raw = RawBar(
            "TESTUSDT", "1m", t, t + timedelta(minutes=1), open_,
            max(open_, close) + wiggle, min(open_, close) - wiggle, close,
            1, 1, 1,
        )
        bars.append(MergedBar.from_raw(raw, id_=index * 1000 + j))
    return Stroke("TESTUSDT", a, b, (a, b), direction, tuple(bars), index)


def _segment_chain(values, *, start_bottom: bool, durations=None, origin=None) -> list[Segment]:
    origin = origin or datetime(2026, 1, 1, tzinfo=timezone.utc)
    durations = durations or [5] * (len(values) - 1)
    points = []
    for i, value in enumerate(values):
        bottom = (i % 2 == 0) if start_bottom else (i % 2 == 1)
        points.append(_fractal(origin + timedelta(hours=i * 20), FractalMark.BOTTOM if bottom else FractalMark.TOP, value, i))
    out = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        stroke = _stroke(a, b, i, durations[i])
        out.append(Segment("TESTUSDT", a, b, stroke.direction, (stroke,), i))
    return out


def _with_internal_strokes(segment: Segment, values, durations) -> Segment:
    assert values[0] == segment.start_value and values[-1] == segment.end_value
    points = []
    span = segment.end_dt - segment.start_dt
    for i, value in enumerate(values):
        dt = segment.start_dt + span * (i / (len(values) - 1))
        if segment.fx_a.mark is FractalMark.TOP:
            mark = FractalMark.TOP if i % 2 == 0 else FractalMark.BOTTOM
        else:
            mark = FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP
        points.append(_fractal(dt, mark, value, 1000 + segment.index * 100 + i))
    points[0] = segment.fx_a
    points[-1] = segment.fx_b
    strokes = tuple(_stroke(a, b, 1000 + segment.index * 100 + i, durations[i]) for i, (a, b) in enumerate(zip(points, points[1:])))
    return replace(segment, strokes=strokes)


def _raw_bars(segments):
    by_dt = {}
    for segment in segments:
        for stroke in segment.strokes:
            for merged in stroke.bars:
                for bar in merged.elements:
                    by_dt[bar.open_time] = bar
    return tuple(by_dt[k] for k in sorted(by_dt))


def _downtrend_with_b2() -> list[Segment]:
    values = [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 94]
    segments = _segment_chain(values, start_bottom=False, durations=[5,5,5,5,20,5,5,5,2,6,10])
    segments[10] = _with_internal_strokes(
        segments[10],
        [108, 104, 107, 105, 106.5, 100, 103, 101, 102, 94],
        [5,5,5,5,20,5,5,5,2],
    )
    return segments


def _uptrend_with_s2() -> list[Segment]:
    values = [60, 80, 65, 75, 68, 100, 88, 98, 90, 110, 92, 106]
    segments = _segment_chain(values, start_bottom=True, durations=[5,5,5,5,20,5,5,5,2,6,10], origin=datetime(2026, 3, 1, tzinfo=timezone.utc))
    segments[10] = _with_internal_strokes(
        segments[10],
        [92, 96, 93, 95, 93.5, 101, 98, 100, 99, 106],
        [5,5,5,5,20,5,5,5,2],
    )
    return segments


def _types(points):
    return {x.point_type for x in points}


def test_first_buy_and_second_buy_require_trend_and_sublevel_first_buy() -> None:
    segments = _downtrend_with_b2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = detect_trading_points(segments, zones, raw_bars=bars)
    assert TradingPointType.BUY1 in _types(result.points)
    assert TradingPointType.BUY2 in _types(result.points)
    b1 = next(x for x in result.points if x.point_type is TradingPointType.BUY1)
    b2 = next(x for x in result.points if x.point_type is TradingPointType.BUY2)
    assert b1.segment_index == 8 and b2.segment_index == 10
    assert b2.evidence_kind == "SUBLEVEL_BS1_ON_FIRST_RETRACE"
    assert not validate_trading_points(result.points, segments, zones, raw_bars=bars)


def test_first_sell_and_second_sell_require_trend_and_sublevel_first_sell() -> None:
    segments = _uptrend_with_s2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = detect_trading_points(segments, zones, raw_bars=bars)
    assert TradingPointType.SELL1 in _types(result.points)
    assert TradingPointType.SELL2 in _types(result.points)
    s1 = next(x for x in result.points if x.point_type is TradingPointType.SELL1)
    s2 = next(x for x in result.points if x.point_type is TradingPointType.SELL2)
    assert s1.segment_index == 8 and s2.segment_index == 10


def test_second_buy_rejected_without_sublevel_first_buy() -> None:
    segments = _downtrend_with_b2()
    segments[10] = replace(segments[10], strokes=(segments[10].strokes[0],))
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = detect_trading_points(segments, zones, raw_bars=bars)
    assert TradingPointType.BUY1 in _types(result.points)
    assert TradingPointType.BUY2 not in _types(result.points)
    assert any(x.point_type is TradingPointType.BUY2 and x.status is TradingPointStatus.REJECTED for x in result.candidates)


def test_third_buy_and_sell_accept_boundary_touch() -> None:
    buy_segments = _segment_chain([100,120,105,118,108,130,118], start_bottom=True)
    buy_zones = detect_segment_central_zones(buy_segments).zones
    buy = detect_trading_points(buy_segments, buy_zones, raw_bars=_raw_bars(buy_segments))
    assert TradingPointType.BUY3 in _types(buy.points)

    sell_segments = _segment_chain([130,110,125,112,122,100,112], start_bottom=False, origin=datetime(2026,5,1,tzinfo=timezone.utc))
    sell_zones = detect_segment_central_zones(sell_segments).zones
    sell = detect_trading_points(sell_segments, sell_zones, raw_bars=_raw_bars(sell_segments))
    assert TradingPointType.SELL3 in _types(sell.points)


def test_no_first_point_with_only_one_central_zone() -> None:
    segments = _segment_chain([120,100,115,95,108,90], start_bottom=False)
    zones = detect_segment_central_zones(segments).zones
    result = detect_trading_points(segments, zones, raw_bars=_raw_bars(segments))
    assert TradingPointType.BUY1 not in _types(result.points)
    assert TradingPointType.SELL1 not in _types(result.points)


def test_independent_reference_matches_deterministic_cases() -> None:
    for segments in (_downtrend_with_b2(), _uptrend_with_s2()):
        bars = _raw_bars(segments)
        zones = detect_segment_central_zones(segments).zones
        result = detect_trading_points(segments, zones, raw_bars=bars)
        comparison = compare_trading_points_with_reference(result.points, segments, zones, raw_bars=bars)
        assert comparison.all_match


def test_engine_batch_and_incremental_trading_points_match() -> None:
    bars = bars_from_csv(Path("artifacts/real/BTCUSDT_spot_1h_20191014-0600_20191104-0100_bars.csv"), symbol="BTCUSDT", interval="1h")[:220]
    batch = analyze_bars(bars, left_boundary_anchored=True)
    engine = FractalEngine(left_boundary_anchored=True)
    incremental = engine.extend(bars)
    assert [(x.point_type, x.dt, x.price, x.confirmed_at_dt) for x in batch.trading_points] == [(x.point_type, x.dt, x.price, x.confirmed_at_dt) for x in incremental.trading_points]


def test_real_snapshot_reference_and_chart_layer() -> None:
    bars = bars_from_csv(Path("artifacts/real/BTCUSDT_spot_1h_20191014-0600_20191104-0100_bars.csv"), symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, left_boundary_anchored=True)
    comparison = compare_trading_points_with_reference(result.trading_points, result.segments, result.segment_central_zones, raw_bars=result.raw_bars)
    assert comparison.all_match
    assert not validate_trading_points(result.trading_points, result.segments, result.segment_central_zones, raw_bars=result.raw_bars)
    fig = build_raw_chart(result, show_trading_points=True)
    names = {trace.name for trace in fig.data}
    for point in result.trading_points:
        assert f"{point.point_type.label}（{point.point_type.value}）" in names
