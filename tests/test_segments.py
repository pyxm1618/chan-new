from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

import pytest

import chan_monitor.segments as segment_module
from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import FractalEngine, StructureState, analyze_bars
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
from chan_monitor.segments import (
    SegmentMode,
    SegmentValidationTarget,
    detect_segments,
    detect_segments_from_anchor,
    stroke_endpoints,
    validate_segment_chain,
)


def _analyze_bars(*args, **kwargs):
    kwargs.setdefault("min_bi_len", 6)
    kwargs.setdefault("left_boundary_anchored", True)
    return analyze_bars(*args, **kwargs)


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


def _segments_signature(segments) -> tuple:
    return tuple(
        (x.direction, x.fx_a.dt, x.fx_b.dt, x.stroke_count)
        for x in segments
    )


def _signature(result) -> tuple:
    return _segments_signature(result.segments)


def test_first_segment_skips_invalid_window_prefix() -> None:
    result = _analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    detected = detect_segments(
        result.strokes,
        exclude_last_stroke_confirmation=True,
    )

    first = detected.evidence[0]
    assert first.start_position == 1
    assert first.end_position == 4
    assert len(detected.unresolved_prefix_strokes) == 1

    segment = detected.segments[0]
    assert segment.direction is StrokeDirection.UP
    assert segment.start_value == pytest.approx(90.2114, abs=1e-4)
    assert segment.end_value == pytest.approx(110.1656, abs=1e-4)

    # 该测试显式声明真实历史起点；几何扫描跳过的第 0 笔不等于窗口未锚定。
    assert result.unresolved_prefix_segments == ()
    assert result.unresolved_segment_prefix_strokes == ()


def test_empty_committed_chain_validator_returns_cleanly() -> None:
    assert validate_segment_chain(
        (),
        (),
        validation_target=SegmentValidationTarget.COMMITTED,
        stable_stroke_count=0,
    ) == ()


def test_two_stroke_tail_keeps_feature_element_audit() -> None:
    strokes = _stroke_chain([100, 110, 102])
    result = detect_segments_from_anchor(
        strokes,
        start_position=0,
        exclude_last_stroke_confirmation=True,
    )
    assert result.segments == ()
    assert result.unfinished_strokes == tuple(strokes)
    # 锚点后的第 1 根反向笔已进入标准特征序列，必须保留审计元素。
    assert len(result.feature_elements) == 1
    assert result.feature_elements[0].stroke_positions == (1,)


def test_first_segment_extreme_guard_rejects_internal_boundary_breaks() -> None:
    up_with_lower_bottom = _stroke_chain([10, 20, 9, 25])
    up_with_higher_top = _stroke_chain([10, 25, 12, 20])
    down_with_higher_top = _stroke_chain([80, 110, 90, 115, 85])
    down_with_lower_bottom = _stroke_chain([80, 110, 80, 100, 85])

    assert not segment_module._first_segment_extremes_valid(
        up_with_lower_bottom,
        stroke_endpoints(up_with_lower_bottom),
        0,
        3,
    )
    assert not segment_module._first_segment_extremes_valid(
        up_with_higher_top,
        stroke_endpoints(up_with_higher_top),
        0,
        3,
    )
    assert not segment_module._first_segment_extremes_valid(
        down_with_higher_top,
        stroke_endpoints(down_with_higher_top),
        1,
        4,
    )
    assert not segment_module._first_segment_extremes_valid(
        down_with_lower_bottom,
        stroke_endpoints(down_with_lower_bottom),
        1,
        4,
    )


def test_rejected_complete_first_candidate_cannot_return_from_fallback(monkeypatch) -> None:
    strokes = _stroke_chain([10, 20, 15, 25, 18, 23, 14])
    endpoints = stroke_endpoints(strokes)

    def fake_scan(values, points, start):
        del points
        end = min(start + 3, len(values) - 1)
        return segment_module._ScanOutcome(
            start,
            end,
            None,
            None,
            "NO_GAP",
            end,
            [],
            [],
            [],
        )

    monkeypatch.setattr(segment_module, "_first_three_overlap", lambda *_: True)
    monkeypatch.setattr(segment_module, "_scan_segment", fake_scan)
    monkeypatch.setattr(
        segment_module,
        "_first_segment_extremes_valid",
        lambda *_: False,
    )

    outcome = segment_module._choose_first_segment(strokes, endpoints)
    assert outcome.end_position is None
    assert outcome.primary is None


