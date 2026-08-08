from __future__ import annotations

from datetime import datetime, timedelta, timezone

from chan_monitor.models import (
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Segment,
    Stroke,
    StrokeDirection,
    TradingPointStatus,
    TradingPointType,
)
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.segments import detect_segments
from chan_monitor.single_level_trading_points import detect_trading_points


def _fractal(dt: datetime, mark: FractalMark, value: float, index: int) -> Fractal:
    high = value if mark is FractalMark.TOP else value + 0.5
    low = value - 0.5 if mark is FractalMark.TOP else value
    elements = []
    for j, offset in enumerate((-2, -1, 0)):
        t = dt + timedelta(minutes=offset)
        raw = RawBar(
            "TESTUSDT",
            "1m",
            t,
            t + timedelta(minutes=1),
            low + 0.1,
            high,
            low,
            high - 0.1,
            1,
            1,
            1,
        )
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
            "TESTUSDT",
            "1m",
            t,
            t + timedelta(minutes=1),
            open_,
            max(open_, close) + wiggle,
            min(open_, close) - wiggle,
            close,
            1,
            1,
            1,
        )
        bars.append(MergedBar.from_raw(raw, id_=index * 1000 + j))
    return Stroke("TESTUSDT", a, b, (a, b), direction, tuple(bars), index)


def _legal_segment(a: Fractal, b: Fractal, index: int, duration: int) -> Segment:
    direction = StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
    delta = b.value - a.value
    p1_mark = FractalMark.TOP if a.mark is FractalMark.BOTTOM else FractalMark.BOTTOM
    p2_mark = a.mark
    p1 = _fractal(a.dt + timedelta(minutes=1), p1_mark, a.value + delta * 0.9, index * 10 + 1)
    p2 = _fractal(b.dt - timedelta(minutes=1), p2_mark, a.value + delta * 0.1, index * 10 + 2)

    # Keep the outer segment's continuous raw-bar stream identical across its three
    # internal strokes. The detector under test must only consume Segment geometry,
    # while each Segment itself now satisfies the >=3 odd-stroke structural contract.
    outer = _stroke(a, b, index * 10, duration)
    points = (a, p1, p2, b)
    strokes = []
    for offset, (left, right) in enumerate(zip(points, points[1:])):
        stroke_direction = (
            StrokeDirection.UP if left.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
        )
        strokes.append(
            Stroke(
                "TESTUSDT",
                left,
                right,
                (left, right),
                stroke_direction,
                outer.bars,
                index * 3 + offset,
            )
        )
    return Segment("TESTUSDT", a, b, direction, tuple(strokes), index)


def _segment_chain(
    values: list[float],
    *,
    start_bottom: bool,
    durations: list[int] | None = None,
    origin: datetime | None = None,
) -> list[Segment]:
    origin = origin or datetime(2026, 1, 1, tzinfo=timezone.utc)
    durations = durations or [5] * (len(values) - 1)
    point_times = [origin]
    for duration in durations:
        point_times.append(point_times[-1] + timedelta(minutes=max(3, duration + 2)))

    points = []
    for i, (value, point_dt) in enumerate(zip(values, point_times)):
        bottom = (i % 2 == 0) if start_bottom else (i % 2 == 1)
        points.append(
            _fractal(
                point_dt,
                FractalMark.BOTTOM if bottom else FractalMark.TOP,
                value,
                i,
            )
        )

    return [
        _legal_segment(a, b, i, durations[i])
        for i, (a, b) in enumerate(zip(points, points[1:]))
    ]


def _raw_bars(segments: list[Segment]) -> tuple[RawBar, ...]:
    by_dt: dict[datetime, RawBar] = {}
    for segment in segments:
        for stroke in segment.strokes:
            for merged in stroke.bars:
                for bar in merged.elements:
                    by_dt[bar.open_time] = bar
    return tuple(by_dt[k] for k in sorted(by_dt))


def _commit_times(segments: list[Segment]) -> dict[str, datetime]:
    return {
        segment.fingerprint: max(segment.end_dt, segment.source_end)
        + timedelta(microseconds=1)
        for segment in segments
    }


def _types(result) -> set[TradingPointType]:
    return {point.point_type for point in result.points}


def _downtrend() -> list[Segment]:
    # Segment 4 is the long same-level connector b. Segment 10 is the final
    # departure c and makes a new low. Segments 11/12 form the first rebound
    # and retracement after B1; segment 12 ends above the B1 low.
    return _segment_chain(
        [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80, 95, 85],
        start_bottom=False,
        durations=[5, 5, 5, 5, 80, 5, 5, 5, 5, 5, 3, 5, 5],
    )


def _uptrend() -> list[Segment]:
    return _segment_chain(
        [60, 80, 65, 75, 68, 100, 88, 98, 90, 110, 92, 120, 105, 115],
        start_bottom=True,
        durations=[5, 5, 5, 5, 80, 5, 5, 5, 5, 5, 3, 5, 5],
        origin=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )


