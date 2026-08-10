from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .models import (
    MacdAnchor,
    RawBar,
    Segment,
    SegmentCentralZone,
    SegmentEvidence,
    Stroke,
    StrokeDirection,
    TradingPoint,
    TradingPointCandidate,
    TradingPointDiagnostic,
    TradingPointStatus,
    TradingPointType,
    TrendDivergence,
)
from .trading_points import (
    TradingPointDetectionResult,
    _directional_macd_area,
    _formal_segment_commit_times,
    _macd_histogram,
    _raw_bars_from_segments,
    _segment_confirmation_dt,
)

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class _ZoneView:
    index: int
    start: int
    end: int
    zg: float
    zd: float
    gg: float
    dd: float


class SingleLevelTrendDivergence(TrendDivergence):
    """Same-level divergence evidence with no recursive sublevel requirement."""

    __slots__ = ()

    @property
    def is_valid(self) -> bool:
        return (
            self.strict_trend
            and self.price_extreme
            and self.macd_divergence
            and self.macd_state_exact
        )


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
    """Detect single-level B1/B2/B3 and S1/S2/S3 from segment structure.

    Production semantics in this phase are deliberately non-recursive. Formal
    points consume confirmed same-level segments and confirmed segment central
    zones only. ``strokes`` remains in the signature for API compatibility but
    is never inspected as lower-timeframe evidence.
    """

    del strokes
    values = tuple(segments)
    zones = tuple(segment_central_zones)
    bars = tuple(raw_bars or _raw_bars_from_segments(values))
    commit_times = _formal_segment_commit_times(
        values,
        segment_evidence=segment_evidence,
        explicit=segment_commit_times,
    )
    missing_commit_indexes = tuple(
        segment.index for segment in values if segment.index not in commit_times
    )
    if missing_commit_indexes:
        return TradingPointDetectionResult(
            points=(),
            candidates=(),
            trend_divergences=(),
            diagnostics=(
                TradingPointDiagnostic(
                    code="FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING",
                    message=(
                        "单级别买卖点拒绝使用缺少正式提交证据的线段；缺失线段："
                        + ", ".join(str(index) for index in missing_commit_indexes)
                    ),
                    dt=values[0].start_dt if values else None,
                ),
            ),
        )

    macd = _macd_histogram(
        bars,
        history_anchored=macd_history_anchored,
        anchor=macd_anchor,
    )
    diagnostics: list[TradingPointDiagnostic] = []
    if macd.issue is not None:
        diagnostics.append(
            TradingPointDiagnostic(
                code="MACD_STREAM_NOT_EXACT",
                message=macd.issue,
                dt=bars[0].open_time if bars else None,
            )
        )

    first_points, first_candidates, divergences = _detect_first_points(
        values,
        zones,
        macd_histogram=macd.histogram,
        macd_exact=macd.exact,
        commit_times=commit_times,
    )
    points: list[TradingPoint] = list(first_points)
    candidates: list[TradingPointCandidate] = list(first_candidates)

    for point in first_points:
        diagnostics.append(
            TradingPointDiagnostic(
                point.point_type.value,
                (
                    f"{point.label}：本级别线段中枢严格趋势成立，"
                    "最终离开线段创新极值且同方向 MACD 柱面积背驰"
                ),
                point.dt,
            )
        )

    _append_second_points(
        values,
        first_points,
        commit_times=commit_times,
        points=points,
        candidates=candidates,
        diagnostics=diagnostics,
    )
    _append_third_points(
        values,
        zones,
        commit_times=commit_times,
        points=points,
        candidates=candidates,
        diagnostics=diagnostics,
    )

    unique: dict[tuple[TradingPointType, datetime, int], TradingPoint] = {}
    for point in points:
        unique[(point.point_type, point.dt, point.segment_index)] = point
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.dt, item.point_type.value, item.segment_index),
        )
    )
    fallback_dt = values[0].start_dt if values else datetime.min
    ordered_candidates = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.dt or fallback_dt,
                item.point_type.value,
                item.segment_index if item.segment_index is not None else -1,
                item.status.value,
            ),
        )
    )
    return TradingPointDetectionResult(
        points=ordered,
        candidates=ordered_candidates,
        trend_divergences=tuple(divergences),
        diagnostics=tuple(diagnostics),
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
    """Validate saved single-level points by deterministic formal recalculation."""

    issues: list[TradingPointDiagnostic] = []
    values = tuple(segments)
    index_map = {segment.index: segment for segment in values}
    try:
        recalculated = detect_trading_points(
            values,
            zones,
            raw_bars=raw_bars,
            segment_evidence=segment_evidence,
            segment_commit_times=segment_commit_times,
            strokes=strokes,
            macd_history_anchored=macd_history_anchored,
            macd_anchor=macd_anchor,
        )
    except (TypeError, ValueError) as exc:
        recalculated = None
        issues.append(
            TradingPointDiagnostic(
                code="TRADING_POINT_FORMAL_RECALCULATION_FAILED",
                message=f"无法按单级别正式结构复算买卖点：{exc}",
                dt=points[0].dt if points else (values[0].start_dt if values else None),
            )
        )

    expected = (
        {
            (item.point_type, item.dt, item.segment_index): item
            for item in recalculated.points
        }
        if recalculated is not None
        else {}
    )
    if recalculated is not None:
        for diagnostic in recalculated.diagnostics:
            if diagnostic.code == "FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING":
                issues.append(
                    TradingPointDiagnostic(
                        code="TRADING_POINT_COMMIT_EVIDENCE_INVALID",
                        message=diagnostic.message,
                        dt=diagnostic.dt,
                    )
                )

    seen: set[tuple[TradingPointType, datetime, int]] = set()
    for point in points:
        key = (point.point_type, point.dt, point.segment_index)
        if key in seen:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_DUPLICATE",
                    f"重复点位 {key}",
                    point.dt,
                )
            )
        seen.add(key)

        segment = index_map.get(point.segment_index)
        if segment is None:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_SEGMENT_MISSING",
                    f"{point.label} 对应线段不存在",
                    point.dt,
                )
            )
            continue
        if segment.end_dt != point.dt or abs(segment.end_value - point.price) > _EPS:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_ENDPOINT_MISMATCH",
                    f"{point.label} 没有落在线段终点",
                    point.dt,
                )
            )
        expected_direction = StrokeDirection.DOWN if point.is_buy else StrokeDirection.UP
        if segment.direction is not expected_direction:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_DIRECTION_INVALID",
                    f"{point.label} 的线段方向错误",
                    point.dt,
                )
            )
        if point.confirmed_at_dt < point.dt:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_FUTURE_TIME_INVALID",
                    f"{point.label} 的确认时间早于结构时间",
                    point.dt,
                )
            )

        expected_point = expected.get(key)
        if recalculated is None:
            continue
        if expected_point is None:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_NOT_IN_FORMAL_RECALCULATION",
                    f"{point.label} 无法由当前单级别正式结构重新计算得到",
                    point.dt,
                )
            )
            continue
        if point.confirmed_at_dt != expected_point.confirmed_at_dt:
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_CONFIRM_TIME_MISMATCH",
                    (
                        f"{point.label} 的确认时间不等于正式提交账本复算时间："
                        f"{point.confirmed_at_dt.isoformat()} != "
                        f"{expected_point.confirmed_at_dt.isoformat()}"
                    ),
                    point.dt,
                )
            )
        if (
            point.evidence_kind != expected_point.evidence_kind
            or point.evidence != expected_point.evidence
            or point.zone_index != expected_point.zone_index
            or point.related_segment_indexes != expected_point.related_segment_indexes
            or point.source_level != expected_point.source_level
        ):
            issues.append(
                TradingPointDiagnostic(
                    "TRADING_POINT_EVIDENCE_MISMATCH",
                    f"{point.label} 的单级别证据与正式复算结果不一致",
                    point.dt,
                )
            )

    return tuple(issues)