def test_same_endpoint_same_price_prefers_later_first_start(monkeypatch) -> None:
    strokes = _stroke_chain([80, 110, 90, 110, 95, 100, 85, 99])
    endpoints = stroke_endpoints(strokes)

    def fake_scan(values, points, start):
        del values, points
        if start in (1, 3):
            return segment_module._ScanOutcome(
                start,
                6,
                None,
                None,
                "NO_GAP",
                7,
                [],
                [],
                [],
            )
        return segment_module._ScanOutcome(
            start,
            None,
            None,
            None,
            None,
            None,
            [],
            [],
            [],
        )

    monkeypatch.setattr(segment_module, "_first_three_overlap", lambda *_: True)
    monkeypatch.setattr(segment_module, "_scan_segment", fake_scan)

    outcome = segment_module._choose_first_segment(strokes, endpoints)
    assert outcome.start_position == 3
    assert outcome.end_position == 6


def test_truncated_stroke_windows_recover_the_same_confirmed_tail() -> None:
    complete = _analyze_bars(demo_bars(600, symbol="BTCUSDT", interval="5m"))
    complete_signature = _segments_signature(complete.detected_segments)
    end_to_index = {
        segment.fx_b.dt: index
        for index, segment in enumerate(complete.detected_segments)
    }

    for offset in range(20):
        truncated = detect_segments(
            complete.strokes[offset:],
            exclude_last_stroke_confirmation=True,
        )
        if not truncated.segments:
            continue
        first_end = truncated.segments[0].fx_b.dt
        assert first_end in end_to_index
        complete_index = end_to_index[first_end]
        assert _segments_signature(truncated.segments)[1:] == complete_signature[
            complete_index + 1 : complete_index + len(truncated.segments)
        ]


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
    for _ in range(200):
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
    result = _analyze_bars(bars, min_bi_len=6)
    comparison = compare_feature_sequence_reference(
        result.detected_segments,
        result.detected_segment_evidence,
        result.strokes,
    )

    assert len(result.strokes) == 26
    assert len(result.detected_segments) == 3
    assert [x.stroke_count for x in result.detected_segments] == [3, 9, 5]
    assert len(result.unresolved_prefix_segments) == 0
    assert len(result.segments) == 2
    assert len(result.provisional_segments) == 1
    assert len(result.unresolved_segment_prefix_strokes) == 0
    assert len(result.detected_unfinished_segment_strokes) == 7
    assert comparison.all_match
    assert validate_segment_chain(
        result.detected_segments,
        result.strokes,
        evidence=result.detected_segment_evidence,
        exclude_last_stroke_confirmation=True,
    ) == ()


def test_batch_and_incremental_results_include_identical_feature_sequences() -> None:
    bars = demo_bars(220)
    expected = _analyze_bars(bars)
    actual = FractalEngine(min_bi_len=6, left_boundary_anchored=True).extend(bars)
    assert actual.segment_markers == expected.segment_markers
    assert actual.segments == expected.segments
    assert actual.unfinished_segment_strokes == expected.unfinished_segment_strokes
    assert actual.feature_fractals == expected.feature_fractals
    assert actual.segment_evidence == expected.segment_evidence


def test_false_actual_break_is_rejected_then_scanning_continues() -> None:
    """首个伪特征分型被否定后，状态机必须继续找到后面的线段。"""
    result = _analyze_bars(demo_bars(600, symbol="BTCUSDT", interval="5m"))

    assert len(result.strokes) == 37
    assert len(result.detected_segments) == 4
    assert len(result.segments) == 3
    assert len(result.feature_elements) == 62
    assert len(result.feature_fractals) == 9
    assert len(result.detected_unfinished_segment_strokes) == 12
    assert max(
        position
        for element in result.feature_elements
        for position in element.stroke_positions
    ) == len(result.strokes) - 1


def test_feature_sequence_coverage_guard_detects_silent_tail_truncation() -> None:
    from chan_monitor.segments import validate_feature_sequence_coverage

    result = _analyze_bars(demo_bars(600, symbol="BTCUSDT", interval="5m"))
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
    result = _analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    comparison = compare_feature_sequence_reference(
        result.detected_segments,
        result.detected_segment_evidence,
        result.strokes,
    )

    assert len(result.strokes) == 338
    assert len(result.detected_segments) == 57
    assert len(result.unresolved_prefix_segments) == 0
    assert len(result.segments) == 56
    assert len(result.provisional_segments) == 1
    assert len(result.feature_elements) == 659
    assert len(result.feature_fractals) == 88
    assert len(result.detected_unfinished_segment_strokes) == 6
    assert max(
        position
        for element in result.feature_elements
        for position in element.stroke_positions
    ) == 337
    assert comparison.all_match
    assert validate_segment_chain(
        result.detected_segments,
        result.strokes,
        evidence=result.detected_segment_evidence,
        exclude_last_stroke_confirmation=True,
    ) == ()


