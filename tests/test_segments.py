from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.feature_sequence_reference import (
    compare_feature_sequence_reference,
    run_feature_sequence_reference,
)
from chan_monitor.models import (
    FeatureBreakStatus,
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Stroke,
    StrokeDirection,
)
from chan_monitor.segments import SegmentMode, detect_segments, validate_segment_chain


def _fractal(index: int, mark: FractalMark, value: float) -> Fractal:
    center = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index * 10)
    if mark is FractalMark.TOP:
        high, low = value, value - 2
    else:
        high, low = value + 2, value

    bars: list[MergedBar] = []
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


def _stroke_chain(values: list[float]) -> list[Stroke]:
    points = [
        _fractal(i, FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP, value)
        for i, value in enumerate(values)
    ]
    strokes: list[Stroke] = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        direction = StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
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
    return strokes


def _signature(result) -> tuple:
    return tuple(
        (x.direction, x.fx_a.dt, x.fx_b.dt, x.stroke_count)
        for x in result.segments
    )


def test_no_gap_feature_fractal_confirms_segment_directly() -> None:
    # 向上线段特征序列为三根向下笔：
    # [15,20]、[18,25]、[14,23]，中间元素构成无缺口顶分型。
    strokes = _stroke_chain([10, 20, 15, 25, 18, 23, 14])
    result = detect_segments(strokes)

    assert len(result.segments) == 1
    assert result.segments[0].direction is StrokeDirection.UP
    assert result.segments[0].stroke_count == 3
    assert result.segments[0].fx_b.merged_index == 3
    assert result.evidence[0].confirmation == "NO_GAP"
    assert result.evidence[0].primary_fractal.gap is False
    assert result.evidence[0].primary_fractal.actual_break is True
    assert validate_segment_chain(result.segments, strokes, evidence=result.evidence) == ()


def test_gap_feature_fractal_waits_for_reverse_feature_fractal() -> None:
    # 主顶分型第一、二元素有缺口；从候选顶开始的向下线段特征序列随后出现底分型。
    strokes = _stroke_chain([10, 20, 15, 25, 23, 24, 18, 22, 20, 23])
    result = detect_segments(strokes)

    assert len(result.segments) >= 1
    first = result.evidence[0]
    assert first.end_position == 3
    assert first.confirmation == "GAP_REVERSE_FRACTAL"
    assert first.primary_fractal.gap is True
    assert first.reverse_fractal is not None
    assert first.reverse_fractal.mark is FractalMark.BOTTOM


def test_cross_boundary_included_element_is_not_merged() -> None:
    # 第一特征元素 [15,20] 被第二元素 [14,25] 完整包含。假设转折点两侧的
    # 两元素不能按普通包含关系合并，否则会吞掉真正的线段顶。
    strokes = _stroke_chain([10, 20, 15, 25, 14, 23, 13])
    result = detect_segments(strokes)

    assert len(result.segments) == 1
    primary = result.evidence[0].primary_fractal
    assert primary.endpoint_position == 3
    assert primary.left.stroke_positions == (1,)
    assert primary.middle.stroke_positions == (3,)
    assert primary.right.stroke_positions == (5,)


def test_inclusion_artifact_needs_later_actual_break() -> None:
    # 第二特征元素由 [18,25] 与包含它的 [16,26] 合并为 [18,26]。
    # 第三元素 [17,24] 虽形成顶分型，但尚未跌破第二元素最后一根原始特征笔的低点 16；
    # 直到下一根同向特征笔低点 15 才能确认真实突破。
    values = [10, 20, 15, 25, 18, 26, 16, 24, 17, 23, 15]
    before = detect_segments(_stroke_chain(values[:10]))
    after = detect_segments(_stroke_chain(values))

    assert len(before.segments) == 0
    assert any(
        x.break_status is FeatureBreakStatus.PENDING
        for x in before.feature_fractals
    )
    assert len(after.segments) == 1
    fx = after.evidence[0].primary_fractal
    assert fx.middle.stroke_positions == (3, 5)
    assert fx.endpoint_position == 5
    assert fx.detected_at_position == 9
    assert fx.actual_break is True
    assert fx.break_status is FeatureBreakStatus.CONFIRMED


def test_legacy_mode_names_map_to_one_feature_sequence_algorithm() -> None:
    strokes = _stroke_chain([10, 20, 15, 25, 18, 23, 14])
    feature = detect_segments(strokes, mode=SegmentMode.FEATURE_SEQUENCE)
    strict = detect_segments(strokes, mode="strict")
    loose = detect_segments(strokes, mode="loose")
    assert _signature(feature) == _signature(strict) == _signature(loose)
    assert strict.mode is SegmentMode.FEATURE_SEQUENCE


