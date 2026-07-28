from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from .models import CentralZone, Stroke

REFERENCE_GROUP_NAME = "CZSC 0.9.53 get_zs_seq + 当前 Rust ZS::new/is_valid（冻结逻辑）"
REFERENCE_GROUP_URL = "https://czsc.readthedocs.io/en/0.9.53/_modules/czsc/utils/sig.html"
REFERENCE_OBJECT_URL = "https://github.com/waditu/czsc/blob/master/crates/czsc-core/src/objects/zs.rs"


@dataclass(frozen=True, slots=True)
class LegacyZone:
    group_index: int
    stroke_indexes: tuple[int, ...]
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
    def stroke_count(self) -> int:
        return len(self.stroke_indexes)


@dataclass(frozen=True, slots=True)
class CentralZoneReferenceComparison:
    reference_name: str
    reference_url: str
    object_url: str
    group_rows: tuple[dict[str, object], ...]
    zone_rows: tuple[dict[str, object], ...]

    @property
    def group_match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.group_rows)

    @property
    def zone_match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.zone_rows)

    @property
    def group_match(self) -> bool:
        return self.group_match_count == len(self.group_rows)

    @property
    def zone_match(self) -> bool:
        return self.zone_match_count == len(self.zone_rows)

    @property
    def all_match(self) -> bool:
        return self.group_match and self.zone_match

    def group_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.group_rows)

    def zone_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.zone_rows)

    def summary(self) -> dict[str, object]:
        return {
            "central_zone_reference_name": self.reference_name,
            "central_zone_reference_url": self.reference_url,
            "central_zone_object_url": self.object_url,
            "central_zone_group_rows": len(self.group_rows),
            "central_zone_group_match_count": self.group_match_count,
            "central_zone_groups_match": self.group_match,
            "central_zone_rows": len(self.zone_rows),
            "central_zone_match_count": self.zone_match_count,
            "central_zones_match": self.zone_match,
            "central_zones_all_match": self.all_match,
        }


def run_frozen_czsc_central_zone_reference(strokes: Sequence[Stroke]) -> tuple[LegacyZone, ...]:
    """独立翻译 ``get_zs_seq`` 和 Rust ``ZS::new/is_valid``，不调用项目实现。"""
    primitive = [
        {
            "index": int(x.index),
            "start_dt": x.start_dt,
            "end_dt": x.end_dt,
            "direction": x.direction.value,
            "high": float(x.high),
            "low": float(x.low),
        }
        for x in strokes
    ]

    raw_groups: list[list[dict[str, object]]] = []
    for bi in primitive:
        if not raw_groups:
            raw_groups.append([bi])
            continue
        current = raw_groups[-1]
        zg = min(float(x["high"]) for x in current[:3])
        zd = max(float(x["low"]) for x in current[:3])
        if (bi["direction"] == "up" and float(bi["high"]) < zd) or (
            bi["direction"] == "down" and float(bi["low"]) > zg
        ):
            raw_groups.append([bi])
        else:
            current.append(bi)

    values: list[LegacyZone] = []
    for i, group in enumerate(raw_groups):
        zg = min(float(x["high"]) for x in group[:3])
        zd = max(float(x["low"]) for x in group[:3])
        gg = max(float(x["high"]) for x in group)
        dd = min(float(x["low"]) for x in group)
        valid = len(group) >= 3 and zg >= zd
        if valid:
            valid = all(
                (zd <= float(x["high"]) <= zg)
                or (zd <= float(x["low"]) <= zg)
                or (float(x["high"]) >= zg and float(x["low"]) <= zd)
                for x in group
            )
        values.append(
            LegacyZone(
                group_index=i,
                stroke_indexes=tuple(int(x["index"]) for x in group),
                sdt=group[0]["start_dt"],
                edt=group[-1]["end_dt"],
                sdir=str(group[0]["direction"]),
                edir=str(group[-1]["direction"]),
                zg=zg,
                zd=zd,
                zz=zd + (zg - zd) * 0.5,
                gg=gg,
                dd=dd,
                valid=valid,
            )
        )
    return tuple(values)


def compare_central_zones_with_czsc(
    zones: Sequence[CentralZone],
    groups: Sequence[CentralZone],
    strokes: Sequence[Stroke],
) -> CentralZoneReferenceComparison:
    reference_groups = run_frozen_czsc_central_zone_reference(strokes)
    group_rows = _compare_groups(groups, reference_groups)
    reference_zones = tuple(x for x in reference_groups if x.valid)
    zone_rows = _compare_zones(zones, reference_zones)
    return CentralZoneReferenceComparison(
        reference_name=REFERENCE_GROUP_NAME,
        reference_url=REFERENCE_GROUP_URL,
        object_url=REFERENCE_OBJECT_URL,
        group_rows=tuple(group_rows),
        zone_rows=tuple(zone_rows),
    )


def _compare_groups(
    ours_values: Sequence[CentralZone],
    ref_values: Sequence[LegacyZone],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(max(len(ours_values), len(ref_values))):
        ours = ours_values[i] if i < len(ours_values) else None
        ref = ref_values[i] if i < len(ref_values) else None
        match = _same_zone(ours, ref, compare_index=False)
        rows.append(_row(i, ours, ref, match, kind="分组"))
    return rows


def _compare_zones(
    ours_values: Sequence[CentralZone],
    ref_values: Sequence[LegacyZone],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(max(len(ours_values), len(ref_values))):
        ours = ours_values[i] if i < len(ours_values) else None
        ref = ref_values[i] if i < len(ref_values) else None
        match = _same_zone(ours, ref, compare_index=False)
        rows.append(_row(i, ours, ref, match, kind="有效中枢"))
    return rows


def _same_zone(ours: CentralZone | None, ref: LegacyZone | None, *, compare_index: bool) -> bool:
    if ours is None or ref is None:
        return False
    return bool(
        (not compare_index or ours.group_index == ref.group_index)
        and tuple(x.index for x in ours.strokes) == ref.stroke_indexes
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
    i: int,
    ours: CentralZone | None,
    ref: LegacyZone | None,
    match: bool,
    *,
    kind: str,
) -> dict[str, object]:
    return {
        "类型": kind,
        "序号": i,
        "一致": match,
        "本项目分组序号": ours.group_index if ours else None,
        "CZSC分组序号": ref.group_index if ref else None,
        "本项目起点": ours.sdt if ours else None,
        "CZSC起点": ref.sdt if ref else None,
        "本项目终点": ours.edt if ours else None,
        "CZSC终点": ref.edt if ref else None,
        "本项目笔序号": _ours_indexes(ours),
        "CZSC笔序号": " | ".join(str(x) for x in ref.stroke_indexes) if ref else None,
        "本项目笔数": ours.stroke_count if ours else None,
        "CZSC笔数": ref.stroke_count if ref else None,
        "本项目ZG": ours.zg if ours else None,
        "CZSC ZG": ref.zg if ref else None,
        "本项目ZD": ours.zd if ours else None,
        "CZSC ZD": ref.zd if ref else None,
        "本项目ZZ": ours.zz if ours else None,
        "CZSC ZZ": ref.zz if ref else None,
        "本项目GG": ours.gg if ours else None,
        "CZSC GG": ref.gg if ref else None,
        "本项目DD": ours.dd if ours else None,
        "CZSC DD": ref.dd if ref else None,
        "本项目有效": ours.is_valid if ours else None,
        "CZSC有效": ref.valid if ref else None,
    }


def _ours_indexes(value: CentralZone | None) -> str | None:
    if value is None:
        return None
    return " | ".join(str(x.index) for x in value.strokes)


def _eq(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return abs(a - b) <= tolerance
