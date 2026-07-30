from __future__ import annotations

from chan_monitor.central_zones import detect_central_zones
from chan_monitor.data import demo_bars
from chan_monitor.engine import (
    StructureState,
    _detect_formal_central_zones,
    _detect_formal_segment_central_zones,
)
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.segments import SegmentMode


def _stroke_key(item) -> tuple:
    return (
        item.start_dt,
        item.end_dt,
        item.start_value,
        item.end_value,
        item.direction,
    )


def _segment_key(item) -> tuple:
    return (
        item.start_dt,
        item.end_dt,
        item.start_value,
        item.end_value,
        item.direction,
    )


def _central_zone_seed(zone) -> tuple:
    return (
        tuple(_stroke_key(x) for x in zone.strokes[:3]),
        zone.zd,
        zone.zg,
    )


def _segment_zone_seed(zone) -> tuple:
    return (
        tuple(_segment_key(x) for x in zone.segments[:3]),
        zone.zd,
        zone.zg,
    )


def test_known_rollback_cases_only_change_provisional_tail() -> None:
    bars = demo_bars(1000, symbol="BTCUSDT", interval="5m")
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    snapshots = {}
    wanted = {125, 126, 175, 176, 235, 236, 378, 379, 403, 404, 633, 634, 810, 811, 990, 991}

    for count, bar in enumerate(bars, 1):
        state.update(bar)
        if count in wanted:
            snapshots[count] = (
                tuple(_stroke_key(x) for x in state.stable_strokes),
                tuple(_segment_key(x) for x in state.segments),
                len(state.detected_strokes),
                len(state.provisional_strokes),
            )

    for before, after in ((125, 126), (175, 176), (235, 236), (378, 379),
                          (403, 404), (633, 634), (810, 811), (990, 991)):
        stable_before, segments_before, detected_before, _ = snapshots[before]
        stable_after, segments_after, detected_after, _ = snapshots[after]
        assert stable_before == stable_after[: len(stable_before)]
        assert segments_before == segments_after[: len(segments_before)]
        assert detected_after <= detected_before


def test_5000_raw_bar_prefixes_have_zero_confirmed_structure_retractions() -> None:
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    previous_strokes: tuple = ()
    previous_segments: tuple = ()
    previous_zones: dict[tuple, object] = {}
    previous_segment_zones: dict[tuple, object] = {}

    for bar in demo_bars(5000, symbol="BTCUSDT", interval="5m"):
        state.update(bar)
        stable = tuple(_stroke_key(x) for x in state.stable_strokes)
        segments = tuple(_segment_key(x) for x in state.segments)

        assert previous_strokes == stable[: len(previous_strokes)]
        assert previous_segments == segments[: len(previous_segments)]
        canonical = state.canonical_strokes
        assert canonical[: len(state.stable_strokes)] == state.stable_strokes
        assert canonical[len(state.stable_strokes):] == state.provisional_strokes

        # 中枢输入未增长时结果不可能变化；只在提交边界推进时复算，避免测试本身
        # 把 5000 根逐前缀验证退化为无意义的重复全量中枢计算。
        if len(stable) != len(previous_strokes):
            zones, _ = _detect_formal_central_zones(
                state.resolved_stable_strokes,
                left_boundary_anchored=state.left_boundary_anchored,
            )
            current_zones = {_central_zone_seed(x): x for x in zones.zones}
            for seed, previous in previous_zones.items():
                assert seed in current_zones
                assert current_zones[seed].edt >= previous.edt
            previous_zones = current_zones

        if len(segments) != len(previous_segments):
            segment_zones, _ = _detect_formal_segment_central_zones(
                state.segments,
                left_boundary_anchored=state.left_boundary_anchored,
            )
            current_segment_zones = {
                _segment_zone_seed(x): x for x in segment_zones.zones
            }
            for seed, previous in previous_segment_zones.items():
                assert seed in current_segment_zones
                assert current_segment_zones[seed].edt >= previous.edt
            previous_segment_zones = current_segment_zones

        previous_strokes = stable
        previous_segments = segments

    assert len(state.detected_strokes) == 338
    assert len(state.stable_strokes) == 330
    assert len(state.resolved_stable_strokes) == 330
    assert len(state.provisional_strokes) == 8
    assert len(state.unresolved_prefix_segments) == 0
    assert len(state.segments) == 56
    assert len(state.provisional_segments) == 1


def test_analysis_result_keeps_all_stable_and_provisional_strokes_separate() -> None:
    from chan_monitor.engine import analyze_bars

    result = analyze_bars(
        demo_bars(5000, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )
    assert result.all_strokes == result.strokes
    assert result.all_strokes == result.stable_strokes + result.provisional_strokes
    assert len(result.detected_strokes) == 338
    assert len(result.stable_strokes) == 330
    assert len(result.resolved_strokes) == 330
    assert len(result.provisional_strokes) == 8
    assert not result.unresolved_prefix_segments
    assert tuple(_segment_key(x) for x in result.segments) == tuple(
        _segment_key(x) for x in result.detected_segments[:-1]
    )
    assert tuple(_segment_key(x) for x in result.provisional_segments) == tuple(
        _segment_key(x) for x in result.detected_segments[-1:]
    )
