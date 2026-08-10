from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from .models import Segment, SegmentCentralZone

REFERENCE_NAME = "线段中枢标准定义（三个连续线段重叠）+ CZSC ZS 数值公式（独立冻结实现）"
REFERENCE_DEFINITION_URL = (
    "https://czsc.readthedocs.io/en/0.9.6/_static/"
    "%E7%BC%A0%E4%B8%AD%E8%AF%B4%E7%A6%85%E6%8A%80%E6%9C%AF%E5%8E%9F%E7%90%86.html"
)
REFERENCE_OBJECT_URL = "https://github.com/waditu/czsc/blob/master/crates/czsc-core/src/objects/zs.rs"


@dataclass(frozen=True, slots=True)
class FrozenSegmentZone:
    index: int
    start_position: int
    end_position: int
    segment_indexes: tuple[int, ...]
    sdt: object
    edt: object
    sdir: str
    edir: str
    zg: float
    zd: float
    zz: float
    gg: float
    dd: float
    valid: bool

    @property
    def segment_count(self) -> int:
        return len(self.segment_indexes)


@dataclass(frozen=True, slots=True)
class SegmentCentralZoneReferenceComparison:
    reference_name: str
    definition_url: str
    object_url: str
    candidate_rows: tuple[dict[str, object], ...]
    zone_rows: tuple[dict[str, object], ...]

    @property
    def candidate_match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.candidate_rows)

    @property
    def zone_match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.zone_rows)

    @property
    def candidates_match(self) -> bool:
        return self.candidate_match_count == len(self.candidate_rows)

    @property
    def zones_match(self) -> bool:
        return self.zone_match_count == len(self.zone_rows)

    @property
    def all_match(self) -> bool:
        return self.candidates_match and self.zones_match

    def candidate_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.candidate_rows)

    def zone_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.zone_rows)

    def summary(self) -> dict[str, object]:
        return {
            "segment_central_zone_reference_name": self.reference_name,
            "segment_central_zone_definition_url": self.definition_url,
            "segment_central_zone_object_url": self.object_url,
            "segment_central_zone_candidate_rows": len(self.candidate_rows),
            "segment_central_zone_candidate_match_count": self.candidate_match_count,
            "segment_central_zone_candidates_match": self.candidates_match,
            "segment_central_zone_rows": len(self.zone_rows),
            "segment_central_zone_match_count": self.zone_match_count,
            "segment_central_zones_match": self.zones_match,
            "segment_central_zones_all_match": self.all_match,
        }


def run_frozen_segment_central_zone_reference(
    segments: Sequence[Segment],
) -> tuple[tuple[FrozenSegmentZone, ...], tuple[FrozenSegmentZone, ...]]:
    """使用原始字典独立执行三段重叠、固定边界与最大延伸。"""
    raw = tuple(
        {
            "index": int(x.index),
            "start_dt": x.start_dt,
            "end_dt": x.end_dt,
            "direction": x.direction.value,
            # Lesson 78: the structural interval of a Segment is the actual
            # extrema reached by its constituent Strokes.  Keep this frozen
            # oracle independent from the production Segment.high/low
            # properties by recomputing the interval directly from strokes.
            "high": float(max(stroke.high for stroke in x.strokes)),
            "low": float(min(stroke.low for stroke in x.strokes)),
        }
        for x in segments
    )
    if len(raw) < 3:
        return (), ()

    candidates: list[FrozenSegmentZone] = []
    valid_starts: set[int] = set()
    for start in range(0, len(raw) - 2):
        triple = raw[start : start + 3]
        upper = min(float(x["high"]) for x in triple)
        lower = max(float(x["low"]) for x in triple)
        if upper >= lower:
            valid_starts.add(start)
            candidates.append(_make_frozen(-1, start, start + 2, raw))

    zones: list[FrozenSegmentZone] = []
    position = 0
    while position + 2 < len(raw):
        if position not in valid_starts:
            position += 1
            continue

        seed = raw[position : position + 3]
        upper = min(float(x["high"]) for x in seed)
        lower = max(float(x["low"]) for x in seed)
        last = position + 2
        probe = last + 1
        while probe < len(raw):
            item = raw[probe]
            overlaps = float(item["high"]) >= lower and float(item["low"]) <= upper
            if not overlaps:
                break
            last = probe
            probe += 1

        zones.append(_make_frozen(len(zones), position, last, raw))
        position = last + 1

    return tuple(zones), tuple(candidates)