def _detect_first_points(
    values: tuple[Segment, ...],
    zones: tuple[SegmentCentralZone, ...],
    *,
    macd_histogram: Mapping[datetime, float],
    macd_exact: bool,
    commit_times: Mapping[int, datetime],
) -> tuple[
    tuple[TradingPoint, ...],
    tuple[TradingPointCandidate, ...],
    tuple[TrendDivergence, ...],
]:
    zone_views = _zone_views(zones, values)
    points: list[TradingPoint] = []
    candidates: list[TradingPointCandidate] = []
    divergences: list[TrendDivergence] = []

    for previous, last in zip(zone_views, zone_views[1:]):
        strict_down = last.gg < previous.dd - _EPS
        strict_up = last.dd > previous.gg + _EPS
        core_down = last.zg < previous.zd - _EPS
        core_up = last.zd > previous.zg + _EPS

        if strict_down:
            direction = StrokeDirection.DOWN
            point_type = TradingPointType.BUY1
        elif strict_up:
            direction = StrokeDirection.UP
            point_type = TradingPointType.SELL1
        else:
            if core_down or core_up:
                point_type = TradingPointType.BUY1 if core_down else TradingPointType.SELL1
                candidates.append(
                    TradingPointCandidate(
                        point_type=point_type,
                        status=TradingPointStatus.REJECTED,
                        dt=None,
                        price=None,
                        segment_index=None,
                        reason=(
                            "线段中枢核心区虽分离，但 GG/DD 波动区间仍重叠；"
                            "不按严格同级别趋势输出一类点"
                        ),
                        checks=(
                            ("前中枢GG", f"{previous.gg:.12g}"),
                            ("前中枢DD", f"{previous.dd:.12g}"),
                            ("后中枢GG", f"{last.gg:.12g}"),
                            ("后中枢DD", f"{last.dd:.12g}"),
                            ("严格趋势", "失败"),
                        ),
                        zone_index=last.index,
                    )
                )
            continue

        entry_pos = _find_entry_position(values, previous, last, direction)
        exit_pos = _find_exit_position(values, last, direction)
        if entry_pos is None or exit_pos is None or exit_pos <= entry_pos:
            candidates.append(
                TradingPointCandidate(
                    point_type=point_type,
                    status=TradingPointStatus.PENDING,
                    dt=None,
                    price=None,
                    segment_index=None,
                    reason="严格同级别趋势已成立，但连接段 b 或最终离开段 c 尚未完整确认",
                    checks=(
                        ("前中枢", str(previous.index)),
                        ("后中枢", str(last.index)),
                        ("比较段b", str(entry_pos)),
                        ("离开段c", str(exit_pos)),
                    ),
                    zone_index=last.index,
                )
            )
            continue

        entry = values[entry_pos]
        exit_segment = values[exit_pos]
        prior_units = values[entry_pos:exit_pos]
        if direction is StrokeDirection.DOWN:
            previous_extreme = min(segment.low for segment in prior_units)
            price_extreme = exit_segment.end_value < previous_extreme - _EPS
        else:
            previous_extreme = max(segment.high for segment in prior_units)
            price_extreme = exit_segment.end_value > previous_extreme + _EPS

        entry_area = _directional_macd_area(entry, direction, dict(macd_histogram))
        exit_area = _directional_macd_area(exit_segment, direction, dict(macd_histogram))
        macd_divergence = entry_area > _EPS and exit_area < entry_area - _EPS

        divergence = SingleLevelTrendDivergence(
            symbol=exit_segment.symbol,
            level="segment",
            direction=direction,
            previous_zone_index=previous.index,
            last_zone_index=last.index,
            entry_unit_index=entry.index,
            exit_unit_index=exit_segment.index,
            entry_macd_area=entry_area,
            exit_macd_area=exit_area,
            entry_power=float(entry.power),
            exit_power=float(exit_segment.power),
            entry_start_dt=entry.start_dt,
            entry_end_dt=entry.end_dt,
            exit_start_dt=exit_segment.start_dt,
            exit_end_dt=exit_segment.end_dt,
            price_extreme=price_extreme,
            macd_divergence=macd_divergence,
            macd_state_exact=macd_exact,
            strict_trend=True,
            sublevel_third_point=False,
            sublevel_zone_count=0,
        )
        divergences.append(divergence)
        checks = (
            ("严格趋势GG/DD", "通过"),
            ("前中枢GG/DD", f"{previous.gg:.12g}/{previous.dd:.12g}"),
            ("后中枢GG/DD", f"{last.gg:.12g}/{last.dd:.12g}"),
            ("b/c同向", "通过"),
            ("c创趋势新极值", "通过" if price_extreme else "失败"),
            ("MACD状态精确", "通过" if macd_exact else "失败"),
            ("方向MACD柱面积背驰", "通过" if macd_divergence else "失败"),
            ("b方向MACD面积", f"{entry_area:.12g}"),
            ("c方向MACD面积", f"{exit_area:.12g}"),
        )

        if not price_extreme:
            candidates.append(
                TradingPointCandidate(
                    point_type=point_type,
                    status=TradingPointStatus.REJECTED,
                    dt=exit_segment.end_dt,
                    price=exit_segment.end_value,
                    segment_index=exit_segment.index,
                    reason="严格同级别趋势成立，但最终离开段 c 没有创出趋势新极值",
                    checks=checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_segment.index),
                )
            )
            continue
        if not macd_exact:
            candidates.append(
                TradingPointCandidate(
                    point_type=point_type,
                    status=TradingPointStatus.PENDING,
                    dt=exit_segment.end_dt,
                    price=exit_segment.end_value,
                    segment_index=exit_segment.index,
                    reason=(
                        "同级别趋势与价格新极值成立，但 MACD 状态不精确；"
                        "需真实历史起点或 MacdAnchor"
                    ),
                    checks=checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_segment.index),
                )
            )
            continue
        if not macd_divergence:
            candidates.append(
                TradingPointCandidate(
                    point_type=point_type,
                    status=TradingPointStatus.REJECTED,
                    dt=exit_segment.end_dt,
                    price=exit_segment.end_value,
                    segment_index=exit_segment.index,
                    reason="同级别趋势成立，但 c 的同方向 MACD 柱面积没有小于 b",
                    checks=checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_segment.index),
                )
            )
            continue

        point = TradingPoint(
            symbol=exit_segment.symbol,
            point_type=point_type,
            dt=exit_segment.end_dt,
            price=exit_segment.end_value,
            segment_index=exit_segment.index,
            confirmed_at_dt=_segment_confirmation_dt(exit_segment.index, commit_times),
            evidence_kind="SINGLE_LEVEL_TREND_MACD_DIVERGENCE",
            evidence=(
                ("级别", "segment"),
                ("模式", "single-level"),
                ("严格趋势规则", "后GG<前DD" if direction is StrokeDirection.DOWN else "后DD>前GG"),
                ("前中枢", str(previous.index)),
                ("最后中枢", str(last.index)),
                ("前中枢GG", f"{previous.gg:.12g}"),
                ("前中枢DD", f"{previous.dd:.12g}"),
                ("后中枢GG", f"{last.gg:.12g}"),
                ("后中枢DD", f"{last.dd:.12g}"),
                ("比较线段b", str(entry.index)),
                ("离开线段c", str(exit_segment.index)),
                ("MACD面积方向", "负柱" if direction is StrokeDirection.DOWN else "正柱"),
                ("b方向MACD面积", f"{entry_area:.12g}"),
                ("c方向MACD面积", f"{exit_area:.12g}"),
                ("MACD状态", "精确"),
            ),
            zone_index=last.index,
            related_segment_indexes=(entry.index, exit_segment.index),
            source_level="segment",
        )
        points.append(point)
        candidates.append(
            TradingPointCandidate(
                point_type=point_type,
                status=TradingPointStatus.CONFIRMED,
                dt=point.dt,
                price=point.price,
                segment_index=point.segment_index,
                reason=(
                    "两个本级别线段中枢满足严格趋势关系，c 创新极值且"
                    "同方向 MACD 柱面积小于 b"
                ),
                checks=checks,
                zone_index=last.index,
                related_segment_indexes=point.related_segment_indexes,
            )
        )

    return tuple(points), tuple(candidates), tuple(divergences)


