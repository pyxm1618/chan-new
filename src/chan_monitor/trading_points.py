from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from .bar_stream import next_open_time, raw_bar_fingerprint, validate_bar_stream
from .central_zones import detect_central_zones
from .models import (
    CentralZone,
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
    unique_elements,
)

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class TradingPointDetectionResult:
    points: tuple[TradingPoint, ...]
    candidates: tuple[TradingPointCandidate, ...]
    trend_divergences: tuple[TrendDivergence, ...]
    diagnostics: tuple[TradingPointDiagnostic, ...]

    @property
    def buy_points(self) -> tuple[TradingPoint, ...]:
        return tuple(x for x in self.points if x.is_buy)

    @property
    def sell_points(self) -> tuple[TradingPoint, ...]:
        return tuple(x for x in self.points if not x.is_buy)


@dataclass(frozen=True, slots=True)
class _ZoneView:
    index: int
    start: int
    end: int
    zg: float
    zd: float
    gg: float
    dd: float


@dataclass(frozen=True, slots=True)
class _FirstPointLevelResult:
    points: tuple[TradingPoint, ...]
    candidates: tuple[TradingPointCandidate, ...]
    divergences: tuple[TrendDivergence, ...]


@dataclass(frozen=True, slots=True)
class _MacdComputation:
    histogram: dict[datetime, float]
    exact: bool
    final_anchor: MacdAnchor | None
    issue: str | None = None


