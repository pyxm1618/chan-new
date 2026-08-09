from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from .models import (
    MacdAnchor,
    RawBar,
    Segment,
    SegmentCentralZone,
    SegmentEvidence,
    Stroke,
    StrokeDirection,
    TradingPoint,
    TradingPointDiagnostic,
)
from .single_level_trading_points import (
    detect_trading_points as _detect_trading_points,
    validate_trading_points as _validate_trading_points,
)
from .trading_points import TradingPointDetectionResult

_EPS = 1e-9


def detect_trading_points(
    segments: Sequence[Segment],
    segment_central_zones: Sequence[SegmentCentralZone],
    *,
    raw_bars: Sequence[RawBar] = (),
    segment_evidence: Sequence[SegmentEvidence] = (),
    segment_commit_times: Mapping[str, datetime] | None = None,
    strokes: Sequence[Stroke] = (),
    macd_history_anchored: bool = False,
    macd_anchor: MacdAnchor | None = None,
) -> TradingPointDetectionResult:
    """Formal fixed-level detector with fail-closed Segment qualification.

    The calculation core deliberately ignores ``segment.strokes`` as lower-level
    trading-point evidence. The formal boundary verifies both intrinsic Segment
    structure and provenance. Every supplied Segment must have identity-bound,
    committed ``SegmentEvidence`` from the Segment engine. A caller-provided
    commit-time mapping is retained only as a compatibility parameter and is not
    accepted as a formal credential.
    """
    del segment_commit_times
    values = tuple(segments)
    evidence = tuple(segment_evidence)
    issue = _first_segment_structure_issue(values)
    if issue is None:
        issue = _first_segment_provenance_issue(values, evidence)
    if issue is not None:
        return TradingPointDetectionResult(
            points=(),
            candidates=(),
            trend_divergences=(),
            diagnostics=(issue,),
        )
    return _detect_trading_points(
        values,
        segment_central_zones,
        raw_bars=raw_bars,
        segment_evidence=evidence,
        # Formal commit times are derived exclusively from validated committed
        # SegmentEvidence. An arbitrary mapping is not a provenance authority.
        segment_commit_times=None,
        strokes=strokes,
        macd_history_anchored=macd_history_anchored,
        macd_anchor=macd_anchor,
    )


def validate_trading_points(
    points: Sequence[TradingPoint],
    segments: Sequence[Segment],
    zones: Sequence[SegmentCentralZone],
    *,
    raw_bars: Sequence[RawBar] = (),
    segment_evidence: Sequence[SegmentEvidence] = (),
    segment_commit_times: Mapping[str, datetime] | None = None,
    strokes: Sequence[Stroke] = (),
    macd_history_anchored: bool = True,
    macd_anchor: MacdAnchor | None = None,
) -> tuple[TradingPointDiagnostic, ...]:
    del segment_commit_times
    values = tuple(segments)
    evidence = tuple(segment_evidence)
    issue = _first_segment_structure_issue(values)
    if issue is None:
        issue = _first_segment_provenance_issue(values, evidence)
    if issue is not None:
        return (issue,)
    return _validate_trading_points(
        points,
        values,
        zones,
        raw_bars=raw_bars,
        segment_evidence=evidence,
        segment_commit_times=None,
        strokes=strokes,
        macd_history_anchored=macd_history_anchored,
        macd_anchor=macd_anchor,
    )


def _first_segment_structure_issue(
    segments: tuple[Segment, ...],
) -> TradingPointDiagnostic | None:
    for position, segment in enumerate(segments):
        strokes = tuple(segment.strokes)
        if len(strokes) < 3 or len(strokes) % 2 == 0:
            return _invalid(
                segment,
                f"第 {position} 条 Segment 含 {len(strokes)} 笔；正式线段必须至少三笔且为奇数笔",
            )

        expected_direction = strokes[0].direction
        expected_marks = (
            ("D", "G")
            if expected_direction is StrokeDirection.UP
            else ("G", "D")
        )
        if segment.direction is not expected_direction:
            return _invalid(segment, f"第 {position} 条 Segment 方向与首笔方向不一致")
        if (segment.fx_a.mark.value, segment.fx_b.mark.value) != expected_marks:
            return _invalid(segment, f"第 {position} 条 Segment 方向与形式端点分型不一致")
        if not _same_endpoint(segment.fx_a, strokes[0].fx_a) or not _same_endpoint(
            segment.fx_b, strokes[-1].fx_b
        ):
            return _invalid(segment, f"第 {position} 条 Segment 形式端点与内部笔链端点不一致")
        if any(stroke.symbol != segment.symbol for stroke in strokes):
            return _invalid(segment, f"第 {position} 条 Segment 内部笔 symbol 与线段不一致")

        for i, stroke in enumerate(strokes):
            if i:
                previous = strokes[i - 1]
                if previous.direction is stroke.direction:
                    return _invalid(segment, f"第 {position} 条 Segment 内部笔方向未交替")
                if not _same_endpoint(previous.fx_b, stroke.fx_a):
                    return _invalid(segment, f"第 {position} 条 Segment 内部笔没有共享端点")

        first_three = strokes[:3]
        if max(stroke.low for stroke in first_three) > min(
            stroke.high for stroke in first_three
        ) + _EPS:
            return _invalid(segment, f"第 {position} 条 Segment 首三笔没有共同重叠区间")

        if position:
            previous_segment = segments[position - 1]
            if previous_segment.direction is segment.direction:
                return _invalid(segment, f"第 {position - 1}、{position} 条 Segment 方向未交替")
            if not _same_endpoint(previous_segment.fx_b, segment.fx_a):
                return _invalid(segment, f"第 {position - 1}、{position} 条 Segment 没有共享端点")
    return None


def _first_segment_provenance_issue(
    segments: tuple[Segment, ...],
    evidence: tuple[SegmentEvidence, ...],
) -> TradingPointDiagnostic | None:
    """Require committed Segment-engine evidence bound to every formal Segment."""
    if len(evidence) != len(segments):
        return TradingPointDiagnostic(
            code="FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING",
            message=(
                "正式单级别买卖点要求每条 Segment 都有对应的 SegmentEvidence；"
                f"线段 {len(segments)} 条，证据 {len(evidence)} 条"
            ),
            dt=segments[0].start_dt if segments else None,
        )

    for position, (segment, item) in enumerate(zip(segments, evidence)):
        if not item.matches_segment(segment):
            return TradingPointDiagnostic(
                code="FORMAL_SEGMENT_EVIDENCE_IDENTITY_MISMATCH",
                message=f"第 {position} 条 SegmentEvidence 与 Segment 不匹配，拒绝授予正式身份",
                dt=segment.start_dt,
            )
        if not item.is_committed:
            return TradingPointDiagnostic(
                code="FORMAL_SEGMENT_EVIDENCE_UNCOMMITTED",
                message=f"第 {position} 条 SegmentEvidence 尚未 committed_at，不能用于正式买卖点",
                dt=segment.start_dt,
            )
    return None


def _same_endpoint(left, right) -> bool:
    return (
        left.dt == right.dt
        and left.mark is right.mark
        and abs(float(left.value) - float(right.value)) <= _EPS
    )


def _invalid(segment: Segment, message: str) -> TradingPointDiagnostic:
    return TradingPointDiagnostic(
        code="FORMAL_SEGMENT_STRUCTURE_INVALID",
        message=message,
        dt=segment.start_dt,
    )