def _append_second_points(
    values: tuple[Segment, ...],
    first_points: tuple[TradingPoint, ...],
    *,
    commit_times: Mapping[int, datetime],
    points: list[TradingPoint],
    candidates: list[TradingPointCandidate],
    diagnostics: list[TradingPointDiagnostic],
) -> None:
    for first in first_points:
        first_pos = _position_by_index(values, first.segment_index)
        if first_pos is None:
            continue
        expected_type = (
            TradingPointType.BUY2
            if first.point_type is TradingPointType.BUY1
            else TradingPointType.SELL2
        )
        if first_pos + 2 >= len(values):
            candidates.append(
                TradingPointCandidate(
                    point_type=expected_type,
                    status=TradingPointStatus.PENDING,
                    dt=None,
                    price=None,
                    segment_index=None,
                    reason="一类点之后尚未完成本级别反向段与第一次回试段",
                    checks=(("前置一类点", first.point_type.value),),
                    related_segment_indexes=(first.segment_index,),
                )
            )
            continue

        rebound = values[first_pos + 1]
        retrace = values[first_pos + 2]
        if first.point_type is TradingPointType.BUY1:
            direction_ok = (
                rebound.direction is StrokeDirection.UP
                and retrace.direction is StrokeDirection.DOWN
            )
            price_ok = retrace.end_value >= first.price - _EPS
        else:
            direction_ok = (
                rebound.direction is StrokeDirection.DOWN
                and retrace.direction is StrokeDirection.UP
            )
            price_ok = retrace.end_value <= first.price + _EPS

        checks = (
            ("本级别方向序列", "通过" if direction_ok else "失败"),
            ("第一次回试不破一类点极值", "通过" if price_ok else "失败"),
        )
        if not (direction_ok and price_ok):
            candidates.append(
                TradingPointCandidate(
                    point_type=expected_type,
                    status=TradingPointStatus.REJECTED,
                    dt=retrace.end_dt,
                    price=retrace.end_value,
                    segment_index=retrace.index,
                    reason="二类点要求本级别第一次回试方向正确且不破一类点极值",
                    checks=checks,
                    related_segment_indexes=(
                        first.segment_index,
                        rebound.index,
                        retrace.index,
                    ),
                )
            )
            continue

        point = TradingPoint(
            symbol=retrace.symbol,
            point_type=expected_type,
            dt=retrace.end_dt,
            price=retrace.end_value,
            segment_index=retrace.index,
            confirmed_at_dt=_segment_confirmation_dt(retrace.index, commit_times),
            evidence_kind="SINGLE_LEVEL_FIRST_RETRACE",
            evidence=(
                ("模式", "single-level"),
                ("前置一类点", first.point_type.value),
                ("前置价格", f"{first.price:.12g}"),
                ("反向线段", str(rebound.index)),
                ("第一次回试线段", str(retrace.index)),
                ("不破一类点极值", "是"),
            ),
            related_segment_indexes=(first.segment_index, rebound.index, retrace.index),
            source_level="segment",
        )
        points.append(point)
        candidates.append(
            TradingPointCandidate(
                point_type=expected_type,
                status=TradingPointStatus.CONFIRMED,
                dt=point.dt,
                price=point.price,
                segment_index=point.segment_index,
                reason="本级别一类点后的第一次回试未破一类点极值",
                checks=checks,
                related_segment_indexes=point.related_segment_indexes,
            )
        )
        diagnostics.append(
            TradingPointDiagnostic(
                expected_type.value,
                f"{point.label}：本级别一类点后的第一次回试未破极值",
                point.dt,
            )
        )


