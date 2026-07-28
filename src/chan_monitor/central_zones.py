from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .models import CentralZone, CentralZoneDiagnostic, Stroke, StrokeDirection


@dataclass(frozen=True, slots=True)
class CentralZoneDetectionResult:
    """笔中枢识别结果。

    ``groups`` 保留 CZSC ``get_zs_seq`` 生成的全部连续分组，便于数据层逐项校验；
    ``zones`` 只包含至少三笔且通过当前 CZSC ``ZS.is_valid`` 规则的有效中枢。
    """

    zones: tuple[CentralZone, ...]
    groups: tuple[CentralZone, ...]
    diagnostics: tuple[CentralZoneDiagnostic, ...]


def detect_central_zones(strokes: Sequence[Stroke]) -> CentralZoneDetectionResult:
    """从已确认笔链识别笔中枢。

    分组逻辑按 CZSC 0.9.53 ``get_zs_seq``：

    - 当前向上笔的最高点低于当前分组下沿 ``ZD`` 时，开启新分组；
    - 当前向下笔的最低点高于当前分组上沿 ``ZG`` 时，开启新分组；
    - 其他情况把当前笔追加到原分组。

    每个分组的 ``ZG / ZD / ZZ / GG / DD`` 与当前 Rust ``ZS`` 一致：
    ``ZG``、``ZD`` 由前三笔重叠区确定；有效中枢要求至少三笔、``ZG >= ZD``，
    且分组内每一笔都与 ``[ZD, ZG]`` 相交或完整覆盖该区间。
    """
    if not strokes:
        return CentralZoneDetectionResult((), (), ())

    stroke_groups: list[list[Stroke]] = []
    diagnostics: list[CentralZoneDiagnostic] = []

    for stroke in strokes:
        if not stroke_groups:
            stroke_groups.append([stroke])
            continue

        current_strokes = stroke_groups[-1]
        current = CentralZone(
            symbol=current_strokes[0].symbol,
            strokes=tuple(current_strokes),
            group_index=len(stroke_groups) - 1,
        )
        separated = (
            stroke.direction is StrokeDirection.UP and stroke.high < current.zd
        ) or (
            stroke.direction is StrokeDirection.DOWN and stroke.low > current.zg
        )
        if separated:
            diagnostics.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_GROUP_SPLIT",
                    message=(
                        f"第 {stroke.index} 笔（{stroke.direction.label}，"
                        f"区间 {stroke.low:.12g}~{stroke.high:.12g}）与当前中枢分组"
                        f" [{current.zd:.12g}, {current.zg:.12g}] 按 CZSC 方向规则分离，开启新分组"
                    ),
                    dt=stroke.start_dt,
                )
            )
            stroke_groups.append([stroke])
        else:
            current_strokes.append(stroke)

    groups = tuple(
        CentralZone(
            symbol=group[0].symbol,
            strokes=tuple(group),
            group_index=i,
        )
        for i, group in enumerate(stroke_groups)
    )

    zones: list[CentralZone] = []
    for group in groups:
        if group.stroke_count < 3:
            diagnostics.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_TOO_SHORT",
                    message=f"第 {group.group_index} 分组只有 {group.stroke_count} 笔，不足三笔，不构成中枢",
                    dt=group.sdt,
                )
            )
            continue
        if not group.is_valid:
            diagnostics.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_INVALID_OVERLAP",
                    message=(
                        f"第 {group.group_index} 分组未通过 ZS.is_valid："
                        f"ZG={group.zg:.12g}, ZD={group.zd:.12g}，或存在不与中枢区间相交的笔"
                    ),
                    dt=group.sdt,
                )
            )
            continue
        zones.append(replace(group, index=len(zones)))

    return CentralZoneDetectionResult(
        zones=tuple(zones),
        groups=groups,
        diagnostics=tuple(diagnostics),
    )


def validate_central_zones(
    zones: Sequence[CentralZone],
    strokes: Sequence[Stroke],
) -> tuple[CentralZoneDiagnostic, ...]:
    """验证中枢边界、连续笔切片与 CZSC ``ZS.is_valid`` 不变量。"""
    issues: list[CentralZoneDiagnostic] = []
    if not zones:
        return ()

    master_spans = [(x.start_dt, x.end_dt) for x in strokes]
    cursor = 0
    for i, zone in enumerate(zones):
        if zone.index != i:
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_INDEX_INVALID",
                    message=f"第 {i} 个中枢的内部序号为 {zone.index}",
                    dt=zone.sdt,
                )
            )
        if zone.stroke_count < 3:
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_TOO_SHORT",
                    message=f"第 {i} 个中枢只有 {zone.stroke_count} 笔",
                    dt=zone.sdt,
                )
            )
        if zone.zg < zone.zd:
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_EMPTY_OVERLAP",
                    message=f"第 {i} 个中枢 ZG={zone.zg:.12g} 小于 ZD={zone.zd:.12g}",
                    dt=zone.sdt,
                )
            )
        if not zone.is_valid:
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_INVALID",
                    message=f"第 {i} 个中枢未通过 CZSC ZS.is_valid",
                    dt=zone.sdt,
                )
            )

        spans = [(x.start_dt, x.end_dt) for x in zone.strokes]
        try:
            start = master_spans.index(spans[0], cursor)
        except (ValueError, IndexError):
            start = -1
        if start < 0 or master_spans[start : start + len(spans)] != spans:
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_STROKES_NOT_CONTIGUOUS",
                    message=f"第 {i} 个中枢内部笔不是最终笔链的连续切片",
                    dt=zone.sdt,
                )
            )
        else:
            cursor = start + len(spans)

        expected_zg = min(x.high for x in zone.strokes[:3])
        expected_zd = max(x.low for x in zone.strokes[:3])
        if not _float_equal(zone.zg, expected_zg) or not _float_equal(zone.zd, expected_zd):
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_BOUNDARY_MISMATCH",
                    message=(
                        f"第 {i} 个中枢边界不是前三笔交集："
                        f"实际 ZD/ZG={zone.zd:.12g}/{zone.zg:.12g}，"
                        f"应为 {expected_zd:.12g}/{expected_zg:.12g}"
                    ),
                    dt=zone.sdt,
                )
            )

        for stroke in zone.strokes:
            if not _intersects(stroke.low, stroke.high, zone.zd, zone.zg):
                issues.append(
                    CentralZoneDiagnostic(
                        code="CENTRAL_ZONE_STROKE_OUTSIDE",
                        message=(
                            f"第 {i} 个中枢内第 {stroke.index} 笔区间 "
                            f"[{stroke.low:.12g}, {stroke.high:.12g}] 与 "
                            f"[{zone.zd:.12g}, {zone.zg:.12g}] 不相交"
                        ),
                        dt=stroke.start_dt,
                    )
                )

        if i and zones[i - 1].edt > zone.sdt:
            issues.append(
                CentralZoneDiagnostic(
                    code="CENTRAL_ZONE_TIME_OVERLAP",
                    message=f"第 {i - 1}、{i} 个中枢时间范围发生重叠",
                    dt=zone.sdt,
                )
            )

    return tuple(issues)


def _intersects(low: float, high: float, zd: float, zg: float) -> bool:
    high_in_range = zd <= high <= zg
    low_in_range = zd <= low <= zg
    contains_range = high >= zg and low <= zd
    return high_in_range or low_in_range or contains_range


def _float_equal(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return abs(a - b) <= tolerance