def test_b1_and_b2_use_only_same_level_segments_and_segment_zones() -> None:
    segments = _downtrend()
    assert all(len(segment.strokes) == 3 for segment in segments)
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )

    assert TradingPointType.BUY1 in _types(result)
    assert TradingPointType.BUY2 in _types(result)
    b1 = next(point for point in result.points if point.point_type is TradingPointType.BUY1)
    b2 = next(point for point in result.points if point.point_type is TradingPointType.BUY2)
    assert b1.segment_index == 10
    assert b2.segment_index == 12
    assert b1.evidence_kind == "SINGLE_LEVEL_TREND_MACD_DIVERGENCE"
    assert b2.evidence_kind == "SINGLE_LEVEL_FIRST_RETRACE"
    assert "次级别" not in str(b1.evidence)
    assert "次级别" not in str(b2.evidence)


def test_s1_and_s2_use_only_same_level_segments_and_segment_zones() -> None:
    segments = _uptrend()
    assert all(len(segment.strokes) == 3 for segment in segments)
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )

    assert TradingPointType.SELL1 in _types(result)
    assert TradingPointType.SELL2 in _types(result)
    s1 = next(point for point in result.points if point.point_type is TradingPointType.SELL1)
    s2 = next(point for point in result.points if point.point_type is TradingPointType.SELL2)
    assert s1.segment_index == 10
    assert s2.segment_index == 12
    assert s1.evidence_kind == "SINGLE_LEVEL_TREND_MACD_DIVERGENCE"
    assert s2.evidence_kind == "SINGLE_LEVEL_FIRST_RETRACE"


def test_formal_detector_rejects_intrinsically_invalid_segments_even_with_commit_times() -> None:
    legal = _downtrend()
    invalid = [
        Segment(
            segment.symbol,
            segment.fx_a,
            segment.fx_b,
            segment.direction,
            (segment.strokes[0],),
            segment.index,
        )
        for segment in legal
    ]
    zones = detect_segment_central_zones(invalid).zones

    result = detect_trading_points(
        invalid,
        zones,
        raw_bars=_raw_bars(invalid),
        segment_commit_times=_commit_times(invalid),
        macd_history_anchored=True,
    )

    assert result.points == ()
    assert any(
        diagnostic.code == "FORMAL_SEGMENT_STRUCTURE_INVALID"
        for diagnostic in result.diagnostics
    )


def test_detect_segments_output_can_feed_b1_and_b2_end_to_end() -> None:
    designed = _segment_chain(
        [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80, 95, 85, 92],
        start_bottom=False,
        durations=[5, 5, 5, 5, 80, 5, 5, 5, 5, 5, 3, 5, 5, 5],
    )
    stroke_chain = tuple(stroke for segment in designed for stroke in segment.strokes)
    detected = detect_segments(stroke_chain)

    assert len(detected.segments) >= 13
    segments = list(detected.segments[:13])
    assert all(segment.stroke_count >= 3 and segment.stroke_count % 2 == 1 for segment in segments)
    zones = detect_segment_central_zones(segments).zones
    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )

    assert TradingPointType.BUY1 in _types(result)
    assert TradingPointType.BUY2 in _types(result)


def test_b2_rejects_first_retracement_that_breaks_b1_low() -> None:
    segments = _segment_chain(
        [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80, 95, 79],
        start_bottom=False,
        durations=[5, 5, 5, 5, 80, 5, 5, 5, 5, 5, 3, 5, 5],
    )
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )

    assert TradingPointType.BUY1 in _types(result)
    assert TradingPointType.BUY2 not in _types(result)
    assert any(
        candidate.point_type is TradingPointType.BUY2
        and candidate.status is TradingPointStatus.REJECTED
        and "不破" in candidate.reason
        for candidate in result.candidates
    )


def test_b3_accepts_exact_segment_zone_boundary_touch() -> None:
    segments = _segment_chain(
        [100, 120, 105, 118, 108, 130, 118],
        start_bottom=True,
    )
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )

    b3 = next(point for point in result.points if point.point_type is TradingPointType.BUY3)
    assert b3.evidence_kind == "SINGLE_LEVEL_ZONE_DEPARTURE_RETEST"
    assert b3.zone_index is not None


def test_missing_formal_commit_evidence_fails_closed() -> None:
    segments = _downtrend()
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        macd_history_anchored=True,
    )

    assert result.points == ()
    assert any(
        diagnostic.code == "FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING"
        for diagnostic in result.diagnostics
    )


def test_unanchored_macd_keeps_b1_pending() -> None:
    segments = _downtrend()
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
    )

    assert TradingPointType.BUY1 not in _types(result)
    assert any(
        candidate.point_type is TradingPointType.BUY1
        and candidate.status is TradingPointStatus.PENDING
        and "MACD" in candidate.reason
        for candidate in result.candidates
    )


def test_one_segment_central_zone_cannot_create_b1_or_s1() -> None:
    segments = _segment_chain(
        [120, 100, 115, 95, 108, 90],
        start_bottom=False,
    )
    zones = detect_segment_central_zones(segments).zones

    result = detect_trading_points(
        segments,
        zones,
        raw_bars=_raw_bars(segments),
        segment_commit_times=_commit_times(segments),
        macd_history_anchored=True,
    )

    assert TradingPointType.BUY1 not in _types(result)
    assert TradingPointType.SELL1 not in _types(result)