def _append_third_points(
    values: tuple[Segment, ...],
    zones: tuple[SegmentCentralZone, ...],
    *,
    commit_times: Mapping[int, datetime],
    points: list[TradingPoint],
    candidates: list[TradingPointCandidate],
    diagnostics: list[TradingPointDiagnostic],
) -> None:
    for zone in zones:
        scan_start = max(zone.start_position + 2, 0)
        departure_pos: int | None = None
        expected: TradingPointType | None = None
        for pos in range(scan_start, min(len(values), zone.end_position + 2)):
            segment = values[pos]
            if (
                segment.direction is StrokeDirection.UP
                and segment.end_value > zone.zg + _EPS
            ):
                departure_pos = pos
                expected = TradingPointType.BUY3
                break
            if (
                segment.direction is StrokeDirection.DOWN
                and segment.end_value < zone.zd - _EPS
            ):
                departure_pos = pos
                expected = TradingPointType.SELL3
                break
        if departure_pos is None or expected is None:
            continue

        departure = values[departure_pos]
        pullback_pos = departure_pos + 1
        if pullback_pos >= len(values):
            candidates.append(
                TradingPointCandidate(
                    point_type=expected,
                    status=TradingPointStatus.PENDING,
                    dt=departure.end_dt,
                    price=departure.end_value,
                    segment_index=departure.index,
                    reason="离开线段中枢后尚无已确认的本级别第一次反向回试线段",
                    checks=(
                        ("中枢", str(zone.index)),
                        ("离开线段", str(departure.index)),
                    ),
                    zone_index=zone.index,
                    related_segment_indexes=(departure.index,),
                )
            )
            continue

        pullback = values[pullback_pos]
        if expected is TradingPointType.BUY3:
            direction_ok = pullback.direction is StrokeDirection.DOWN
            boundary_ok = pullback.low >= zone.zg - _EPS
            distance = pullback.low - zone.zg
        else:
            direction_ok = pullback.direction is StrokeDirection.UP
            boundary_ok = pullback.high <= zone.zd + _EPS
            distance = zone.zd - pullback.high

        checks = (
            ("离开方向", "通过"),
            ("第一次反向回试", "通过" if direction_ok else "失败"),
            ("不返回线段中枢", "通过" if boundary_ok else "失败"),
        )
        if not (direction_ok and boundary_ok):
            candidates.append(
                TradingPointCandidate(
                    point_type=expected,
                    status=TradingPointStatus.REJECTED,
                    dt=pullback.end_dt,
                    price=pullback.end_value,
                    segment_index=pullback.index,
                    reason="第一次回试重新进入线段中枢，或回试方向不正确",
                    checks=checks,
                    zone_index=zone.index,
                    related_segment_indexes=(departure.index, pullback.index),
                )
            )
            continue

        point = TradingPoint(
            symbol=pullback.symbol,
            point_type=expected,
            dt=pullback.end_dt,
            price=pullback.end_value,
            segment_index=pullback.index,
            confirmed_at_dt=_segment_confirmation_dt(pullback.index, commit_times),
            evidence_kind="SINGLE_LEVEL_ZONE_DEPARTURE_RETEST",
            evidence=(
                ("模式", "single-level"),
                ("线段中枢", str(zone.index)),
                ("ZD", f"{zone.zd:.12g}"),
                ("ZG", f"{zone.zg:.12g}"),
                ("离开线段", str(departure.index)),
                ("第一次回试线段", str(pullback.index)),
                ("距中枢边界", f"{distance:.12g}"),
            ),
            zone_index=zone.index,
            related_segment_indexes=(departure.index, pullback.index),
            source_level="segment",
        )
        points.append(point)
        candidates.append(
            TradingPointCandidate(
                point_type=expected,
                status=TradingPointStatus.CONFIRMED,
                dt=point.dt,
                price=point.price,
                segment_index=point.segment_index,
                reason="离开本级别线段中枢后的第一次反向回试未返回中枢",
                checks=checks,
                zone_index=zone.index,
                related_segment_indexes=point.related_segment_indexes,
            )
        )
        diagnostics.append(
            TradingPointDiagnostic(
                expected.value,
                (
                    f"{point.label}：线段中枢 {zone.index} 离开后的第一次回试"
                    f"未返回 [{zone.zd:.12g}, {zone.zg:.12g}]"
                ),
                point.dt,
            )
        )


