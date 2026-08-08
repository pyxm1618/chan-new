from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_monitor.chart import build_raw_chart
from chan_monitor.chart_styles import DEFAULT_CHART_STYLE
from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.models import (
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Segment,
    Stroke,
    StrokeDirection,
)
from chan_monitor.segment_central_zone_reference import (
    compare_segment_central_zones_with_reference,
)
from chan_monitor.segment_central_zones import (
    detect_segment_central_zones,
    validate_segment_central_zones,
)


def _fractal(index: int, mark: FractalMark, value: float) -> Fractal:
    center = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index * 10)
    high = value if mark is FractalMark.TOP else value + 1
    low = value - 1 if mark is FractalMark.TOP else value
    bars: list[MergedBar] = []
    for offset in (-1, 0, 1):
        dt = center + timedelta(hours=offset)
        raw = RawBar(
            symbol="TESTUSDT",
            interval="1h",
            open_time=dt,
            close_time=dt + timedelta(hours=1),
            open=low + 0.25,
            high=high,
            low=low,
            close=high - 0.25,
            volume=1,
            quote_volume=1,
            trade_count=1,
        )
        bars.append(MergedBar.from_raw(raw, id_=index * 3 + offset + 1))
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


def _segment_chain(values: list[float]) -> list[Segment]:
    points = [
        _fractal(i, FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP, value)
        for i, value in enumerate(values)
    ]
    segments: list[Segment] = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        direction = StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
        stroke = Stroke(
            symbol="TESTUSDT",
            fx_a=a,
            fx_b=b,
            fractals=(a, b),
            direction=direction,
            bars=(a.elements[1], b.elements[1]),
            index=i,
        )
        segments.append(
            Segment(
                symbol="TESTUSDT",
                fx_a=a,
                fx_b=b,
                direction=direction,
                strokes=(stroke,),
                index=i,
            )
        )
    return segments


def _segment_with_internal_interval(
    index: int,
    *,
    direction: StrokeDirection,
    start: float,
    end: float,
    internal_low: float,
    internal_high: float,
) -> Segment:
    base = index * 10
    if direction is StrokeDirection.DOWN:
        points = (
            _fractal(base, FractalMark.TOP, start),
            _fractal(base + 1, FractalMark.BOTTOM, internal_low),
            _fractal(base + 2, FractalMark.TOP, internal_high),
            _fractal(base + 3, FractalMark.BOTTOM, end),
        )
    else:
        points = (
            _fractal(base, FractalMark.BOTTOM, start),
            _fractal(base + 1, FractalMark.TOP, internal_high),
            _fractal(base + 2, FractalMark.BOTTOM, internal_low),
            _fractal(base + 3, FractalMark.TOP, end),
        )

    strokes = []
    for offset, (a, b) in enumerate(zip(points, points[1:])):
        stroke_direction = (
            StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
        )
        strokes.append(
            Stroke(
                symbol="TESTUSDT",
                fx_a=a,
                fx_b=b,
                fractals=(a, b),
                direction=stroke_direction,
                bars=(a.elements[1], b.elements[1]),
                index=index * 3 + offset,
            )
        )
    return Segment(
        symbol="TESTUSDT",
        fx_a=points[0],
        fx_b=points[-1],
        direction=direction,
        strokes=tuple(strokes),
        index=index,
    )


def test_three_continuous_segments_form_zone() -> None:
    segments = _segment_chain([10, 20, 12, 18])
    result = detect_segment_central_zones(segments)

    assert len(result.candidates) == 1
    assert len(result.zones) == 1
    zone = result.zones[0]
    assert zone.start_position == 0
    assert zone.end_position == 2
    assert zone.segment_count == 3
    assert (zone.zd, zone.zg, zone.zz) == (12, 18, 15)
    assert zone.is_valid
    assert validate_segment_central_zones(result.zones, segments) == ()


def test_zone_extends_with_fixed_first_three_overlap() -> None:
    segments = _segment_chain([10, 20, 12, 18, 13, 17])
    result = detect_segment_central_zones(segments)
    zone = result.zones[0]

    assert zone.segment_count == 5
    assert (zone.zd, zone.zg) == (12, 18)
    assert [x.index for x in zone.segments] == [0, 1, 2, 3, 4]
    assert validate_segment_central_zones(result.zones, segments) == ()