def test_gap_waiting_still_migrates_extremes_until_a_later_no_gap_primary_wins() -> None:
    """缺口等待中端点可迁移，但后续无缺口主分型必须优先直接确认。"""
    result = _analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    from chan_monitor.segments import _scan_segment, stroke_endpoints

    outcome = _scan_segment(result.strokes, stroke_endpoints(result.strokes), 303)

    assert outcome.gap_origin is not None
    assert outcome.gap_origin.endpoint_position == 308
    assert outcome.end_position == 318
    assert outcome.confirmation == "NO_GAP"
    assert outcome.confirmed_at_position == 324
    assert outcome.final_endpoint is not None
    assert outcome.final_endpoint.value == result.strokes[318].fx_a.value
    replacements = [
        item for item in outcome.diagnostics
        if item.code == "GAP_PRIMARY_ENDPOINT_REPLACED"
    ]
    assert len(replacements) == 3
    assert "第 312 笔" in replacements[0].message
    assert any(
        item.code == "GAP_WAIT_CONFIRMED_BY_LATER_NO_GAP_PRIMARY"
        for item in outcome.diagnostics
    )


def test_gap_wait_does_not_ignore_later_confirmed_no_gap_primary() -> None:
    """回归：18→21 缺口等待后，25 在 27 形成无缺口主分型，应立即结束。"""
    result = _analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    from chan_monitor.segments import _scan_segment, stroke_endpoints

    outcome = _scan_segment(result.strokes, stroke_endpoints(result.strokes), 18)

    assert outcome.gap_origin is not None
    assert outcome.gap_origin.endpoint_position == 21
    assert outcome.gap_origin.gap is True
    assert outcome.end_position == 25
    assert outcome.confirmation == "NO_GAP"
    assert outcome.confirmed_at_position == 27
    assert outcome.primary is not None
    assert outcome.primary.endpoint_position == 25
    assert outcome.primary.gap is False
    assert outcome.reverse is None
    assert any(
        item.code == "GAP_WAIT_CONFIRMED_BY_LATER_NO_GAP_PRIMARY"
        for item in outcome.diagnostics
    )


def test_gap_confirmation_guard_detects_skipped_earlier_no_gap_primary() -> None:
    """独立不变量必须能识别旧版 18→31 的错误缺口确认。"""
    result = _analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    from chan_monitor.models import FeatureBreakStatus, SegmentEvidence
    from chan_monitor.segments import (
        _start_reverse_attempt,
        _trace_feature_detector,
        _validate_gap_wait_did_not_skip_no_gap_primary,
    )

    direction = result.strokes[18].direction
    trace = _trace_feature_detector(
        result.strokes,
        segment_direction=direction,
        sequence_start_position=18,
        feed_start=19,
    )
    confirmed = [
        fx for fx in trace.candidates
        if fx.break_status is FeatureBreakStatus.CONFIRMED
    ]
    origin = next(fx for fx in confirmed if fx.endpoint_position == 21)
    stale_primary = next(fx for fx in confirmed if fx.endpoint_position == 31)
    reverse = _start_reverse_attempt(
        result.strokes,
        direction,
        endpoint_position=31,
        active_from=31,
    ).confirmed
    assert reverse is not None
    bad = SegmentEvidence(
        segment_index=0,
        start_position=18,
        end_position=31,
        confirmation="GAP_REVERSE_FRACTAL",
        primary_fractal=stale_primary,
        reverse_fractal=reverse,
        gap_origin_fractal=origin,
        final_endpoint=result.strokes[31].fx_a,
    )

    issues = _validate_gap_wait_did_not_skip_no_gap_primary(
        strokes=result.strokes,
        evidence=bad,
        segment_index=0,
    )
    assert len(issues) == 1
    assert issues[0].code == "GAP_CONFIRMATION_SKIPPED_EARLIER_NO_GAP_PRIMARY"
    assert "第 25 笔" in issues[0].message
    assert "第 27 笔" in issues[0].message