@dataclass(frozen=True, slots=True)
class _InternalThirdPoint:
    position: int
    sublevel_zone_count: int


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
    """识别线段操作级别的一、二、三类买卖点。

    本实现明确区分操作级别与次级别：

    * 一买/一卖：操作级别必须已经形成至少两个严格同向、互不重叠的线段中枢，
      连接两中枢的同向走势 b 与最终离开走势 c 方向一致；c 内形成对最后中枢 B
      的次级别三类点、至少包含两个次级别中枢、创出趋势新极值，并且同方向
      MACD 柱面积小于 b。
    * 二买/二卖：操作级别一类点之后的第一次反向回试不破坏一类点极值，并且
      该回试线段的终点必须同时是其内部笔级别走势的一类买卖点。
    * 三买/三卖：一个已完成线段离开固定线段中枢，紧随其后的第一个反向线段
      回试不重新进入中枢；不跌破/不升破边界包含等价触碰。

    只使用已经确认的线段。调用方必须提供覆盖全部输入线段的正式提交证据：
    优先传 ``segment_evidence``，测试或外部持久化系统也可显式传入
    ``segment_commit_times``。显式映射必须以 ``Segment.fingerprint`` 为键，
    不能再用局部 ``segment_index``。缺少任一线段的 committed_at 时，接口安全关闭，
    不会回退到线段端点时间输出 B1/B2/B3/S1/S2/S3。

    图上点位使用 ``dt``，后台通知必须使用 ``confirmed_at_dt``，避免未来函数。
    """
    values = tuple(segments)
    zones = tuple(segment_central_zones)
    bars = tuple(raw_bars or _raw_bars_from_segments(values))
    commit_times = _formal_segment_commit_times(
        values,
        segment_evidence=segment_evidence,
        explicit=segment_commit_times,
    )
    missing_commit_indexes = tuple(x.index for x in values if x.index not in commit_times)
    if missing_commit_indexes:
        return TradingPointDetectionResult(
            points=(),
            candidates=(),
            trend_divergences=(),
            diagnostics=(
                TradingPointDiagnostic(
                    code="FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING",
                    message=(
                        "买卖点接口拒绝使用缺少正式提交证据的线段；缺失线段："
                        + ", ".join(str(x) for x in missing_commit_indexes)
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

    segment_first = _detect_first_points_at_level(
        units=values,
        zones=zones,
        macd=macd,
        level="segment",
        confirmation_fn=lambda pos: _segment_confirmation_dt(
            values[pos].index, commit_times
        ),
        segment_index_fn=lambda pos: values[pos].index,
    )

    points: list[TradingPoint] = list(segment_first.points)
    candidates: list[TradingPointCandidate] = list(segment_first.candidates)
    diagnostics: list[TradingPointDiagnostic] = []
    if macd.issue is not None:
        diagnostics.append(
            TradingPointDiagnostic(
                code="MACD_STREAM_NOT_EXACT",
                message=macd.issue,
                dt=bars[0].open_time if bars else None,
            )
        )

    for point in segment_first.points:
        diagnostics.append(
            TradingPointDiagnostic(
                point.point_type.value,
                f"{point.label}：严格 GG/DD 趋势成立，最终离开 c 内含次级别三类点和至少两个次级别中枢、创新极值且方向 MACD 力度背驰",
                point.dt,
            )
        )

    # 二类点：严格要求回试段内部的笔级别一类点落在同一终点。
    for first in segment_first.points:
        i = _position_by_index(values, first.segment_index)
        if i is None:
            continue
        expected_type = (
            TradingPointType.BUY2
            if first.point_type is TradingPointType.BUY1
            else TradingPointType.SELL2
        )
        if i + 2 >= len(values):
            candidates.append(
                TradingPointCandidate(
                    expected_type,
                    TradingPointStatus.PENDING,
                    None,
                    None,
                    None,
                    "一类点之后尚未完成反向线段与首次回试线段",
                    (("前置一类点", first.point_type.value),),
                    related_segment_indexes=(first.segment_index,),
                )
            )
            continue

        rebound, retrace = values[i + 1], values[i + 2]
        if first.point_type is TradingPointType.BUY1:
            direction_ok = (
                rebound.direction is StrokeDirection.UP
                and retrace.direction is StrokeDirection.DOWN
            )
            price_ok = retrace.end_value >= first.price - _EPS
            lower_type = TradingPointType.BUY1
        else:
            direction_ok = (
                rebound.direction is StrokeDirection.DOWN
                and retrace.direction is StrokeDirection.UP
            )
            price_ok = retrace.end_value <= first.price + _EPS
            lower_type = TradingPointType.SELL1

        lower_result = _detect_local_stroke_first_points(retrace, macd)
        lower = next(
            (
                x
                for x in lower_result.points
                if x.point_type is lower_type
                and x.dt == retrace.end_dt
                and abs(x.price - retrace.end_value) <= _EPS
            ),
            None,
        )
        lower_ok = lower is not None
        checks = (
            ("方向序列", "通过" if direction_ok else "失败"),
            ("不破一类点极值", "通过" if price_ok else "失败"),
            ("次级别一类点", "通过" if lower_ok else "失败"),
            ("次级别候选数", str(len(lower_result.candidates))),
        )
        if not (direction_ok and price_ok and lower_ok):
            candidates.append(
                TradingPointCandidate(
                    expected_type,
                    TradingPointStatus.REJECTED,
                    retrace.end_dt,
                    retrace.end_value,
                    retrace.index,
                    "二类点必须由回试走势终点的次级别一类点构成",
                    checks,
                    related_segment_indexes=(first.segment_index, rebound.index, retrace.index),
                )
            )
            continue

        confirmed_at = max(
            _segment_confirmation_dt(retrace.index, commit_times),
            lower.confirmed_at_dt,
        )
        point = TradingPoint(
            symbol=retrace.symbol,
            point_type=expected_type,
            dt=retrace.end_dt,
            price=retrace.end_value,
            segment_index=retrace.index,
            confirmed_at_dt=confirmed_at,
            evidence_kind="SUBLEVEL_BS1_ON_FIRST_RETRACE",
            evidence=(
                ("前置一类点", first.point_type.value),
                ("前置价格", f"{first.price:.12g}"),
                ("反向线段", str(rebound.index)),
                ("首次回试线段", str(retrace.index)),
                ("次级别一类点", lower.point_type.value),
                ("次级别确认时间", lower.confirmed_at_dt.isoformat()),
            ),
            related_segment_indexes=(first.segment_index, rebound.index, retrace.index),
            source_level="segment",
        )
        points.append(point)
        candidates.append(
            TradingPointCandidate(
                expected_type,
                TradingPointStatus.CONFIRMED,
                point.dt,
                point.price,
                point.segment_index,
                "首次回试不破一类点，且回试终点由笔级别一类点确认",
                checks,
                related_segment_indexes=point.related_segment_indexes,
            )
        )
        diagnostics.append(
            TradingPointDiagnostic(
                expected_type.value,
                f"{point.label}：一类点后的首次回试未破极值，且回试终点出现笔级别{lower.label}",
                point.dt,
            )
        )

    # 三类点：从固定中枢种子完成后，寻找第一条真正离开边界的线段；
    # 紧随其后的反向线段就是首次回试。这样即使回试只触碰 ZG/ZD，
    # 也不会因区间端点相等而被“中枢最大延伸”吞掉。
    for zone in zones:
        scan_start = max(zone.start_position + 2, 0)
        departure_pos: int | None = None
        expected: TradingPointType | None = None
        for pos in range(scan_start, min(len(values), zone.end_position + 2)):
            unit = values[pos]
            if unit.direction is StrokeDirection.UP and unit.end_value > zone.zg + _EPS:
                departure_pos, expected = pos, TradingPointType.BUY3
                break
            if unit.direction is StrokeDirection.DOWN and unit.end_value < zone.zd - _EPS:
                departure_pos, expected = pos, TradingPointType.SELL3
                break
        if departure_pos is None or expected is None:
            continue
        departure = values[departure_pos]
        pullback_pos = departure_pos + 1
        if pullback_pos >= len(values):
            candidates.append(
                TradingPointCandidate(
                    expected, TradingPointStatus.PENDING, departure.end_dt, departure.end_value,
                    departure.index, "离开中枢后尚无已确认的首次反向回试线段",
                    (("中枢", str(zone.index)), ("离开线段", str(departure.index))),
                    zone_index=zone.index, related_segment_indexes=(departure.index,),
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
        checks = (("离开方向", "通过"), ("首次反向回试", "通过" if direction_ok else "失败"),
                  ("不返回中枢", "通过" if boundary_ok else "失败"))
        if not (direction_ok and boundary_ok):
            candidates.append(
                TradingPointCandidate(
                    expected, TradingPointStatus.REJECTED, pullback.end_dt, pullback.end_value,
                    pullback.index, "首次回试重新进入中枢，或回试方向不正确", checks,
                    zone_index=zone.index, related_segment_indexes=(departure.index, pullback.index),
                )
            )
            continue
        point = TradingPoint(
            symbol=pullback.symbol, point_type=expected, dt=pullback.end_dt,
            price=pullback.end_value, segment_index=pullback.index,
            confirmed_at_dt=_segment_confirmation_dt(pullback.index, commit_times),
            evidence_kind="ZONE_DEPARTURE_FIRST_RETEST",
            evidence=(("线段中枢", str(zone.index)), ("ZD", f"{zone.zd:.12g}"),
                      ("ZG", f"{zone.zg:.12g}"), ("离开线段", str(departure.index)),
                      ("首次回试线段", str(pullback.index)), ("距中枢边界", f"{distance:.12g}")),
            zone_index=zone.index, related_segment_indexes=(departure.index, pullback.index),
            source_level="segment",
        )
        points.append(point)
        candidates.append(TradingPointCandidate(
            expected, TradingPointStatus.CONFIRMED, point.dt, point.price, point.segment_index,
            "离开中枢后的第一个反向走势不重新进入中枢", checks, zone_index=zone.index,
            related_segment_indexes=point.related_segment_indexes,
        ))
        diagnostics.append(TradingPointDiagnostic(
            expected.value,
            f"{point.label}：线段中枢 {zone.index} 离开后的首次回试未返回 [{zone.zd:.12g}, {zone.zg:.12g}]",
            point.dt,
        ))

    unique: dict[tuple[TradingPointType, datetime, int], TradingPoint] = {}
    for point in points:
        unique[(point.point_type, point.dt, point.segment_index)] = point
    ordered = tuple(
        sorted(unique.values(), key=lambda x: (x.dt, x.point_type.value, x.segment_index))
    )
    fallback_dt = values[0].start_dt if values else datetime.min
    candidate_ordered = tuple(
        sorted(
            candidates,
            key=lambda x: (
                x.dt or fallback_dt,
                x.point_type.value,
                x.segment_index if x.segment_index is not None else -1,
                x.status.value,
            ),
        )
    )
    return TradingPointDetectionResult(
        ordered,
        candidate_ordered,
        segment_first.divergences,
        tuple(diagnostics),
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
    """校验已确认买卖点及其真实正式提交时间。

    校验器与检测器使用同一份强绑定提交账本重新计算点位；不能只检查
    ``confirmed_at_dt >= dt``，否则错误或篡改后的通知时间仍会通过。
    """
    issues: list[TradingPointDiagnostic] = []
    values = tuple(segments)
    index_map = {x.index: x for x in values}
    zone_map = {x.index: x for x in zones}
    try:
        macd = _macd_histogram(
            raw_bars or _raw_bars_from_segments(values),
            history_anchored=macd_history_anchored,
            anchor=macd_anchor,
        )
    except ValueError as exc:
        macd = _MacdComputation({}, False, None, str(exc))
        issues.append(
            TradingPointDiagnostic(
                "TRADING_POINT_MACD_STREAM_INVALID",
                f"MACD 输入流或锚点无效：{exc}",
                points[0].dt if points else (values[0].start_dt if values else None),
            )
        )
    seen: set[tuple[TradingPointType, datetime, int]] = set()

    expected_points: dict[tuple[TradingPointType, datetime, int], TradingPoint] = {}
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
                "TRADING_POINT_FORMAL_RECALCULATION_FAILED",
                f"无法使用正式结构、提交账本和 MACD 状态复算买卖点：{exc}",
                points[0].dt if points else (values[0].start_dt if values else None),
            )
        )
    else:
        expected_points = {
            (item.point_type, item.dt, item.segment_index): item
            for item in recalculated.points
        }
        for diagnostic in recalculated.diagnostics:
            if diagnostic.code == "FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING":
                issues.append(
                    TradingPointDiagnostic(
                        "TRADING_POINT_COMMIT_EVIDENCE_INVALID",
                        diagnostic.message,
                        diagnostic.dt,
                    )
                )

    for point in points:
        key = (point.point_type, point.dt, point.segment_index)
        if key in seen:
            issues.append(TradingPointDiagnostic("TRADING_POINT_DUPLICATE", f"重复点位 {key}", point.dt))
        seen.add(key)
        segment = index_map.get(point.segment_index)
        if segment is None:
            issues.append(TradingPointDiagnostic("TRADING_POINT_SEGMENT_MISSING", f"{point.label} 对应线段不存在", point.dt))
            continue
        if segment.end_dt != point.dt or abs(segment.end_value - point.price) > _EPS:
            issues.append(TradingPointDiagnostic("TRADING_POINT_ENDPOINT_MISMATCH", f"{point.label} 没有落在线段终点", point.dt))
        expected_direction = StrokeDirection.DOWN if point.is_buy else StrokeDirection.UP
        if segment.direction is not expected_direction:
            issues.append(TradingPointDiagnostic("TRADING_POINT_DIRECTION_INVALID", f"{point.label} 的线段方向错误", point.dt))
        if point.confirmed_at_dt < point.dt:
            issues.append(TradingPointDiagnostic("TRADING_POINT_FUTURE_TIME_INVALID", f"{point.label} 的确认时间早于结构时间", point.dt))
        expected_point = expected_points.get(key)
        if recalculated is not None:
            if expected_point is None:
                issues.append(
                    TradingPointDiagnostic(
                        "TRADING_POINT_NOT_IN_FORMAL_RECALCULATION",
                        f"{point.label} 无法由当前正式线段账本重新计算得到",
                        point.dt,
                    )
                )
            elif point.confirmed_at_dt != expected_point.confirmed_at_dt:
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

        if point.point_type in {TradingPointType.BUY1, TradingPointType.SELL1}:
            ev = point.evidence_dict
            if point.evidence_kind != "STRICT_TREND_DIRECTIONAL_MACD_DIVERGENCE":
                issues.append(TradingPointDiagnostic(
                    "BS1_EVIDENCE_KIND_INVALID",
                    f"{point.label} 不是严格趋势方向 MACD 背驰证据",
                    point.dt,
                ))
            if ev.get("趋势中枢数") != "2" or ev.get("MACD状态") != "精确":
                issues.append(TradingPointDiagnostic("BS1_TREND_INVALID", f"{point.label} 缺少严格趋势或精确 MACD 状态", point.dt))
            try:
                previous_gg = float(ev["前中枢GG"])
                previous_dd = float(ev["前中枢DD"])
                last_gg = float(ev["后中枢GG"])
                last_dd = float(ev["后中枢DD"])
                entry_area = float(ev["进入MACD面积"])
                exit_area = float(ev["离开MACD面积"])
            except (KeyError, ValueError):
                issues.append(TradingPointDiagnostic("BS1_EVIDENCE_INVALID", f"{point.label} 严格趋势或 MACD 证据不可解析", point.dt))
            else:
                strict = (
                    last_gg < previous_dd - _EPS
                    if point.point_type is TradingPointType.BUY1
                    else last_dd > previous_gg + _EPS
                )
                if not strict:
                    issues.append(TradingPointDiagnostic("BS1_STRICT_TREND_INVALID", f"{point.label} 不满足 GG/DD 严格趋势关系", point.dt))
                if entry_area <= _EPS or exit_area >= entry_area - _EPS:
                    issues.append(TradingPointDiagnostic("BS1_MACD_DIVERGENCE_INVALID", f"{point.label} 同方向 MACD 柱面积未减弱", point.dt))

                try:
                    previous_zone_index = int(ev["前中枢"])
                    last_zone_index = int(ev["最后中枢"])
                    entry_index = int(ev.get("比较单元b", ev.get("进入单元A", "")))
                    exit_index = int(ev.get("离开单元c", ev.get("离开单元C", "")))
                except (KeyError, ValueError):
                    issues.append(TradingPointDiagnostic("BS1_ABC_EVIDENCE_INVALID", f"{point.label} a+A+b+B+c 证据不可解析", point.dt))
                else:
                    last_zone = zone_map.get(last_zone_index)
                    entry_pos = _position_by_index(values, entry_index)
                    exit_pos = _position_by_index(values, exit_index)
                    if last_zone is None or entry_pos is None or exit_pos is None:
                        issues.append(TradingPointDiagnostic("BS1_ABC_STRUCTURE_MISSING", f"{point.label} a+A+b+B+c 结构不存在", point.dt))
                    else:
                        views = {x.index: x for x in _zone_views(zones, values)}
                        previous_view = views.get(previous_zone_index)
                        last_view = views.get(last_zone_index)
                        direction = StrokeDirection.DOWN if point.point_type is TradingPointType.BUY1 else StrokeDirection.UP
                        if previous_view is None or last_view is None:
                            issues.append(TradingPointDiagnostic(
                                "BS1_ZONE_VIEW_MISSING",
                                f"{point.label} 的前后中枢无法按趋势本体重新计算",
                                point.dt,
                            ))
                            continue
                        expected_entry_pos = _find_entry_position(values, previous_view, last_view, direction)
                        expected_exit_pos = _find_exit_position(values, last_view, direction)
                        if expected_entry_pos != entry_pos or expected_exit_pos != exit_pos:
                            issues.append(TradingPointDiagnostic(
                                "BS1_BC_POSITION_INVALID",
                                f"{point.label} 的 b/c 不是按前后中枢重新计算得到的连接段与最终离开段",
                                point.dt,
                            ))
                        internal = _internal_zone_third_point(values[exit_pos], last_view, direction)
                        if (
                            exit_pos != last_view.end
                            or internal is None
                            or internal.sublevel_zone_count < 2
                        ):
                            issues.append(TradingPointDiagnostic(
                                "BS1_C_NOT_COMPLETE",
                                f"{point.label} 的 c 不是最后中枢最终离开段，或 c 内缺少次级别三类点/两个次级别中枢",
                                point.dt,
                            ))
                        actual_entry_area = _directional_macd_area(values[entry_pos], direction, macd.histogram)
                        actual_exit_area = _directional_macd_area(values[exit_pos], direction, macd.histogram)
                        if not macd.exact:
                            issues.append(TradingPointDiagnostic(
                                "BS1_MACD_STATE_NOT_EXACT",
                                f"{point.label} 无法由真实历史起点或 MacdAnchor 精确复算 MACD",
                                point.dt,
                            ))
                        if (
                            abs(actual_entry_area - entry_area) > 1e-8
                            or abs(actual_exit_area - exit_area) > 1e-8
                        ):
                            issues.append(TradingPointDiagnostic(
                                "BS1_MACD_EVIDENCE_MISMATCH",
                                f"{point.label} 保存的 b/c MACD 面积与原始 K 复算结果不一致",
                                point.dt,
                            ))
                        if actual_entry_area <= _EPS or actual_exit_area >= actual_entry_area - _EPS:
                            issues.append(TradingPointDiagnostic(
                                "BS1_MACD_RECOMPUTED_INVALID",
                                f"{point.label} 按原始 K 重算后不满足同方向 MACD 柱面积背驰",
                                point.dt,
                            ))
                        prior = values[entry_pos:exit_pos]
                        if prior:
                            extreme = (
                                values[exit_pos].end_value < min(x.low for x in prior) - _EPS
                                if direction is StrokeDirection.DOWN
                                else values[exit_pos].end_value > max(x.high for x in prior) + _EPS
                            )
                            if not extreme:
                                issues.append(TradingPointDiagnostic("BS1_PRICE_EXTREME_INVALID", f"{point.label} 的 c 未创趋势新极值", point.dt))

        if point.point_type in {TradingPointType.BUY2, TradingPointType.SELL2}:
            if point.evidence_kind != "SUBLEVEL_BS1_ON_FIRST_RETRACE":
                issues.append(TradingPointDiagnostic("BS2_SUBLEVEL_EVIDENCE_MISSING", f"{point.label} 缺少次级别一类点证据", point.dt))
            else:
                expected_lower = (
                    TradingPointType.BUY1
                    if point.point_type is TradingPointType.BUY2
                    else TradingPointType.SELL1
                )
                lower_result = _detect_local_stroke_first_points(segment, macd)
                lower_ok = any(
                    x.point_type is expected_lower
                    and x.dt == point.dt
                    and abs(x.price - point.price) <= _EPS
                    for x in lower_result.points
                )
                if not lower_ok:
                    issues.append(
                        TradingPointDiagnostic(
                            "BS2_SUBLEVEL_EVIDENCE_INVALID",
                            f"{point.label} 的回试终点未能重新计算出次级别{expected_lower.label}",
                            point.dt,
                        )
                    )

        if point.point_type in {TradingPointType.BUY3, TradingPointType.SELL3}:
            zone = zone_map.get(point.zone_index)
            if zone is None:
                issues.append(TradingPointDiagnostic("BS3_ZONE_MISSING", f"{point.label} 关联中枢不存在", point.dt))
            elif point.point_type is TradingPointType.BUY3 and segment.low < zone.zg - _EPS:
                issues.append(TradingPointDiagnostic("BUY3_REENTERED_ZONE", "三买回试重新进入中枢", point.dt))
            elif point.point_type is TradingPointType.SELL3 and segment.high > zone.zd + _EPS:
                issues.append(TradingPointDiagnostic("SELL3_REENTERED_ZONE", "三卖回抽重新进入中枢", point.dt))

    return tuple(issues)


def _detect_first_points_at_level(
    *,
    units: Sequence[Any],
    zones: Sequence[Any],
    macd: _MacdComputation,
    level: str,
    confirmation_fn: Callable[[int], datetime],
    segment_index_fn: Callable[[int], int],
) -> _FirstPointLevelResult:
    """识别严格趋势背驰形成的一类买卖点。

    这里严格区分两种情况：

    * ``后 GG < 前 DD`` / ``后 DD > 前 GG``：同级别下跌/上涨趋势；
    * 只有核心区 ``ZG/ZD`` 分离、但 ``GG/DD`` 仍重叠：形成更高级别中枢，
      不是标准趋势背驰，不能输出一买/一卖。

    MACD 只比较走势方向对应的柱体：下跌只累计绿柱（负柱），上涨只累计
    红柱（正柱）。有限窗口若没有真实历史起点或持久化 ``MacdAnchor``，
    EMA 状态不可精确恢复，只输出待确认候选，不输出正式点。
    """
    values = tuple(units)
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
            # 核心区分离而整体波动区间仍重叠，原理论定义为更高级别中枢，
            # 不能把它误判成趋势与一类点。
            if core_down or core_up:
                point_type = TradingPointType.BUY1 if core_down else TradingPointType.SELL1
                candidates.append(
                    TradingPointCandidate(
                        point_type,
                        TradingPointStatus.REJECTED,
                        None,
                        None,
                        None,
                        "中枢核心区虽已分离，但 GG/DD 波动区间仍重叠；属于更高级别中枢，不是严格趋势",
                        (
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
                    point_type,
                    TradingPointStatus.PENDING,
                    None,
                    None,
                    None,
                    "严格趋势已成立，但连接段 b 或最终离开走势 c 尚未完整确认",
                    (
                        ("前中枢", str(previous.index)),
                        ("后中枢", str(last.index)),
                        ("比较段b", str(entry_pos)),
                        ("离开段c", str(exit_pos)),
                        ("严格趋势", "通过"),
                    ),
                    zone_index=last.index,
                )
            )
            continue

        entry = values[entry_pos]
        exit_ = values[exit_pos]
        internal_third = _internal_zone_third_point(exit_, last, direction)
        # segment 是正式操作级别，c 必须在自身内部包含对最后中枢 B 的次级别
        # 三类点，而且至少包含两个次级别中枢。stroke 是当前数据模型的最低
        # 递归层，只能以完成笔作为解析下限。
        sublevel_zone_count = (
            internal_third.sublevel_zone_count if internal_third is not None else 0
        )
        sublevel_third_point = (
            internal_third is not None and sublevel_zone_count >= 2
        ) or level == "stroke"
        entry_area = _directional_macd_area(entry, direction, macd.histogram)
        exit_area = _directional_macd_area(exit_, direction, macd.histogram)

        # c 必须成为从 b 开始到 c 之前整个同级别趋势的新极值，而不仅仅是
        # 与 b 的终点作一次局部比较。
        prior_units = values[entry_pos:exit_pos]
        if direction is StrokeDirection.DOWN:
            previous_extreme = min(float(x.low) for x in prior_units)
            extreme = exit_.end_value < previous_extreme - _EPS
        else:
            previous_extreme = max(float(x.high) for x in prior_units)
            extreme = exit_.end_value > previous_extreme + _EPS

        divergence = entry_area > _EPS and exit_area < entry_area - _EPS
        trend = TrendDivergence(
            symbol=exit_.symbol,
            level=level,
            direction=direction,
            previous_zone_index=previous.index,
            last_zone_index=last.index,
            entry_unit_index=entry.index,
            exit_unit_index=exit_.index,
            entry_macd_area=entry_area,
            exit_macd_area=exit_area,
            entry_power=float(entry.power),
            exit_power=float(exit_.power),
            entry_start_dt=entry.start_dt,
            entry_end_dt=entry.end_dt,
            exit_start_dt=exit_.start_dt,
            exit_end_dt=exit_.end_dt,
            price_extreme=extreme,
            macd_divergence=divergence,
            macd_state_exact=macd.exact,
            strict_trend=True,
            sublevel_third_point=sublevel_third_point,
            sublevel_zone_count=sublevel_zone_count,
        )
        divergences.append(trend)
        checks = (
            ("严格趋势GG/DD", "通过"),
            ("前中枢GG/DD", f"{previous.gg:.12g}/{previous.dd:.12g}"),
            ("后中枢GG/DD", f"{last.gg:.12g}/{last.dd:.12g}"),
            ("b/c同向", "通过"),
            ("c内次级别三类点", "通过" if internal_third is not None else "失败"),
            ("c内次级别中枢数", str(sublevel_zone_count)),
            ("c次级别结构完整", "通过" if sublevel_third_point else "失败"),
            ("c创趋势新极值", "通过" if extreme else "失败"),
            ("MACD状态精确", "通过" if macd.exact else "失败"),
            ("方向MACD柱面积背驰", "通过" if divergence else "失败"),
            ("b方向MACD面积", f"{entry_area:.12g}"),
            ("c方向MACD面积", f"{exit_area:.12g}"),
        )
        segment_index = segment_index_fn(exit_pos)

        if not sublevel_third_point:
            candidates.append(
                TradingPointCandidate(
                    point_type,
                    TradingPointStatus.PENDING,
                    exit_.end_dt,
                    exit_.end_value,
                    segment_index,
                    "最终离开 c 尚未同时满足：内部形成对最后中枢 B 的次级别三类点，且至少包含两个次级别中枢",
                    checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_.index),
                )
            )
            continue

        if not extreme:
            candidates.append(
                TradingPointCandidate(
                    point_type,
                    TradingPointStatus.REJECTED,
                    exit_.end_dt,
                    exit_.end_value,
                    segment_index,
                    "严格趋势成立，但最终离开 c 没有创出该趋势新极值",
                    checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_.index),
                )
            )
            continue

        if not macd.exact:
            candidates.append(
                TradingPointCandidate(
                    point_type,
                    TradingPointStatus.PENDING,
                    exit_.end_dt,
                    exit_.end_value,
                    segment_index,
                    "严格趋势与价格新极值成立，但有限窗口缺少精确 MACD 递推状态；需真实历史起点或 MacdAnchor",
                    checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_.index),
                )
            )
            continue

        if not divergence:
            candidates.append(
                TradingPointCandidate(
                    point_type,
                    TradingPointStatus.REJECTED,
                    exit_.end_dt,
                    exit_.end_value,
                    segment_index,
                    "严格趋势和价格新极值成立，但 c 的同方向 MACD 柱面积没有小于 b",
                    checks,
                    zone_index=last.index,
                    related_segment_indexes=(entry.index, exit_.index),
                )
            )
            continue

        point = TradingPoint(
            symbol=exit_.symbol,
            point_type=point_type,
            dt=exit_.end_dt,
            price=exit_.end_value,
            segment_index=segment_index,
            confirmed_at_dt=confirmation_fn(exit_pos),
            evidence_kind="STRICT_TREND_DIRECTIONAL_MACD_DIVERGENCE",
            evidence=(
                ("级别", level),
                ("趋势中枢数", "2"),
                ("严格趋势规则", "后GG<前DD" if direction is StrokeDirection.DOWN else "后DD>前GG"),
                ("前中枢", str(previous.index)),
                ("最后中枢", str(last.index)),
                ("前中枢GG", f"{previous.gg:.12g}"),
                ("前中枢DD", f"{previous.dd:.12g}"),
                ("后中枢GG", f"{last.gg:.12g}"),
                ("后中枢DD", f"{last.dd:.12g}"),
                ("比较单元b", str(entry.index)),
                ("离开单元c", str(exit_.index)),
                ("c内次级别三类点", str(internal_third.position) if internal_third is not None else "最低建模级别"),
                ("c内次级别中枢数", str(sublevel_zone_count)),
                ("MACD面积方向", "负柱" if direction is StrokeDirection.DOWN else "正柱"),
                ("b方向MACD面积", f"{entry_area:.12g}"),
                ("c方向MACD面积", f"{exit_area:.12g}"),
                # 兼容 v0.10.13 以前的审计字段名。
                ("进入MACD面积", f"{entry_area:.12g}"),
                ("离开MACD面积", f"{exit_area:.12g}"),
                ("MACD状态", "精确"),
                ("进入价格力度", f"{entry.power:.12g}"),
                ("离开价格力度", f"{exit_.power:.12g}"),
            ),
            zone_index=last.index,
            related_segment_indexes=(entry.index, exit_.index),
            source_level=level,
        )
        points.append(point)
        candidates.append(
            TradingPointCandidate(
                point_type,
                TradingPointStatus.CONFIRMED,
                point.dt,
                point.price,
                segment_index,
                "两个同级别中枢满足严格 GG/DD 趋势关系，c 内含次级别三类点和至少两个次级别中枢、创新极值且同方向 MACD 柱面积小于 b",
                checks,
                zone_index=last.index,
                related_segment_indexes=(entry.index, exit_.index),
            )
        )

    return _FirstPointLevelResult(tuple(points), tuple(candidates), tuple(divergences))

def _detect_local_stroke_first_points(
    segment: Segment, macd: _MacdComputation
) -> _FirstPointLevelResult:
    local = tuple(segment.strokes)
    if len(local) < 5:
        return _FirstPointLevelResult((), (), ())
    zones = detect_central_zones(local).zones
    if len(zones) < 2:
        return _FirstPointLevelResult((), (), ())
    return _detect_first_points_at_level(
        units=local,
        zones=zones,
        macd=macd,
        level="stroke",
        confirmation_fn=lambda pos: local[pos].fx_b.source_end,
        segment_index_fn=lambda pos: segment.index,
    )


def _zone_views(zones: Sequence[Any], units: Sequence[Any]) -> tuple[_ZoneView, ...]:
    identity = {id(x): i for i, x in enumerate(units)}
    by_index = {x.index: i for i, x in enumerate(units)}
    result: list[_ZoneView] = []
    for i, zone in enumerate(zones):
        members = getattr(zone, "segments", None) or getattr(zone, "strokes", None)
        if not members:
            continue
        if hasattr(zone, "start_position") and zone.start_position >= 0:
            start, end = int(zone.start_position), int(zone.end_position)
        else:
            first, last = members[0], members[-1]
            start = identity.get(id(first), by_index.get(first.index, -1))
            end = identity.get(id(last), by_index.get(last.index, -1))
        if start < 0 or end < start:
            continue
        trend_members = (
            getattr(zone, "trend_segments", None)
            or getattr(zone, "trend_strokes", None)
            or members
        )
        # 去掉最终离开单元后，至少仍需三个同级别走势才能称为中枢本体。
        if len(trend_members) < 3:
            continue
        result.append(
            _ZoneView(
                index=int(getattr(zone, "index", i) if getattr(zone, "index", -1) >= 0 else i),
                start=start,
                end=end,
                zg=float(zone.zg),
                zd=float(zone.zd),
                gg=max(float(x.high) for x in trend_members),
                dd=min(float(x.low) for x in trend_members),
            )
        )
    return tuple(result)


def _find_entry_position(
    units: Sequence[Any], previous: _ZoneView, last: _ZoneView, direction: StrokeDirection
) -> int | None:
    # 扫描器因价格连续性会把最终离开线段保留在前中枢切片尾部；该尾段正是
    # A（连接前后两个中枢的同向走势），因此从 previous.end 开始寻找。
    lo = max(0, previous.end)
    hi = min(len(units) - 1, last.start - 1)
    for pos in range(hi, lo - 1, -1):
        unit = units[pos]
        if unit.direction is not direction:
            continue
        if direction is StrokeDirection.DOWN:
            if unit.start_value > last.zg + _EPS and unit.end_value <= last.zg + _EPS:
                return pos
        else:
            if unit.start_value < last.zd - _EPS and unit.end_value >= last.zd - _EPS:
                return pos
    return None


def _find_exit_position(
    units: Sequence[Any], zone: _ZoneView, direction: StrokeDirection
) -> int | None:
    # 已完成中枢的 c 只能是其切片最后一条离开单元。若中途离开后又返回，
    # 中枢会继续延伸，那次离开属于中枢震荡，不得提前输出一类点。
    pos = zone.end
    if pos < 0 or pos >= len(units):
        return None
    unit = units[pos]
    if unit.direction is not direction:
        return None
    if direction is StrokeDirection.DOWN:
        return pos if unit.start_value >= zone.zd - _EPS and unit.end_value < zone.zd - _EPS else None
    return pos if unit.start_value <= zone.zg + _EPS and unit.end_value > zone.zg + _EPS else None


def _internal_zone_third_point(
    unit: Any, zone: _ZoneView, direction: StrokeDirection
) -> _InternalThirdPoint | None:
    """返回 c 内部对最后中枢 B 形成的次级别三类点及中枢数量。

    下跌 c：内部先向下离开 ``ZD``，随后向上回抽不回到 ``ZD``，再继续
    向下；上涨 c 对称。标准 ``a+A+b+B+c`` 背驰还要求 c 至少包含两个
    次级别中枢，因此三笔形似结构不会被提升为正式一类点。
    """
    lower_units = tuple(getattr(unit, "strokes", ()))
    if len(lower_units) < 3:
        return None
    zone_count = len(detect_central_zones(lower_units).zones)
    for pos in range(len(lower_units) - 2):
        departure, pullback, continuation = lower_units[pos : pos + 3]
        if direction is StrokeDirection.DOWN:
            valid = (
                departure.direction is StrokeDirection.DOWN
                and departure.end_value < zone.zd - _EPS
                and pullback.direction is StrokeDirection.UP
                and pullback.high <= zone.zd + _EPS
                and continuation.direction is StrokeDirection.DOWN
                and continuation.end_value < pullback.start_value - _EPS
            )
        else:
            valid = (
                departure.direction is StrokeDirection.UP
                and departure.end_value > zone.zg + _EPS
                and pullback.direction is StrokeDirection.DOWN
                and pullback.low >= zone.zg - _EPS
                and continuation.direction is StrokeDirection.UP
                and continuation.end_value > pullback.start_value + _EPS
            )
        if valid:
            return _InternalThirdPoint(
                position=int(getattr(pullback, "index", pos + 1)),
                sublevel_zone_count=zone_count,
            )
    return None


def build_macd_anchor(
    raw_bars: Sequence[RawBar],
    *,
    anchor: MacdAnchor | None = None,
) -> MacdAnchor:
    """递推并返回最后一根 K 收盘后的 MACD 状态。

    ``anchor`` 表示第一根输入 K 之前的状态；没有 anchor 时，调用方必须保证
    输入从该品种、该周期的真实历史起点开始。该函数用于滚动窗口和服务重启时
    持久化 EMA12、EMA26 与 DEA，避免窗口变化改变背驰结论。
    """
    computation = _macd_histogram(
        raw_bars,
        history_anchored=anchor is None,
        anchor=anchor,
    )
    if computation.final_anchor is None:
        raise ValueError("至少需要一根 K 线才能生成 MacdAnchor")
    if not computation.exact:
        raise ValueError(
            "输入 K 线不是同品种、同周期且连续的精确序列，不能生成可用于正式买卖点的 MacdAnchor"
        )
    return computation.final_anchor


def _macd_histogram(
    raw_bars: Sequence[RawBar],
    *,
    history_anchored: bool,
    anchor: MacdAnchor | None,
) -> _MacdComputation:
    bars = tuple(raw_bars)
    if not bars:
        return _MacdComputation(
            {},
            bool(history_anchored) if anchor is None else bool(anchor.exact),
            anchor,
        )

    stream = validate_bar_stream(bars)
    if anchor is not None:
        if stream.symbol != anchor.symbol:
            raise ValueError(
                f"MacdAnchor 品种不匹配：{anchor.symbol} != {stream.symbol}"
            )
        if stream.interval != anchor.interval:
            raise ValueError(
                f"MacdAnchor 周期不匹配：{anchor.interval} != {stream.interval}"
            )
        if bars[0].open_time != anchor.expected_next_open_time:
            raise ValueError(
                "MacdAnchor 与输入窗口不连续："
                f"锚点要求下一根为 {anchor.expected_next_open_time.isoformat()}，"
                f"实际首根为 {bars[0].open_time.isoformat()}"
            )
        if not stream.continuous:
            raise ValueError(
                "MacdAnchor 后的输入 K 线存在断档，无法精确续算 MACD："
                f"{stream.issue}"
            )

    alpha_fast = 2.0 / 13.0
    alpha_slow = 2.0 / 27.0
    alpha_signal = 2.0 / 10.0
    histogram: dict[datetime, float] = {}

    if anchor is None:
        first = bars[0]
        ema_fast = float(first.close)
        ema_slow = float(first.close)
        dea = 0.0
        histogram[first.open_time] = 0.0
        remaining = bars[1:]
        exact = bool(history_anchored and stream.continuous)
        issue = None if exact else (
            stream.issue
            or "有限窗口未声明为真实历史起点，MACD 初始 EMA 状态不可精确恢复"
        )
        history_start_open_time = first.open_time if exact else None
        processed_bar_count = len(bars)
    else:
        ema_fast = float(anchor.ema_fast)
        ema_slow = float(anchor.ema_slow)
        dea = float(anchor.dea)
        remaining = bars
        exact = bool(anchor.exact)
        issue = None if exact else "传入的 MacdAnchor 本身不是精确状态"
        history_start_open_time = anchor.history_start_open_time
        processed_bar_count = anchor.processed_bar_count + len(bars)

    for bar in remaining:
        close = float(bar.close)
        ema_fast = alpha_fast * close + (1.0 - alpha_fast) * ema_fast
        ema_slow = alpha_slow * close + (1.0 - alpha_slow) * ema_slow
        dif = ema_fast - ema_slow
        dea = alpha_signal * dif + (1.0 - alpha_signal) * dea
        histogram[bar.open_time] = 2.0 * (dif - dea)

    last = bars[-1]
    final = MacdAnchor(
        symbol=last.symbol,
        interval=last.interval,
        asof=bars[-1].close_time,
        last_open_time=last.open_time,
        last_close_time=last.close_time,
        expected_next_open_time=next_open_time(last.open_time, last.interval),
        last_bar_fingerprint=raw_bar_fingerprint(last),
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        dea=dea,
        exact=exact,
        history_start_open_time=history_start_open_time,
        processed_bar_count=processed_bar_count,
    )
    return _MacdComputation(histogram, exact, final, issue)


def _directional_macd_area(
    unit: Any, direction: StrokeDirection, macd: dict[datetime, float]
) -> float:
    values = (
        value
        for dt, value in macd.items()
        if unit.source_start <= dt <= unit.source_end
    )
    if direction is StrokeDirection.DOWN:
        # 下跌背驰只比较绿柱（负柱）面积。反向红柱属于内部反弹，不能作为
        # 下跌力度累加，否则会同时制造假阳性与假阴性。
        return float(sum(-value for value in values if value < 0.0))
    # 上涨背驰只比较红柱（正柱）面积。
    return float(sum(value for value in values if value > 0.0))


def _raw_bars_from_segments(segments: Sequence[Segment]) -> tuple[RawBar, ...]:
    values: list[RawBar] = []
    for segment in segments:
        values.extend(segment.raw_bars)
        for stroke in segment.strokes:
            for merged in stroke.bars:
                values.extend(merged.elements)
    return unique_elements(values)


def _position_by_index(segments: Sequence[Segment], index: int) -> int | None:
    for i, segment in enumerate(segments):
        if segment.index == index:
            return i
    return None


def _formal_segment_commit_times(
    segments: Sequence[Segment],
    *,
    segment_evidence: Sequence[SegmentEvidence],
    explicit: Mapping[str, datetime] | None,
) -> dict[int, datetime]:
    """汇总强绑定的正式提交时间。

    ``segment_index`` 只是当前链内位置，不能跨品种或跨恢复会话充当身份。
    结构证据必须携带几何指纹；外部持久化映射必须直接以指纹为键。
    """
    by_index = {x.index: x for x in segments}
    by_fingerprint: dict[str, Segment] = {}
    for segment in segments:
        fingerprint = segment.fingerprint
        if fingerprint in by_fingerprint:
            raise ValueError("输入线段链存在重复结构指纹，无法安全匹配提交证据")
        by_fingerprint[fingerprint] = segment

    result: dict[int, datetime] = {}
    for item in segment_evidence:
        if item.committed_at is None:
            continue
        segment = by_index.get(item.segment_index)
        if segment is None:
            raise ValueError(f"SegmentEvidence 包含未知线段索引：{item.segment_index}")
        if not item.matches_segment(segment):
            raise ValueError(
                f"线段 {item.segment_index} 的 SegmentEvidence 与品种/周期/几何指纹不匹配"
            )
        previous = result.get(segment.index)
        if previous is not None and previous != item.committed_at:
            raise ValueError(f"线段 {segment.index} 存在冲突的 committed_at")
        result[segment.index] = item.committed_at

    for fingerprint, committed_at in (explicit or {}).items():
        if not isinstance(fingerprint, str):
            raise TypeError(
                "segment_commit_times 必须以 Segment.fingerprint 字符串为键；"
                "不再接受 segment_index"
            )
        if not isinstance(committed_at, datetime):
            raise TypeError("segment_commit_times 的值必须是 datetime")
        segment = by_fingerprint.get(fingerprint)
        if segment is None:
            raise ValueError("segment_commit_times 包含不属于当前线段链的结构指纹")
        previous = result.get(segment.index)
        if previous is not None and previous != committed_at:
            raise ValueError(f"线段 {segment.index} 的显式提交时间与 SegmentEvidence 冲突")
        result[segment.index] = committed_at

    for index, committed_at in result.items():
        segment = by_index[index]
        available_at = max(segment.end_dt, segment.source_end)
        if committed_at < available_at:
            raise ValueError(
                f"线段 {index} 的 committed_at 早于结构可用时间："
                f"{committed_at.isoformat()} < {available_at.isoformat()}"
            )
    return result


def _segment_confirmation_dt(
    segment_index: int,
    commit_times: Mapping[int, datetime],
) -> datetime:
    try:
        return commit_times[segment_index]
    except KeyError as exc:  # pragma: no cover - 入口已统一校验覆盖率
        raise ValueError(f"线段 {segment_index} 缺少正式 committed_at") from exc