def compare_segment_central_zones_with_reference(
    zones: Sequence[SegmentCentralZone],
    candidates: Sequence[SegmentCentralZone],
    segments: Sequence[Segment],
) -> SegmentCentralZoneReferenceComparison:
    reference_zones, reference_candidates = run_frozen_segment_central_zone_reference(segments)
    return SegmentCentralZoneReferenceComparison(
        reference_name=REFERENCE_NAME,
        definition_url=REFERENCE_DEFINITION_URL,
        object_url=REFERENCE_OBJECT_URL,
        candidate_rows=tuple(_compare(candidates, reference_candidates, "三段候选")),
        zone_rows=tuple(_compare(zones, reference_zones, "最终线段中枢")),
    )


def _make_frozen(
    index: int,
    start: int,
    end: int,
    raw: Sequence[dict[str, object]],
) -> FrozenSegmentZone:
    group = raw[start : end + 1]
    first_three = group[:3]
    zg = min(float(x["high"]) for x in first_three)
    zd = max(float(x["low"]) for x in first_three)
    valid = len(group) >= 3 and zg >= zd and all(
        float(x["high"]) >= zd and float(x["low"]) <= zg for x in group
    )
    return FrozenSegmentZone(
        index=index,
        start_position=start,
        end_position=end,
        segment_indexes=tuple(int(x["index"]) for x in group),
        sdt=group[0]["start_dt"],
        edt=group[-1]["end_dt"],
        sdir=str(group[0]["direction"]),
        edir=str(group[-1]["direction"]),
        zg=zg,
        zd=zd,
        zz=zd + (zg - zd) * 0.5,
        gg=max(float(x["high"]) for x in group),
        dd=min(float(x["low"]) for x in group),
        valid=valid,
    )


def _compare(
    ours_values: Sequence[SegmentCentralZone],
    reference_values: Sequence[FrozenSegmentZone],
    kind: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(max(len(ours_values), len(reference_values))):
        ours = ours_values[i] if i < len(ours_values) else None
        ref = reference_values[i] if i < len(reference_values) else None
        match = _same(ours, ref)
        rows.append(_row(kind, i, ours, ref, match))
    return rows


def _same(ours: SegmentCentralZone | None, ref: FrozenSegmentZone | None) -> bool:
    if ours is None or ref is None:
        return False
    return bool(
        ours.start_position == ref.start_position
        and ours.end_position == ref.end_position
        and tuple(x.index for x in ours.segments) == ref.segment_indexes
        and ours.sdt == ref.sdt
        and ours.edt == ref.edt
        and ours.sdir.value == ref.sdir
        and ours.edir.value == ref.edir
        and _eq(ours.zg, ref.zg)
        and _eq(ours.zd, ref.zd)
        and _eq(ours.zz, ref.zz)
        and _eq(ours.gg, ref.gg)
        and _eq(ours.dd, ref.dd)
        and ours.is_valid == ref.valid
    )


def _row(
    kind: str,
    i: int,
    ours: SegmentCentralZone | None,
    ref: FrozenSegmentZone | None,
    match: bool,
) -> dict[str, object]:
    return {
        "类型": kind,
        "序号": i,
        "一致": match,
        "本项目位置": f"{ours.start_position}~{ours.end_position}" if ours else None,
        "参考位置": f"{ref.start_position}~{ref.end_position}" if ref else None,
        "本项目线段序号": _ours_indexes(ours),
        "参考线段序号": " | ".join(str(x) for x in ref.segment_indexes) if ref else None,
        "本项目起点": ours.sdt if ours else None,
        "参考起点": ref.sdt if ref else None,
        "本项目终点": ours.edt if ours else None,
        "参考终点": ref.edt if ref else None,
        "本项目线段数": ours.segment_count if ours else None,
        "参考线段数": ref.segment_count if ref else None,
        "本项目ZG": ours.zg if ours else None,
        "参考ZG": ref.zg if ref else None,
        "本项目ZD": ours.zd if ours else None,
        "参考ZD": ref.zd if ref else None,
        "本项目ZZ": ours.zz if ours else None,
        "参考ZZ": ref.zz if ref else None,
        "本项目GG": ours.gg if ours else None,
        "参考GG": ref.gg if ref else None,
        "本项目DD": ours.dd if ours else None,
        "参考DD": ref.dd if ref else None,
        "本项目有效": ours.is_valid if ours else None,
        "参考有效": ref.valid if ref else None,
    }


def _ours_indexes(value: SegmentCentralZone | None) -> str | None:
    if value is None:
        return None
    return " | ".join(str(x.index) for x in value.segments)


def _eq(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return abs(a - b) <= tolerance
