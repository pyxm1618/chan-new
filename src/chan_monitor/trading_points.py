from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Sequence

from .central_zones import detect_central_zones
from .models import (
    CentralZone,
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


def detect_trading_points(
    segments: Sequence[Segment],
    segment_central_zones: Sequence[SegmentCentralZone],
    *,
    raw_bars: Sequence[RawBar] = (),
    segment_evidence: Sequence[SegmentEvidence] = (),
    strokes: Sequence[Stroke] = (),
) -> TradingPointDetectionResult:
    """识别线段操作级别的一、二、三类买卖点。

    本实现明确区分操作级别与次级别：

    * 一买/一卖：操作级别必须已经形成至少两个严格同向、互不重叠的线段中枢，
      最后中枢的进入线段与离开线段方向一致；离开线段创新极值，同时其同方向
      MACD 柱面积小于进入线段，构成趋势背驰。
    * 二买/二卖：操作级别一类点之后的第一次反向回试不破坏一类点极值，并且
      该回试线段的终点必须同时是其内部笔级别走势的一类买卖点。
    * 三买/三卖：一个已完成线段离开固定线段中枢，紧随其后的第一个反向线段
      回试不重新进入中枢；不跌破/不升破边界包含等价触碰。

    只使用已经确认的线段。图上点位使用 ``dt``，后台通知必须使用
    ``confirmed_at_dt``，避免未来函数。
    """
    values = tuple(segments)
    zones = tuple(segment_central_zones)
    bars = tuple(sorted(raw_bars or _raw_bars_from_segments(values), key=lambda x: x.open_time))
    evidence_map = {x.segment_index: x for x in segment_evidence}

    segment_first = _detect_first_points_at_level(
        units=values,
        zones=zones,
        raw_bars=bars,
        level="segment",
        confirmation_fn=lambda pos: _segment_confirmation_dt(
            values[pos].index, values, evidence_map, strokes
        ),
        segment_index_fn=lambda pos: values[pos].index,
    )

    points: list[TradingPoint] = list(segment_first.points)
    candidates: list[TradingPointCandidate] = list(segment_first.candidates)
    diagnostics: list[TradingPointDiagnostic] = []

    for point in segment_first.points:
        diagnostics.append(
            TradingPointDiagnostic(
                point.point_type.value,
                f"{point.label}：两个同向线段中枢构成趋势，最后中枢离开段创新极值且 MACD 力度背驰",
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

        lower_result = _detect_local_stroke_first_points(retrace, bars)
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
            _segment_confirmation_dt(retrace.index, values, evidence_map, strokes),
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
            confirmed_at_dt=_segment_confirmation_dt(pullback.index, values, evidence_map, strokes),
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
) -> tuple[TradingPointDiagnostic, ...]:
    """校验已确认买卖点的方向、端点、层级证据和中枢边界。"""
    issues: list[TradingPointDiagnostic] = []
    values = tuple(segments)
    index_map = {x.index: x for x in values}
    zone_map = {x.index: x for x in zones}
    seen: set[tuple[TradingPointType, datetime, int]] = set()

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

        if point.point_type in {TradingPointType.BUY1, TradingPointType.SELL1}:
            ev = point.evidence_dict
            if ev.get("趋势中枢数") != "2":
                issues.append(TradingPointDiagnostic("BS1_TREND_INVALID", f"{point.label} 没有两个严格同向中枢", point.dt))
            try:
                if float(ev.get("离开MACD面积", "nan")) >= float(ev.get("进入MACD面积", "nan")) - _EPS:
                    issues.append(TradingPointDiagnostic("BS1_MACD_DIVERGENCE_INVALID", f"{point.label} MACD 力度未减弱", point.dt))
            except ValueError:
                issues.append(TradingPointDiagnostic("BS1_MACD_EVIDENCE_INVALID", f"{point.label} MACD 证据不可解析", point.dt))

        if point.point_type in {TradingPointType.BUY2, TradingPointType.SELL2}:
            if point.evidence_kind != "SUBLEVEL_BS1_ON_FIRST_RETRACE":
                issues.append(TradingPointDiagnostic("BS2_SUBLEVEL_EVIDENCE_MISSING", f"{point.label} 缺少次级别一类点证据", point.dt))
            else:
                expected_lower = (
                    TradingPointType.BUY1
                    if point.point_type is TradingPointType.BUY2
                    else TradingPointType.SELL1
                )
                lower_result = _detect_local_stroke_first_points(segment, raw_bars)
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
    raw_bars: Sequence[RawBar],
    level: str,
    confirmation_fn: Callable[[int], datetime],
    segment_index_fn: Callable[[int], int],
) -> _FirstPointLevelResult:
    values = tuple(units)
    zone_views = _zone_views(zones, values)
    macd = _macd_histogram(raw_bars)
    points: list[TradingPoint] = []
    candidates: list[TradingPointCandidate] = []
    divergences: list[TrendDivergence] = []

    for previous, last in zip(zone_views, zone_views[1:]):
        # 当前中枢对象会把离开段纳入时间延伸，GG/DD 因而可能包含
        # 离开段极值。趋势关系应比较两个固定核心区间，而不是扩展后的
        # 全部波动范围：后中枢核心完全低于前中枢为下跌，反之为上涨。
        if last.zg < previous.zd - _EPS:
            direction = StrokeDirection.DOWN
            point_type = TradingPointType.BUY1
        elif last.zd > previous.zg + _EPS:
            direction = StrokeDirection.UP
            point_type = TradingPointType.SELL1
        else:
            continue

        entry_pos = _find_entry_position(values, previous, last, direction)
        exit_pos = _find_exit_position(values, last, direction)
        if entry_pos is None or exit_pos is None:
            candidates.append(
                TradingPointCandidate(
                    point_type,
                    TradingPointStatus.PENDING,
                    None,
                    None,
                    None,
                    "趋势中枢已成立，但最后中枢的进入段或离开段尚未完整确认",
                    (
                        ("前中枢", str(previous.index)),
                        ("后中枢", str(last.index)),
                        ("进入段", str(entry_pos)),
                        ("离开段", str(exit_pos)),
                    ),
                    zone_index=last.index,
                )
            )
            continue

        entry = values[entry_pos]
        exit_ = values[exit_pos]
        entry_area = _directional_macd_area(entry, direction, macd)
        exit_area = _directional_macd_area(exit_, direction, macd)
        if direction is StrokeDirection.DOWN:
            extreme = exit_.end_value < entry.end_value - _EPS
        else:
            extreme = exit_.end_value > entry.end_value + _EPS
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
        )
        divergences.append(trend)
        checks = (
            ("严格同向中枢", "通过"),
            ("进入离开同向", "通过"),
            ("离开段创新极值", "通过" if extreme else "失败"),
            ("MACD柱面积背驰", "通过" if divergence else "失败"),
            ("进入MACD面积", f"{entry_area:.12g}"),
            ("离开MACD面积", f"{exit_area:.12g}"),
        )
        segment_index = segment_index_fn(exit_pos)
        if not trend.is_valid:
            candidates.append(
                TradingPointCandidate(
                    point_type,
                    TradingPointStatus.REJECTED,
                    exit_.end_dt,
                    exit_.end_value,
                    segment_index,
                    "趋势结构成立，但离开段未同时满足创新极值与 MACD 力度背驰",
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
            evidence_kind="TREND_MACD_DIVERGENCE",
            evidence=(
                ("级别", level),
                ("趋势中枢数", "2"),
                ("前中枢", str(previous.index)),
                ("最后中枢", str(last.index)),
                ("进入单元", str(entry.index)),
                ("离开单元", str(exit_.index)),
                ("进入MACD面积", f"{entry_area:.12g}"),
                ("离开MACD面积", f"{exit_area:.12g}"),
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
                "两个严格同向中枢构成趋势，离开段创新极值且 MACD 柱面积背驰",
                checks,
                zone_index=last.index,
                related_segment_indexes=(entry.index, exit_.index),
            )
        )

    return _FirstPointLevelResult(tuple(points), tuple(candidates), tuple(divergences))


def _detect_local_stroke_first_points(
    segment: Segment, raw_bars: Sequence[RawBar]
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
        raw_bars=raw_bars,
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
        result.append(
            _ZoneView(
                index=int(getattr(zone, "index", i) if getattr(zone, "index", -1) >= 0 else i),
                start=start,
                end=end,
                zg=float(zone.zg),
                zd=float(zone.zd),
                gg=float(zone.gg),
                dd=float(zone.dd),
            )
        )
    return tuple(result)


def _find_entry_position(
    units: Sequence[Any], previous: _ZoneView, last: _ZoneView, direction: StrokeDirection
) -> int | None:
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
    start = max(0, zone.start + 2)
    stop = min(len(units) - 1, zone.end + 1)
    for pos in range(start, stop + 1):
        unit = units[pos]
        if unit.direction is not direction:
            continue
        if direction is StrokeDirection.DOWN:
            if unit.start_value >= zone.zd - _EPS and unit.end_value < zone.zd - _EPS:
                return pos
        else:
            if unit.start_value <= zone.zg + _EPS and unit.end_value > zone.zg + _EPS:
                return pos
    return None


def _macd_histogram(raw_bars: Sequence[RawBar]) -> dict[datetime, float]:
    bars = tuple(sorted(raw_bars, key=lambda x: x.open_time))
    if not bars:
        return {}
    closes = [float(x.close) for x in bars]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    hist = [2.0 * (a - b) for a, b in zip(dif, dea)]
    return {bar.open_time: value for bar, value in zip(bars, hist)}


def _ema(values: Sequence[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def _directional_macd_area(
    unit: Any, direction: StrokeDirection, macd: dict[datetime, float]
) -> float:
    values = [
        value
        for dt, value in macd.items()
        if unit.source_start <= dt <= unit.source_end
    ]
    # MACD 在短走势刚切换时可能仍位于零轴另一侧；背驰比较采用该走势
    # 时间区间内柱体绝对面积，避免仅因零轴滞后把力度误记为 0。
    return float(sum(abs(x) for x in values))


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


def _segment_confirmation_dt(
    segment_index: int,
    segments: Sequence[Segment],
    evidence_map: dict[int, SegmentEvidence],
    strokes: Sequence[Stroke],
) -> datetime:
    evidence = evidence_map.get(segment_index)
    if evidence is not None and 0 <= evidence.confirmed_at_position < len(strokes):
        return strokes[evidence.confirmed_at_position].end_dt
    segment = next(x for x in segments if x.index == segment_index)
    return segment.fx_b.source_end