def test_first_non_overlapping_segment_starts_next_search() -> None:
    # 0~2 的重叠为 [12, 20]；第 3 段 [22, 25] 完全在上方。
    # 第 3~5 段随后形成新的重叠 [23, 25]。
    segments = _segment_chain([10, 20, 12, 25, 22, 28, 23])
    result = detect_segment_central_zones(segments)

    assert len(result.zones) == 2
    assert [(x.start_position, x.end_position) for x in result.zones] == [(0, 2), (3, 5)]
    assert [(x.zd, x.zg) for x in result.zones] == [(12, 20), (23, 25)]
    assert validate_segment_central_zones(result.zones, segments) == ()


def test_no_three_segment_overlap_means_no_zone() -> None:
    segments = _segment_chain([10, 20, 30, 40])
    result = detect_segment_central_zones(segments)
    assert result.candidates == ()
    assert result.zones == ()


def test_segment_zone_uses_actual_internal_segment_interval() -> None:
    # 第78课：以线段为最小级别部件时应按线段实际高低区间标准化，不能只看形式端点。
    segments = [
        _segment_with_internal_interval(
            0,
            direction=StrokeDirection.DOWN,
            start=100,
            end=90,
            internal_low=80,
            internal_high=110,
        ),
        _segment_with_internal_interval(
            1,
            direction=StrokeDirection.UP,
            start=111,
            end=120,
            internal_low=95,
            internal_high=125,
        ),
        _segment_with_internal_interval(
            2,
            direction=StrokeDirection.DOWN,
            start=94,
            end=85,
            internal_low=88,
            internal_high=115,
        ),
    ]

    assert (segments[0].high, segments[0].low) == (110, 80)
    result = detect_segment_central_zones(segments)
    assert len(result.zones) == 1
    assert (result.zones[0].zd, result.zones[0].zg) == (95, 110)


def test_random_chains_match_independent_reference() -> None:
    rng = random.Random(20260727)
    for _ in range(300):
        values = [100.0]
        for i in range(rng.randint(4, 24)):
            magnitude = rng.uniform(1, 18)
            values.append(values[-1] + magnitude if i % 2 == 0 else values[-1] - magnitude)
        segments = _segment_chain(values)
        result = detect_segment_central_zones(segments)
        comparison = compare_segment_central_zones_with_reference(
            result.zones,
            result.candidates,
            segments,
        )
        assert comparison.all_match
        assert validate_segment_central_zones(result.zones, segments) == ()


def test_real_snapshot_has_one_segment_zone_and_matches_reference() -> None:
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, min_bi_len=6, left_boundary_anchored=True)

    # 冻结样本显式声明从可信历史起点开始；第三条仍处于右侧 provisional。
    assert len(result.unresolved_prefix_segments) == 0
    assert len(result.segments) == 2
    assert len(result.provisional_segments) == 1
    assert len(result.segment_central_zones) == 0

    # 当前完整检测链仍保留旧几何结果作为候选和算法审计。
    assert len(result.detected_segments) == 3
    assert len(result.detected_segment_central_zones) == 1
    zone = result.detected_segment_central_zones[0]
    assert [x.index for x in zone.segments] == [0, 1, 2]
    assert (zone.zd, zone.zg) == (7917.0, 8124.92)
    comparison = compare_segment_central_zones_with_reference(
        result.detected_segment_central_zones,
        (),
        result.detected_segments,
    )
    assert comparison.zones_match
    assert validate_segment_central_zones(
        result.detected_segment_central_zones,
        result.detected_segments,
    ) == ()


def test_batch_and_incremental_results_include_identical_segment_zones() -> None:
    bars = demo_bars(260)
    expected = analyze_bars(bars, left_boundary_anchored=True)
    actual = FractalEngine(left_boundary_anchored=True).extend(bars)
    assert actual.segment_central_zones == expected.segment_central_zones
    assert actual.segment_central_zone_candidates == expected.segment_central_zone_candidates
    assert actual.segment_central_zone_diagnostics == expected.segment_central_zone_diagnostics


def test_chart_draws_light_orange_rectangle_per_segment_zone() -> None:
    result = analyze_bars(
        demo_bars(1000, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )
    figure = build_raw_chart(result)

    orange = [x for x in figure.layout.shapes if x.type == "rect" and x.line.color == "#FB923C"]
    assert len(orange) == len(result.segment_central_zones)
    assert all(x.fillcolor == DEFAULT_CHART_STYLE.segment_central_zone.fillcolor for x in orange)
    trace = next(x for x in figure.data if x.name == "线段中枢")
    assert len(trace.x) == len(result.segment_central_zones)
