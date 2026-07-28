from __future__ import annotations

from pathlib import Path

from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.models import MergedBar, RawBar, StrokeDirection
from chan_monitor.reference import compare_with_czsc_reference
from chan_monitor.strokes import check_bi, validate_stroke_chain


def rb(i: int, high: float, low: float) -> RawBar:
    return RawBar.simple(i, high, low)


def mb(i: int, high: float, low: float) -> MergedBar:
    return MergedBar.from_raw(rb(i, high, low), i)


def test_check_bi_requires_minimum_merged_bar_count() -> None:
    bars = [
        mb(0, 10, 8),
        mb(1, 9, 7),   # 底分型中心
        mb(2, 11, 9),
        mb(3, 12, 10),
        mb(4, 14, 12), # 顶分型中心
        mb(5, 13, 11),
    ]
    stroke, remaining = check_bi(bars, min_bi_len=6)
    assert stroke is not None
    assert stroke.direction is StrokeDirection.UP
    assert stroke.start_dt == bars[1].dt
    assert stroke.end_dt == bars[4].dt
    assert stroke.length == 6
    assert [x.dt for x in remaining] == [x.dt for x in bars[3:]]

    rejected, unchanged = check_bi(bars, min_bi_len=7)
    assert rejected is None
    assert unchanged == bars


def test_check_bi_chooses_most_extreme_valid_endpoint() -> None:
    bars = [
        mb(0, 10, 8),
        mb(1, 9, 7),    # 起点底
        mb(2, 11, 9),
        mb(3, 12, 10),
        mb(4, 14, 12),  # 第一个顶
        mb(5, 11, 9),   # 中间底
        mb(6, 13, 11),
        mb(7, 16, 14),  # 更高的顶，应作为终点
        mb(8, 15, 13),
    ]
    stroke, _ = check_bi(bars, min_bi_len=6)
    assert stroke is not None
    assert stroke.fx_b.dt == bars[7].dt
    assert stroke.fx_b.value == 16
    assert stroke.length == 9


def test_batch_and_incremental_results_include_identical_strokes() -> None:
    bars = demo_bars(180)
    expected = analyze_bars(bars)
    actual = FractalEngine().extend(bars)
    assert actual.strokes == expected.strokes
    assert actual.unfinished_bars == expected.unfinished_bars
    assert actual.stroke_diagnostics == expected.stroke_diagnostics


def test_real_snapshot_pen_chain_applies_shared_endpoint_correction() -> None:
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, min_bi_len=6)
    comparison = compare_with_czsc_reference(result)

    assert len(result.strokes) == 26
    assert len(result.unfinished_bars) == 57
    assert comparison.merged_match
    assert comparison.fractal_match
    assert comparison.unfinished_match
    assert comparison.stroke_match_count == 23
    assert not comparison.stroke_match
    assert comparison.unfinished_match_count == 57

    assert validate_stroke_chain(result.strokes, min_bi_len=6) == ()

    first = result.strokes[0]
    assert first.direction is StrokeDirection.UP
    assert first.start_dt.isoformat() == "2019-10-14T16:00:00+00:00"
    assert first.end_dt.isoformat() == "2019-10-15T00:00:00+00:00"
    assert first.length == 8


def test_later_lower_bottom_replaces_stale_shared_endpoint() -> None:
    """回归：旧共享底之后出现更低底时，两侧笔必须共同迁移到新底。"""
    values = [
        (9, 7),
        (12, 10),  # 顶 A
        (10, 8),
        (9, 7),
        (8, 6),
        (7, 5),
        (6.5, 4.5),
        (6, 4),  # 旧底 B1
        (8, 6),
        (9, 7),
        (10, 8),
        (11, 9),
        (12, 10),
        (14, 12),  # 中间顶 C，先形成 B1 -> C
        (11, 9),
        (5, 3),  # 后续更低底 B2
        (9, 7),
        (10, 8),
        (11, 9),
        (12, 10),
        (13, 11),
        (16, 14),  # 新顶 D
        (14, 12),
    ]
    bars = [rb(i, high, low) for i, (high, low) in enumerate(values)]
    result = analyze_bars(bars, min_bi_len=6)

    assert [
        (stroke.start_dt.hour, stroke.end_dt.hour, stroke.direction)
        for stroke in result.strokes
    ] == [
        (1, 15, StrokeDirection.DOWN),
        (15, 21, StrokeDirection.UP),
    ]
    assert result.strokes[0].end_value == 3
    assert result.strokes[1].start_value == 3
    assert any(x.code == "SHARED_ENDPOINT_REPLACED" for x in result.stroke_diagnostics)
    assert validate_stroke_chain(result.strokes, min_bi_len=6) == ()

    # 冻结的旧状态机正好复现用户发现的问题：仍把旧底 7 作为共享端点。
    comparison = compare_with_czsc_reference(result)
    assert not comparison.stroke_match
