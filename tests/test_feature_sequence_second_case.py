from __future__ import annotations

from datetime import datetime, timedelta, timezone

import chan_monitor.segments as segment_module
from chan_monitor.models import (
    FeatureBreakStatus,
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Stroke,
    StrokeDirection,
)


def _fractal(index: int, mark: FractalMark, value: float) -> Fractal:
    center = datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(hours=index * 10)
    if mark is FractalMark.TOP:
        high, low = value, value - 2
    else:
        high, low = value + 2, value
    bars = []
    for offset in (-1, 0, 1):
        dt = center + timedelta(hours=offset)
        raw = RawBar(
            symbol="TESTUSDT",
            interval="1h",
            open_time=dt,
            close_time=dt + timedelta(hours=1),
            open=low + 0.5,
            high=high,
            low=low,
            close=high - 0.5,
            volume=1,
            quote_volume=1,
            trade_count=1,
        )
        bars.append(MergedBar.from_raw(raw, id_=index * 10 + offset + 1))
    return Fractal(
        symbol="TESTUSDT",
        dt=center,
        mark=mark,
        high=high,
        low=low,
        value=value,
        elements=(bars[0], bars[1], bars[2]),
        merged_index=index,
    )


def _stroke_chain_from_top(values: list[float]) -> tuple[Stroke, ...]:
    points = [
        _fractal(i, FractalMark.TOP if i % 2 == 0 else FractalMark.BOTTOM, value)
        for i, value in enumerate(values)
    ]
    strokes = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        direction = StrokeDirection.DOWN if a.mark is FractalMark.TOP else StrokeDirection.UP
        strokes.append(
            Stroke(
                symbol="TESTUSDT",
                fx_a=a,
                fx_b=b,
                fractals=(a, b),
                direction=direction,
                bars=(a.elements[1], b.elements[1]),
                index=i,
            )
        )
    return tuple(strokes)


def test_second_case_reverse_feature_sequence_needs_only_standard_fractal() -> None:
    # Lesson 67/77 second case: the reverse (second) feature sequence does not recurse
    # into first/second-case confirmation again. Here its middle feature element is
    # produced by inclusion: the standard bottom fractal exists, while the generic
    # first-sequence actual-break rule is still PENDING because the right element has
    # not exceeded the last raw stroke inside the merged middle element.
    strokes = _stroke_chain_from_top(
        [30, 20, 24, 18, 25, 16, 26, 17, 25.5]
    )

    detector = segment_module._FeatureDetector(
        strokes,
        segment_direction=StrokeDirection.DOWN,
        sequence_start_position=0,
        require_actual_break=True,
    )
    assert detector.add_position(1) is None
    assert detector.add_position(3) is None
    assert detector.add_position(5) is None
    candidate = detector.add_position(7)
    assert candidate is not None
    assert candidate.middle.stroke_positions == (3, 5)
    assert candidate.break_status is FeatureBreakStatus.PENDING

    reverse = segment_module._start_reverse_attempt(
        strokes,
        StrokeDirection.UP,
        endpoint_position=0,
        active_from=0,
    )
    assert reverse.confirmed is not None
    assert reverse.confirmed.middle.stroke_positions == (3, 5)
    assert reverse.confirmed.break_status is FeatureBreakStatus.CONFIRMED
    assert reverse.confirmed.detected_at_position == reverse.confirmed.right.last_stroke_position == 7