def _zone_views(
    zones: tuple[SegmentCentralZone, ...],
    values: tuple[Segment, ...],
) -> tuple[_ZoneView, ...]:
    identity = {id(segment): position for position, segment in enumerate(values)}
    by_index = {segment.index: position for position, segment in enumerate(values)}
    result: list[_ZoneView] = []
    for fallback_index, zone in enumerate(zones):
        members = tuple(zone.segments)
        if not members:
            continue
        if zone.start_position >= 0:
            start = int(zone.start_position)
            end = int(zone.end_position)
        else:
            start = identity.get(id(members[0]), by_index.get(members[0].index, -1))
            end = identity.get(id(members[-1]), by_index.get(members[-1].index, -1))
        if start < 0 or end < start:
            continue
        trend_members = tuple(zone.trend_segments) or members
        if len(trend_members) < 3:
            continue
        result.append(
            _ZoneView(
                index=zone.index if zone.index >= 0 else fallback_index,
                start=start,
                end=end,
                zg=float(zone.zg),
                zd=float(zone.zd),
                gg=max(float(segment.high) for segment in trend_members),
                dd=min(float(segment.low) for segment in trend_members),
            )
        )
    return tuple(result)


def _find_entry_position(
    values: tuple[Segment, ...],
    previous: _ZoneView,
    last: _ZoneView,
    direction: StrokeDirection,
) -> int | None:
    lo = max(0, previous.end)
    hi = min(len(values) - 1, last.start - 1)
    for pos in range(hi, lo - 1, -1):
        segment = values[pos]
        if segment.direction is not direction:
            continue
        if direction is StrokeDirection.DOWN:
            if segment.start_value > last.zg + _EPS and segment.end_value <= last.zg + _EPS:
                return pos
        elif segment.start_value < last.zd - _EPS and segment.end_value >= last.zd - _EPS:
            return pos
    return None


def _find_exit_position(
    values: tuple[Segment, ...],
    zone: _ZoneView,
    direction: StrokeDirection,
) -> int | None:
    pos = zone.end
    if pos < 0 or pos >= len(values):
        return None
    segment = values[pos]
    if segment.direction is not direction:
        return None
    if direction is StrokeDirection.DOWN:
        return (
            pos
            if segment.start_value >= zone.zd - _EPS
            and segment.end_value < zone.zd - _EPS
            else None
        )
    return (
        pos
        if segment.start_value <= zone.zg + _EPS
        and segment.end_value > zone.zg + _EPS
        else None
    )


def _position_by_index(values: tuple[Segment, ...], index: int) -> int | None:
    for position, segment in enumerate(values):
        if segment.index == index:
            return position
    return None