def test_random_stroke_chains_match_independent_reference() -> None:
    rng = random.Random(20260726)
    for _ in range(1000):
        point_count = rng.randrange(8, 121)
        values = []
        for i in range(point_count):
            if i % 2 == 0:
                values.append(rng.uniform(70, 110))
            else:
                values.append(rng.uniform(115, 155))
        strokes = _stroke_chain(values)
        result = detect_segments(strokes)
        reference = run_feature_sequence_reference(strokes)
        assert [
            (x.direction, x.start_dt, x.end_dt, x.stroke_count)
            for x in result.segments
        ] == [
            (
                x.direction,
                strokes[x.start].fx_a.dt,
                strokes[x.end].fx_a.dt,
                x.end - x.start,
            )
            for x in reference
        ]
        assert [
            (x.confirmation, x.confirmed_at_position)
            for x in result.evidence
        ] == [
            (x.confirmation, x.confirmed_at)
            for x in reference
        ]


def test_real_snapshot_matches_independent_feature_sequence_reference() -> None:
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, min_bi_len=6)
    comparison = compare_feature_sequence_reference(
        result.segments,
        result.segment_evidence,
        result.strokes,
    )

    assert len(result.strokes) == 26
    assert len(result.segments) == 4
    assert [x.stroke_count for x in result.segments] == [5, 5, 3, 5]
    assert len(result.unresolved_segment_prefix_strokes) == 1
    assert len(result.unfinished_segment_strokes) == 7
    assert comparison.all_match
    assert validate_segment_chain(
        result.segments,
        result.strokes,
        evidence=result.segment_evidence,
    ) == ()


def test_batch_and_incremental_results_include_identical_feature_sequences() -> None:
    bars = demo_bars(220)
    expected = analyze_bars(bars)
    actual = FractalEngine().extend(bars)
    assert actual.segment_markers == expected.segment_markers
    assert actual.segments == expected.segments
    assert actual.unfinished_segment_strokes == expected.unfinished_segment_strokes
    assert actual.feature_fractals == expected.feature_fractals
    assert actual.segment_evidence == expected.segment_evidence


def test_false_actual_break_is_rejected_then_scanning_continues() -> None:
    """首个伪特征分型被否定后，状态机必须继续找到后面的线段。"""
    result = analyze_bars(demo_bars(600, symbol="BTCUSDT", interval="5m"))

    assert len(result.strokes) == 37
    assert len(result.segments) == 4
    assert len(result.feature_elements) == 36
    assert len(result.unfinished_segment_strokes) == 3
    assert any(
        x.code == "FEATURE_FRACTAL_REJECTED_NO_ACTUAL_BREAK"
        for x in result.segment_diagnostics
    )
    assert any(
        x.break_status is FeatureBreakStatus.REJECTED
        for x in result.feature_fractals
    )
    assert max(
        position
        for element in result.feature_elements
        for position in element.stroke_positions
    ) == len(result.strokes) - 1


def test_feature_sequence_coverage_guard_detects_silent_tail_truncation() -> None:
    from chan_monitor.segments import validate_feature_sequence_coverage

    result = analyze_bars(demo_bars(600, symbol="BTCUSDT", interval="5m"))
    truncated = tuple(
        element
        for element in result.feature_elements
        if element.last_stroke_position <= 12
    )
    issues = validate_feature_sequence_coverage(truncated, result.strokes)

    assert len(issues) == 1
    assert issues[0].code == "FEATURE_SEQUENCE_TAIL_NOT_SCANNED"
    assert validate_feature_sequence_coverage(result.feature_elements, result.strokes) == ()


def test_5000_bar_feature_sequence_reaches_tail_and_matches_reference() -> None:
    result = analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    comparison = compare_feature_sequence_reference(
        result.segments,
        result.segment_evidence,
        result.strokes,
    )

    assert len(result.strokes) == 338
    assert len(result.segments) == 61
    assert len(result.feature_elements) == 307
    assert len(result.feature_fractals) == 63
    assert len(result.unfinished_segment_strokes) == 3
    assert max(
        position
        for element in result.feature_elements
        for position in element.stroke_positions
    ) == 337
    assert comparison.all_match
    assert validate_segment_chain(
        result.segments,
        result.strokes,
        evidence=result.segment_evidence,
    ) == ()


def test_confirmed_segment_prefixes_are_stable_as_more_strokes_arrive() -> None:
    full_result = analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    full_signature = _signature(full_result)

    for count in (40, 80, 120, 180, 240, 300, 338):
        prefix = detect_segments(full_result.strokes[:count])
        assert _signature(prefix) == full_signature[: len(prefix.segments)]
        assert all(
            item.confirmed_at_position < count
            for item in prefix.evidence
        )
