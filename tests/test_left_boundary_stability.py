from __future__ import annotations

from chan_monitor.chart import build_raw_chart
from chan_monitor.data import demo_bars
from chan_monitor.engine import StructureAnchor, analyze_bars


def _stroke_key(item) -> tuple:
    return (
        item.start_dt,
        item.end_dt,
        round(item.start_value, 12),
        round(item.end_value, 12),
        item.direction,
    )


def _segment_key(item) -> tuple:
    return (
        item.start_dt,
        item.end_dt,
        round(item.start_value, 12),
        round(item.end_value, 12),
        item.direction,
    )


def _zone_key(item) -> tuple:
    return (
        tuple(_stroke_key(x) for x in item.strokes[:3]),
        round(item.zd, 12),
        round(item.zg, 12),
    )


def _segment_zone_key(item) -> tuple:
    return (
        tuple(_segment_key(x) for x in item.segments[:3]),
        round(item.zd, 12),
        round(item.zg, 12),
    )


def _assert_contiguous_suffix_of_reference(actual: tuple, reference: tuple) -> None:
    if not actual:
        return
    start = reference.index(actual[0])
    assert actual == reference[start : start + len(actual)]


def test_unanchored_window_publishes_no_formal_structure() -> None:
    result = analyze_bars(demo_bars(1000, symbol="BTCUSDT", interval="5m"))

    assert not result.left_boundary_resolved
    assert not result.left_boundary_anchored
    assert result.left_anchor is None
    assert result.segments == ()
    assert result.central_zones == ()
    assert result.segment_central_zones == ()
    assert result.trading_points == ()
    assert result.resolved_strokes == ()
    assert result.stable_strokes == ()
    assert result.provisional_segments == ()
    assert result.unresolved_prefix_segments == result.detected_segments
    assert result.unresolved_segment_prefix_strokes == result.strokes
    assert any(
        item.code == "UNRESOLVED_LEFT_BOUNDARY_SEGMENT"
        for item in result.segment_diagnostics
    )




def test_unanchored_chart_uses_candidate_lines_only() -> None:
    result = analyze_bars(demo_bars(600, symbol="BTCUSDT", interval="5m"))
    figure = build_raw_chart(result)
    names = {trace.name for trace in figure.data}

    assert "笔" not in names
    assert "线段" not in names
    assert "未确认笔（同色虚线）" in names
    assert "未确认线段（同色虚线）" in names

def test_arbitrary_truncated_windows_remain_candidate_only_without_anchor() -> None:
    bars = demo_bars(1000, symbol="BTCUSDT", interval="5m")

    # 覆盖不同 K 线相位。安全性来自“没有锚点就不发布正式结构”，而不是
    # 猜测窗口中第几条线段可能已经重新对齐。
    for offset in range(0, 500, 10):
        result = analyze_bars(bars[offset:])
        assert not result.left_boundary_resolved
        assert result.segments == ()
        assert result.central_zones == ()
        assert result.segment_central_zones == ()
        assert result.trading_points == ()
        assert result.unresolved_prefix_segments == result.detected_segments


def test_trusted_origin_is_explicit_opt_in_not_default_assumption() -> None:
    bars = demo_bars(600, symbol="BTCUSDT", interval="5m")
    cold = analyze_bars(bars)
    anchored = analyze_bars(bars, left_boundary_anchored=True)

    detected = tuple(_segment_key(x) for x in anchored.detected_segments)
    assert cold.segments == ()
    assert tuple(_segment_key(x) for x in anchored.segments) == detected[:-1]
    assert cold.unresolved_prefix_segments == cold.detected_segments
    assert anchored.unresolved_prefix_segments == ()
    assert anchored.left_boundary_resolved
    assert anchored.left_boundary_anchored
    assert len(anchored.resolved_strokes) == len(anchored.stable_strokes)
    assert anchored.central_zones


def test_persisted_segment_endpoint_anchor_recovers_only_reference_suffix() -> None:
    bars = demo_bars(1000, symbol="BTCUSDT", interval="5m")
    full = analyze_bars(bars, left_boundary_anchored=True)
    anchor_segment = full.segments[1]
    anchor = StructureAnchor(
        dt=anchor_segment.end_dt,
        value=anchor_segment.end_value,
        mark=anchor_segment.fx_b.mark,
    )

    # 窗口并非真实历史起点，但仍包含持久化端点及其必要上下文。
    truncated = analyze_bars(bars[100:], left_anchor=anchor)
    assert truncated.left_boundary_resolved
    assert not truncated.left_boundary_anchored
    assert truncated.left_anchor == anchor

    actual_segments = tuple(_segment_key(x) for x in truncated.segments)
    reference_segments = tuple(_segment_key(x) for x in full.segments)
    _assert_contiguous_suffix_of_reference(actual_segments, reference_segments)
    assert actual_segments[0] == reference_segments[2]

    actual_zones = tuple(_zone_key(x) for x in truncated.central_zones)
    reference_zones = tuple(_zone_key(x) for x in full.central_zones)
    _assert_contiguous_suffix_of_reference(actual_zones, reference_zones)

    actual_segment_zones = tuple(
        _segment_zone_key(x) for x in truncated.segment_central_zones
    )
    reference_segment_zones = tuple(
        _segment_zone_key(x) for x in full.segment_central_zones
    )
    _assert_contiguous_suffix_of_reference(actual_segment_zones, reference_segment_zones)


def test_missing_persisted_anchor_fails_closed() -> None:
    bars = demo_bars(1000, symbol="BTCUSDT", interval="5m")
    full = analyze_bars(bars, left_boundary_anchored=True)
    old_segment = full.segments[0]
    anchor = StructureAnchor(
        dt=old_segment.end_dt,
        value=old_segment.end_value,
        mark=old_segment.fx_b.mark,
    )

    # 该窗口已经裁掉锚点。程序不得猜测一个替代起点。
    result = analyze_bars(bars[150:], left_anchor=anchor)
    assert not result.left_boundary_resolved
    assert result.segments == ()
    assert result.central_zones == ()
    assert result.segment_central_zones == ()
    assert result.trading_points == ()
    assert result.unresolved_prefix_segments == result.detected_segments
