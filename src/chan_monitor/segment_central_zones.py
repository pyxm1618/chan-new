from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import Segment, SegmentCentralZone, SegmentCentralZoneDiagnostic


@dataclass(frozen=True, slots=True)
class SegmentCentralZoneDetectionResult:
    """线段中枢识别结果。

    ``candidates`` 保存每一个满足“三个连续线段有共同重叠区”的原始三段窗口；
    ``zones`` 保存按时间最早优先、向后最大延伸得到的互不重叠中枢序列。
    """

    zones: tuple[SegmentCentralZone, ...]
    candidates: tuple[SegmentCentralZone, ...]
    diagnostics: tuple[SegmentCentralZoneDiagnostic, ...]


def detect_segment_central_zones(
    segments: Sequence[Segment],
) -> SegmentCentralZoneDetectionResult:
    """从已确认线段链识别线段中枢。

    规则：

    1. 任意三个连续线段的价格区间存在非空共同交集，构成中枢种子；
    2. ``ZG = min(high[0:3])``，``ZD = max(low[0:3])``，边界由种子前三段固定；
    3. 后续线段与固定 ``[ZD, ZG]`` 相交时，中枢继续延伸；
    4. 第一条不相交线段不属于旧中枢，并作为后续新中枢搜索的起点；
    5. 对多义窗口采用“时间最早的有效三段优先，随后最大延伸”的确定性口径。

    输入只能是标准特征序列确认后的最终线段，未完成线段尾部不会参与中枢计算。
    """
    values = tuple(segments)
    if len(values) < 3:
        return SegmentCentralZoneDetectionResult((), (), ())

    diagnostics: list[SegmentCentralZoneDiagnostic] = []
    candidates: list[SegmentCentralZone] = []
    candidate_by_start: dict[int, SegmentCentralZone] = {}

    for start in range(len(values) - 2):
        candidate = SegmentCentralZone(
            symbol=values[start].symbol,
            segments=values[start : start + 3],
            start_position=start,
            end_position=start + 2,
        )
        if candidate.is_valid:
            candidates.append(candidate)
            candidate_by_start[start] = candidate
            diagnostics.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_SEED",
                    message=(
                        f"线段位置 {start}~{start + 2} 的共同重叠区为 "
                        f"[{candidate.zd:.12g}, {candidate.zg:.12g}]，形成线段中枢种子"
                    ),
                    dt=candidate.sdt,
                )
            )

    zones: list[SegmentCentralZone] = []
    cursor = 0
    while cursor <= len(values) - 3:
        seed = candidate_by_start.get(cursor)
        if seed is None:
            cursor += 1
            continue

        end = cursor + 2
        while end + 1 < len(values):
            next_segment = values[end + 1]
            if not _intersects(next_segment.low, next_segment.high, seed.zd, seed.zg):
                diagnostics.append(
                    SegmentCentralZoneDiagnostic(
                        code="SEGMENT_CENTRAL_ZONE_ENDED",
                        message=(
                            f"第 {end + 1} 条线段区间 "
                            f"[{next_segment.low:.12g}, {next_segment.high:.12g}] 不再与 "
                            f"[{seed.zd:.12g}, {seed.zg:.12g}] 重叠，前一线段中枢结束"
                        ),
                        dt=next_segment.start_dt,
                    )
                )
                break
            end += 1
            diagnostics.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_EXTENDED",
                    message=(
                        f"第 {end} 条线段仍与固定中枢区间 "
                        f"[{seed.zd:.12g}, {seed.zg:.12g}] 重叠，中枢延伸"
                    ),
                    dt=values[end].start_dt,
                )
            )

        zone = SegmentCentralZone(
            symbol=values[cursor].symbol,
            segments=values[cursor : end + 1],
            index=len(zones),
            start_position=cursor,
            end_position=end,
        )
        zones.append(zone)
        cursor = end + 1

    return SegmentCentralZoneDetectionResult(
        zones=tuple(zones),
        candidates=tuple(candidates),
        diagnostics=tuple(diagnostics),
    )


