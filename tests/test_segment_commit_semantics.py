from __future__ import annotations

from dataclasses import replace

from chan_monitor.chart import segment_evidence_frame, segments_frame
from chan_monitor.data import demo_bars
from chan_monitor.engine import StructureState, analyze_bars
from chan_monitor.segments import (
    SegmentMode,
    SegmentValidationTarget,
    validate_segment_chain,
)
from chan_monitor.trading_points import _segment_confirmation_dt


def test_committed_chain_validator_understands_stable_prefix_semantics() -> None:
    result = analyze_bars(
        demo_bars(5000, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )

    issues = validate_segment_chain(
        result.segments,
        result.strokes,
        mode=result.segment_mode,
        evidence=result.segment_evidence,
        validation_target=SegmentValidationTarget.COMMITTED,
        stable_stroke_count=len(result.stable_strokes),
    )

    assert issues == ()
    assert result.segment_evidence[-1].confirmed_at_position == len(result.stable_strokes) - 1


def test_each_formal_segment_records_the_actual_commit_bar() -> None:
    bars = demo_bars(1000, symbol="BTCUSDT", interval="5m")
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    previous_count = 0

    for position, bar in enumerate(bars):
        state.update(bar)
        newly_committed = state.evidence[previous_count:]
        for item in newly_committed:
            assert item.committed_at == bar.close_time
            assert item.committed_at_bar_position == position
        previous_count = len(state.evidence)

    assert state.evidence
    assert all(item.committed_at is not None for item in state.evidence)
    assert all(item.committed_at_bar_position is not None for item in state.evidence)
    assert [item.committed_at for item in state.evidence] == sorted(
        item.committed_at for item in state.evidence
    )
    assert [item.committed_at_bar_position for item in state.evidence] == sorted(
        item.committed_at_bar_position for item in state.evidence
    )


def test_committed_validator_rejects_missing_commit_timestamp() -> None:
    result = analyze_bars(
        demo_bars(600, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )
    broken = (
        replace(
            result.segment_evidence[0],
            committed_at=None,
            committed_at_bar_position=None,
        ),
    ) + result.segment_evidence[1:]

    issues = validate_segment_chain(
        result.segments,
        result.strokes,
        evidence=broken,
        validation_target=SegmentValidationTarget.COMMITTED,
        stable_stroke_count=len(result.stable_strokes),
    )

    assert any(item.code == "SEGMENT_COMMIT_TIME_MISSING" for item in issues)


def test_trading_point_uses_formal_commit_time_not_structural_evidence_time() -> None:
    result = analyze_bars(
        demo_bars(600, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )
    evidence = result.segment_evidence[0]
    structural_time = result.strokes[evidence.confirmed_at_position].end_dt

    actual = _segment_confirmation_dt(
        result.segments[0].index,
        result.segments,
        {evidence.segment_index: evidence},
        result.strokes,
    )

    assert evidence.committed_at is not None
    assert actual == evidence.committed_at
    assert actual > structural_time


def test_segment_exports_include_real_commit_metadata() -> None:
    result = analyze_bars(
        demo_bars(600, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )

    segment_rows = segments_frame(result)
    evidence_rows = segment_evidence_frame(result)

    assert segment_rows["正式提交时间"].notna().all()
    assert segment_rows["正式提交原始K位置"].notna().all()
    assert evidence_rows["正式提交时间"].notna().all()
    assert evidence_rows["正式提交原始K位置"].notna().all()
