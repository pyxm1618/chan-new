from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_monitor.chart import build_raw_chart
from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.models import (
    Fractal, FractalMark, MergedBar, RawBar, Segment, Stroke, StrokeDirection,
    TradingPointStatus, TradingPointType,
)
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.trading_point_reference import compare_trading_points_with_reference
from chan_monitor.trading_points import (
    _directional_macd_area,
    build_macd_anchor,
    detect_trading_points,
    validate_trading_points,
)


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
    for j in range(steps):
        ratio0, ratio1 = j / steps, (j + 1) / steps
        t = a.dt + timedelta(minutes=j)
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
    point_times = [origin]
    for duration in durations:
        point_times.append(point_times[-1] + timedelta(minutes=max(3, duration + 2)))
    points = []
    for i, (value, point_dt) in enumerate(zip(values, point_times)):
        bottom = (i % 2 == 0) if start_bottom else (i % 2 == 1)
        points.append(_fractal(point_dt, FractalMark.BOTTOM if bottom else FractalMark.TOP, value, i))
    out = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        stroke = _stroke(a, b, i, durations[i])
        out.append(Segment("TESTUSDT", a, b, stroke.direction, (stroke,), i))
    return out


def _with_internal_strokes(segment: Segment, values, durations) -> Segment:
    assert values[0] == segment.start_value and values[-1] == segment.end_value
    spans = [max(3, duration + 2) for duration in durations]
    available = int((segment.end_dt - segment.start_dt).total_seconds() // 60)
    assert sum(spans) <= available
    spans[-1] += available - sum(spans)
    effective_durations = [max(1, span - 2) for span in spans]
    times = [segment.start_dt]
    for span in spans:
        times.append(times[-1] + timedelta(minutes=span))
    points = []
    for i, (value, dt) in enumerate(zip(values, times)):
        if segment.fx_a.mark is FractalMark.TOP:
            mark = FractalMark.TOP if i % 2 == 0 else FractalMark.BOTTOM
        else:
            mark = FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP
        points.append(_fractal(dt, mark, value, 1000 + segment.index * 100 + i))
    points[0] = segment.fx_a
    points[-1] = segment.fx_b
    strokes = tuple(
        _stroke(a, b, 1000 + segment.index * 100 + i, effective_durations[i])
        for i, (a, b) in enumerate(zip(points, points[1:]))
    )
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
    # 两个线段中枢满足严格趋势关系：后 trend_GG=112 < 前 trend_DD=120。
    # 第 10 段为最终离开 C 并创出 80 新低；第 12 段首次回试不破 80，
    # 且其内部笔级别也形成严格一买。
    values = [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80, 95, 85]
    segments = _segment_chain(
        values,
        start_bottom=False,
        durations=[5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 25, 5, 87],
    )
    segments[10] = _with_internal_strokes(
        segments[10],
        [108, 98, 104, 100, 103, 90, 96, 92, 95, 80],
        [1] * 9,
    )
    segments[12] = _with_internal_strokes(
        segments[12],
        [95, 91.6666667, 94.1666667, 92.5, 93.6666667, 88.3333333,
         90.3333333, 88.6666667, 90, 86.6666667, 89.6666667, 85],
        [5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 2],
    )
    return segments


def _uptrend_with_s2() -> list[Segment]:
    values = [60, 80, 65, 75, 68, 100, 88, 98, 90, 110, 92, 120, 105, 115]
    segments = _segment_chain(
        values,
        start_bottom=True,
        durations=[5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 25, 5, 87],
        origin=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    segments[10] = _with_internal_strokes(
        segments[10],
        [92, 102, 96, 100, 97, 110, 104, 108, 105, 120],
        [1] * 9,
    )
    segments[12] = _with_internal_strokes(
        segments[12],
        [105, 108.3333333, 105.8333333, 107.5, 106.3333333, 111.6666667,
         109.6666667, 111.3333333, 110, 113.3333333, 110.3333333, 115],
        [5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 2],
    )
    return segments


def _core_separated_but_not_strict() -> list[Segment]:
    # 核心区间分离，但把离开段错误计入中枢波动范围时会产生歧义。
    # 这里最后 C 未创趋势新低，因此无论如何都不能输出正式一买。
    return _segment_chain(
        [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 94],
        start_bottom=False,
        durations=[5, 5, 5, 5, 20, 5, 5, 5, 2, 6, 10],
    )


def _commit_times(segments):
    return {x.fingerprint: max(x.end_dt, x.source_end) + timedelta(microseconds=1) for x in segments}


def _detect_trading_points(segments, zones, **kwargs):
    kwargs.setdefault("segment_commit_times", _commit_times(segments))
    return detect_trading_points(segments, zones, **kwargs)


def _types(points):
    return {x.point_type for x in points}




def test_public_api_requires_formal_segment_commit_evidence() -> None:
    segments = _downtrend_with_b2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=bars,
        macd_history_anchored=True,
    )

    assert result.points == ()
    assert result.trend_divergences == ()
    assert any(
        item.code == "FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING"
        for item in result.diagnostics
    )


def test_public_api_rejects_commit_time_before_segment_is_available() -> None:
    segments = _downtrend_with_b2()
    zones = detect_segment_central_zones(segments).zones
    invalid = _commit_times(segments)
    invalid[segments[-1].fingerprint] = segments[-1].start_dt

    import pytest

    with pytest.raises(ValueError, match="committed_at 早于结构可用时间"):
        detect_trading_points(
            segments,
            zones,
            raw_bars=_raw_bars(segments),
            segment_commit_times=invalid,
            macd_history_anchored=True,
        )


def test_macd_anchor_is_bound_to_symbol_interval_and_contiguous_cursor() -> None:
    segments = _downtrend_with_b2()
    bars = _raw_bars(segments)
    split = 40
    anchor = build_macd_anchor(bars[:split])

    import pytest

    wrong_symbol = tuple(replace(bar, symbol="OTHER") for bar in bars[split:])
    with pytest.raises(ValueError, match="品种不匹配"):
        detect_trading_points(
            segments,
            detect_segment_central_zones(segments).zones,
            raw_bars=wrong_symbol,
            segment_commit_times=_commit_times(segments),
            macd_anchor=anchor,
        )

    wrong_interval = tuple(replace(bar, interval="5m") for bar in bars[split:])
    with pytest.raises(ValueError, match="周期不匹配"):
        detect_trading_points(
            segments,
            detect_segment_central_zones(segments).zones,
            raw_bars=wrong_interval,
            segment_commit_times=_commit_times(segments),
            macd_anchor=anchor,
        )

    with pytest.raises(ValueError, match="不连续"):
        detect_trading_points(
            segments,
            detect_segment_central_zones(segments).zones,
            raw_bars=bars[split + 1 :],
            segment_commit_times=_commit_times(segments),
            macd_anchor=anchor,
        )

    gapped = bars[:split] + bars[split + 1 :]
    result = detect_trading_points(
        segments,
        detect_segment_central_zones(segments).zones,
        raw_bars=gapped,
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )
    assert not any(x.point_type is TradingPointType.BUY1 for x in result.points)
    assert any(x.code == "MACD_STREAM_NOT_EXACT" for x in result.diagnostics)


def test_public_api_rejects_segment_evidence_from_another_symbol() -> None:
    a = analyze_bars(
        demo_bars(500, symbol="AAA", interval="5m"),
        left_boundary_anchored=True,
    )
    b = analyze_bars(
        demo_bars(500, symbol="BBB", interval="5m"),
        left_boundary_anchored=True,
    )
    assert a.segments and len(a.segments) == len(b.segments)

    import pytest

    with pytest.raises(ValueError, match="品种/周期/几何指纹不匹配"):
        detect_trading_points(
            a.segments,
            a.segment_central_zones,
            raw_bars=a.raw_bars,
            segment_evidence=b.segment_evidence,
            strokes=a.resolved_strokes,
            macd_history_anchored=True,
        )


def test_first_buy_and_second_buy_require_trend_and_sublevel_first_buy() -> None:
    segments = _downtrend_with_b2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(segments, zones, raw_bars=bars, macd_history_anchored=True)
    assert TradingPointType.BUY1 in _types(result.points)
    assert TradingPointType.BUY2 in _types(result.points)
    b1 = next(x for x in result.points if x.point_type is TradingPointType.BUY1)
    b2 = next(x for x in result.points if x.point_type is TradingPointType.BUY2)
    assert b1.segment_index == 10 and b2.segment_index == 12
    assert b2.evidence_kind == "SUBLEVEL_BS1_ON_FIRST_RETRACE"
    assert not validate_trading_points(
        result.points,
        segments,
        zones,
        raw_bars=bars,
        segment_commit_times=_commit_times(segments),
    )


def test_first_sell_and_second_sell_require_trend_and_sublevel_first_sell() -> None:
    segments = _uptrend_with_s2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(segments, zones, raw_bars=bars, macd_history_anchored=True)
    assert TradingPointType.SELL1 in _types(result.points)
    assert TradingPointType.SELL2 in _types(result.points)
    s1 = next(x for x in result.points if x.point_type is TradingPointType.SELL1)
    s2 = next(x for x in result.points if x.point_type is TradingPointType.SELL2)
    assert s1.segment_index == 10 and s2.segment_index == 12


def test_second_buy_rejected_without_sublevel_first_buy() -> None:
    segments = _downtrend_with_b2()
    segments[12] = replace(segments[12], strokes=(segments[12].strokes[0],))
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(segments, zones, raw_bars=bars, macd_history_anchored=True)
    assert TradingPointType.BUY1 in _types(result.points)
    assert TradingPointType.BUY2 not in _types(result.points)
    assert any(x.point_type is TradingPointType.BUY2 and x.status is TradingPointStatus.REJECTED for x in result.candidates)


def test_first_buy_stays_pending_when_c_has_third_sell_shape_but_only_one_sublevel_zone() -> None:
    segments = _segment_chain(
        [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80],
        start_bottom=False,
        durations=[5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 16],
    )
    # 三笔能画出“离开—回抽不回—继续”，但只形成一个次级别中枢；
    # 按 a+A+b+B+c 的严格条件不能提升为正式一买。
    segments[10] = _with_internal_strokes(segments[10], [108, 95, 101, 80], [5, 5, 2])
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(
        segments, zones, raw_bars=bars, macd_history_anchored=True
    )
    assert TradingPointType.BUY1 not in _types(result.points)
    candidate = next(x for x in result.candidates if x.point_type is TradingPointType.BUY1)
    assert candidate.status is TradingPointStatus.PENDING
    assert dict(candidate.checks)["c内次级别中枢数"] == "1"


def test_validator_recomputes_macd_and_c_structure_instead_of_trusting_saved_evidence() -> None:
    segments = _downtrend_with_b2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(
        segments, zones, raw_bars=bars, macd_history_anchored=True
    )
    b1 = next(x for x in result.points if x.point_type is TradingPointType.BUY1)

    forged = []
    for key, value in b1.evidence:
        forged.append((key, "0" if key in {"b方向MACD面积", "进入MACD面积"} else value))
    forged_point = replace(b1, evidence=tuple(forged))
    forged_codes = {
        x.code for x in validate_trading_points(
                (forged_point,),
                segments,
                zones,
                raw_bars=bars,
                segment_commit_times=_commit_times(segments),
        )
    }
    assert "BS1_MACD_EVIDENCE_MISMATCH" in forged_codes

    weakened = list(segments)
    weakened[10] = _with_internal_strokes(weakened[10], [108, 95, 101, 80], [5, 5, 2])
    weakened_bars = _raw_bars(weakened)
    weakened_zones = detect_segment_central_zones(weakened).zones
    weakened_codes = {
        x.code for x in validate_trading_points(
            (b1,),
            weakened,
            weakened_zones,
            raw_bars=weakened_bars,
            segment_commit_times=_commit_times(weakened),
        )
    }
    assert "BS1_C_NOT_COMPLETE" in weakened_codes


def test_validator_requires_exact_formal_commit_confirmation_time() -> None:
    segments = _downtrend_with_b2()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(
        segments,
        zones,
        raw_bars=bars,
        macd_history_anchored=True,
    )
    point = next(x for x in result.points if x.point_type is TradingPointType.BUY1)
    forged = replace(point, confirmed_at_dt=point.confirmed_at_dt + timedelta(days=1))

    codes = {
        item.code
        for item in validate_trading_points(
            (forged,),
            segments,
            zones,
            raw_bars=bars,
            segment_commit_times=_commit_times(segments),
            macd_history_anchored=True,
        )
    }
    assert "TRADING_POINT_CONFIRM_TIME_MISMATCH" in codes


def test_third_buy_and_sell_accept_boundary_touch() -> None:
    buy_segments = _segment_chain([100,120,105,118,108,130,118], start_bottom=True)
    buy_zones = detect_segment_central_zones(buy_segments).zones
    buy = _detect_trading_points(buy_segments, buy_zones, raw_bars=_raw_bars(buy_segments), macd_history_anchored=True)
    assert TradingPointType.BUY3 in _types(buy.points)

    sell_segments = _segment_chain([130,110,125,112,122,100,112], start_bottom=False, origin=datetime(2026,5,1,tzinfo=timezone.utc))
    sell_zones = detect_segment_central_zones(sell_segments).zones
    sell = _detect_trading_points(sell_segments, sell_zones, raw_bars=_raw_bars(sell_segments), macd_history_anchored=True)
    assert TradingPointType.SELL3 in _types(sell.points)


def test_no_first_point_with_only_one_central_zone() -> None:
    segments = _segment_chain([120,100,115,95,108,90], start_bottom=False)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(segments, zones, raw_bars=_raw_bars(segments), macd_history_anchored=True)
    assert TradingPointType.BUY1 not in _types(result.points)
    assert TradingPointType.SELL1 not in _types(result.points)


def test_independent_reference_matches_deterministic_cases() -> None:
    for segments in (_downtrend_with_b2(), _uptrend_with_s2()):
        bars = _raw_bars(segments)
        zones = detect_segment_central_zones(segments).zones
        result = _detect_trading_points(segments, zones, raw_bars=bars, macd_history_anchored=True)
        comparison = compare_trading_points_with_reference(result.points, segments, zones, raw_bars=bars, macd_history_anchored=True)
        assert comparison.all_match


def test_core_separation_or_intermediate_departure_does_not_create_first_buy() -> None:
    segments = _core_separated_but_not_strict()
    bars = _raw_bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(
        segments, zones, raw_bars=bars, macd_history_anchored=True
    )
    assert TradingPointType.BUY1 not in _types(result.points)


def test_directional_macd_area_ignores_opposite_color_histogram() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    unit = type("Unit", (), {
        "source_start": start,
        "source_end": start + timedelta(minutes=3),
    })()
    hist = {
        start: -2.0,
        start + timedelta(minutes=1): 5.0,
        start + timedelta(minutes=2): -3.0,
        start + timedelta(minutes=3): 7.0,
    }
    assert _directional_macd_area(unit, StrokeDirection.DOWN, hist) == 5.0
    assert _directional_macd_area(unit, StrokeDirection.UP, hist) == 12.0


def test_macd_anchor_makes_window_result_identical_and_unanchored_window_is_pending() -> None:
    segments = _downtrend_with_b2()
    structure_bars = _raw_bars(segments)
    first = structure_bars[0].open_time
    warmup = []
    price = 150.0
    for i in range(120):
        dt = first - timedelta(minutes=120 - i)
        close = price + (i % 7 - 3) * 0.1
        warmup.append(RawBar(
            "TESTUSDT", "1m", dt, dt + timedelta(minutes=1), price,
            max(price, close) + 0.05, min(price, close) - 0.05, close, 1, 1, 1,
        ))
        price = close
    zones = detect_segment_central_zones(segments).zones
    full = _detect_trading_points(
        segments, zones, raw_bars=tuple(warmup) + structure_bars,
        macd_history_anchored=True,
    )
    anchor = build_macd_anchor(warmup)
    restored = _detect_trading_points(
        segments, zones, raw_bars=structure_bars, macd_anchor=anchor
    )
    assert [
        (x.point_type, x.dt, x.price, x.segment_index) for x in full.points
    ] == [
        (x.point_type, x.dt, x.price, x.segment_index) for x in restored.points
    ]
    assert [
        (x.entry_macd_area, x.exit_macd_area) for x in full.trend_divergences
    ] == [
        (x.entry_macd_area, x.exit_macd_area) for x in restored.trend_divergences
    ]

    unanchored = _detect_trading_points(segments, zones, raw_bars=structure_bars)
    assert TradingPointType.BUY1 not in _types(unanchored.points)
    assert any(
        x.point_type is TradingPointType.BUY1
        and x.status is TradingPointStatus.PENDING
        and "MacdAnchor" in x.reason
        for x in unanchored.candidates
    )


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
    assert not validate_trading_points(
        result.trading_points,
        result.segments,
        result.segment_central_zones,
        raw_bars=result.raw_bars,
        segment_evidence=result.segment_evidence,
        strokes=result.resolved_strokes,
        macd_history_anchored=result.left_boundary_anchored,
        macd_anchor=result.macd_anchor,
    )
    fig = build_raw_chart(result, show_trading_points=True)
    names = {trace.name for trace in fig.data}
    for point in result.trading_points:
        assert f"{point.point_type.label}（{point.point_type.value}）" in names