def validate_segment_central_zones(
    zones: Sequence[SegmentCentralZone],
    segments: Sequence[Segment],
) -> tuple[SegmentCentralZoneDiagnostic, ...]:
    """校验线段中枢的三段重叠、连续切片、延伸与最大性。"""
    issues: list[SegmentCentralZoneDiagnostic] = []
    master = tuple(segments)
    previous_end = -1

    for expected_index, zone in enumerate(zones):
        if zone.index != expected_index:
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_INDEX_INVALID",
                    message=f"第 {expected_index} 个线段中枢的内部序号为 {zone.index}",
                    dt=zone.sdt,
                )
            )
        if zone.segment_count < 3:
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_TOO_SHORT",
                    message=f"第 {expected_index} 个线段中枢只有 {zone.segment_count} 段",
                    dt=zone.sdt,
                )
            )
        if zone.start_position <= previous_end:
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_POSITION_OVERLAP",
                    message=f"第 {expected_index} 个线段中枢与前一中枢的位置范围重叠",
                    dt=zone.sdt,
                )
            )
        previous_end = zone.end_position

        if zone.start_position < 0 or zone.end_position >= len(master):
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_POSITION_OUT_OF_RANGE",
                    message=f"第 {expected_index} 个线段中枢位置范围越界",
                    dt=zone.sdt,
                )
            )
            continue

        expected_slice = master[zone.start_position : zone.end_position + 1]
        if tuple(zone.segments) != expected_slice:
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_SEGMENTS_NOT_CONTIGUOUS",
                    message=f"第 {expected_index} 个线段中枢不是最终线段链的连续切片",
                    dt=zone.sdt,
                )
            )

        expected_zg = min(x.high for x in zone.segments[:3])
        expected_zd = max(x.low for x in zone.segments[:3])
        if not _float_equal(zone.zg, expected_zg) or not _float_equal(zone.zd, expected_zd):
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_BOUNDARY_MISMATCH",
                    message=(
                        f"第 {expected_index} 个线段中枢边界不是前三段交集："
                        f"实际 ZD/ZG={zone.zd:.12g}/{zone.zg:.12g}，"
                        f"应为 {expected_zd:.12g}/{expected_zg:.12g}"
                    ),
                    dt=zone.sdt,
                )
            )

        if zone.zg < zone.zd or not zone.is_valid:
            issues.append(
                SegmentCentralZoneDiagnostic(
                    code="SEGMENT_CENTRAL_ZONE_INVALID",
                    message=f"第 {expected_index} 个线段中枢没有有效共同重叠区",
                    dt=zone.sdt,
                )
            )

        for segment in zone.segments:
            if not _intersects(segment.low, segment.high, zone.zd, zone.zg):
                issues.append(
                    SegmentCentralZoneDiagnostic(
                        code="SEGMENT_CENTRAL_ZONE_SEGMENT_OUTSIDE",
                        message=(
                            f"第 {expected_index} 个线段中枢内第 {segment.index} 条线段区间 "
                            f"[{segment.low:.12g}, {segment.high:.12g}] 与 "
                            f"[{zone.zd:.12g}, {zone.zg:.12g}] 不重叠"
                        ),
                        dt=segment.start_dt,
                    )
                )

        next_position = zone.end_position + 1
        if next_position < len(master):
            next_segment = master[next_position]
            if _intersects(next_segment.low, next_segment.high, zone.zd, zone.zg):
                issues.append(
                    SegmentCentralZoneDiagnostic(
                        code="SEGMENT_CENTRAL_ZONE_NOT_MAXIMAL",
                        message=(
                            f"第 {expected_index} 个线段中枢还能延伸到第 {next_position} 条线段，"
                            "但结果提前结束"
                        ),
                        dt=next_segment.start_dt,
                    )
                )

    return tuple(issues)


def _intersects(low: float, high: float, zd: float, zg: float) -> bool:
    return high >= zd and low <= zg


def _float_equal(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return abs(a - b) <= tolerance