def test_every_confirmed_gap_segment_uses_last_extreme_before_reverse_confirmation() -> None:
    result = _analyze_bars(demo_bars(5000, symbol="BTCUSDT", interval="5m"))
    for item in result.segment_evidence:
        if item.confirmation != "GAP_REVERSE_FRACTAL":
            continue
        origin = item.gap_origin_fractal or item.primary_fractal
        final = item.final_endpoint or result.strokes[item.end_position].fx_a
        direction = result.strokes[item.start_position].direction
        expected_direction = (
            StrokeDirection.DOWN
            if direction is StrokeDirection.UP
            else StrokeDirection.UP
        )
        candidates = [
            (position, result.strokes[position].fx_a)
            for position in range(origin.endpoint_position, item.confirmed_at_position + 1)
            if position < len(result.strokes)
            and result.strokes[position].direction is expected_direction
        ]
        if direction is StrokeDirection.UP:
            expected_position, expected = max(
                candidates, key=lambda x: (x[1].value, x[0])
            )
        else:
            expected_position, expected = min(
                candidates, key=lambda x: (x[1].value, -x[0])
            )
        assert item.end_position == expected_position
        assert final.value == expected.value


def test_detected_segment_prefixes_match_the_final_stroke_chain() -> None:
    # 这里只验证纯线段算法对同一最终笔链切片的一致性；原始 K 流的正式结构
    # 单调性由下面的 1000/5000 根提交账本测试覆盖。
    full_result = _analyze_bars(demo_bars(1000, symbol="BTCUSDT", interval="5m"))
    full_signature = _segments_signature(full_result.detected_segments)

    for count in (20, 30, 40, 50, 59):
        prefix = detect_segments(
            full_result.strokes[:count],
            exclude_last_stroke_confirmation=True,
        )
        assert _segments_signature(prefix.segments) == full_signature[: len(prefix.segments)]
        assert all(
            item.confirmed_at_position < count
            for item in prefix.evidence
        )


def test_raw_bar_prefix_does_not_confirm_segment_with_reversible_last_stroke() -> None:
    """新 K 可能撤销最后一笔；依赖该笔确认的线段必须保持候选状态。"""
    before = _analyze_bars(demo_bars(235, symbol="BTCUSDT", interval="5m"))
    after = _analyze_bars(demo_bars(236, symbol="BTCUSDT", interval="5m"))

    assert len(before.strokes) == 21
    assert len(after.strokes) == 20
    assert all(
        item.confirmed_at_position < len(before.strokes) - 1
        for item in before.segment_evidence
    )
    assert all(
        item.confirmed_at_position < len(after.strokes) - 1
        for item in after.segment_evidence
    )

    # 尾部检测段可以变化，但正式账本保持不变。
    assert len(before.detected_segments) == 2
    assert len(after.detected_segments) == 2
    assert len(before.segments) == 1
    assert _signature(before) == _signature(after)[: len(before.segments)]
    assert any(
        item.code == "SEGMENT_CONFIRMATION_USES_REVERSIBLE_LAST_STROKE"
        for item in before.segment_diagnostics
    )
    assert before.unfinished_segment_strokes


def test_confirmed_segments_are_monotonic_across_raw_bar_prefixes() -> None:
    """完整原始 K 流逐根推进，正式线段必须严格保持前缀单调。"""
    state = StructureState(min_bi_len=6, segment_mode=SegmentMode.FEATURE_SEQUENCE, left_boundary_anchored=True)
    previous: tuple = ()
    previous_stable: tuple = ()
    for bar in demo_bars(1000, symbol="BTCUSDT", interval="5m"):
        state.update(bar)
        current = _segments_signature(state.segments)
        stable = tuple(
            (x.start_dt, x.end_dt, x.start_value, x.end_value, x.direction)
            for x in state.stable_strokes
        )
        assert previous == current[: len(previous)]
        assert previous_stable == stable[: len(previous_stable)]
        assert state.canonical_strokes[: len(state.stable_strokes)] == state.stable_strokes
        assert state.canonical_strokes[len(state.stable_strokes):] == state.provisional_strokes
        previous = current
        previous_stable = stable


def test_validator_rejects_last_stroke_dependent_segment_even_if_detector_is_run_in_pure_mode() -> None:
    from chan_monitor.strokes import detect_strokes

    bars = demo_bars(235, symbol="BTCUSDT", interval="5m")
    strokes = detect_strokes(bars, min_bi_len=6).strokes
    pure = detect_segments(strokes, exclude_last_stroke_confirmation=False)
    assert pure.evidence[-1].confirmed_at_position == len(strokes) - 1

    issues = validate_segment_chain(
        pure.segments,
        strokes,
        evidence=pure.evidence,
        exclude_last_stroke_confirmation=True,
    )
    assert any(
        item.code == "SEGMENT_CONFIRMATION_USES_REVERSIBLE_LAST_STROKE"
        for item in issues
    )
