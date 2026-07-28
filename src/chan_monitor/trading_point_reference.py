from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import pandas as pd

from .models import RawBar, Segment, SegmentCentralZone, SegmentEvidence, Stroke, TradingPoint, unique_elements

REFERENCE_NAME = "缠论走势级别递归规则 + MACD 背驰量化（独立字典复算）"
REFERENCE_CXT_URL = "https://github.com/waditu/czsc"
REFERENCE_WIKI_URL = "https://czsc.readthedocs.io/en/0.9.6/_static/%E7%BC%A0%E4%B8%AD%E8%AF%B4%E7%A6%85%E6%8A%80%E6%9C%AF%E5%8E%9F%E7%90%86.html"
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class FrozenTradingPoint:
    point_type: str
    dt: object
    price: float
    segment_index: int
    evidence_kind: str
    zone_index: int | None
    related_segment_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TradingPointReferenceComparison:
    reference_name: str
    cxt_url: str
    wiki_url: str
    rows: tuple[dict[str, object], ...]

    @property
    def match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.rows)

    @property
    def all_match(self) -> bool:
        return self.match_count == len(self.rows)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def summary(self) -> dict[str, object]:
        return {
            "trading_point_reference_name": self.reference_name,
            "trading_point_reference_cxt_url": self.cxt_url,
            "trading_point_reference_wiki_url": self.wiki_url,
            "trading_point_comparison_rows": len(self.rows),
            "trading_point_match_count": self.match_count,
            "trading_points_match": self.all_match,
        }


def run_frozen_trading_point_reference(
    segments: Sequence[Segment],
    zones: Sequence[SegmentCentralZone],
    *,
    raw_bars: Sequence[RawBar] = (),
) -> tuple[FrozenTradingPoint, ...]:
    """以基础字典独立复算，不调用生产买卖点识别器。"""
    units = tuple(_unit_dict(x) for x in segments)
    zone_dicts = tuple(
        {
            "index": int(x.index), "start": int(x.start_position), "end": int(x.end_position),
            "zg": float(x.zg), "zd": float(x.zd), "gg": float(x.gg), "dd": float(x.dd),
        }
        for x in zones
    )
    bars = tuple(sorted(raw_bars or _bars_from_segments(segments), key=lambda x: x.open_time))
    hist = _hist(bars)
    out: list[FrozenTradingPoint] = []

    first = _first_points(units, zone_dicts, hist, segment_index_override=None)
    out.extend(first)

    by_index = {int(x["index"]): i for i, x in enumerate(units)}
    for p in first:
        pos = by_index[p.segment_index]
        if pos + 2 >= len(units):
            continue
        rebound, retrace = units[pos + 1], units[pos + 2]
        is_buy = p.point_type == "B1"
        direction_ok = (
            rebound["direction"] == ("up" if is_buy else "down")
            and retrace["direction"] == ("down" if is_buy else "up")
        )
        price_ok = float(retrace["end"]) >= p.price - _EPS if is_buy else float(retrace["end"]) <= p.price + _EPS
        if not (direction_ok and price_ok):
            continue
        local_strokes = tuple(_unit_dict(x) for x in segments[pos + 2].strokes)
        local_zones = _stroke_zones(local_strokes)
        local_first = _first_points(
            local_strokes, local_zones, hist, segment_index_override=int(retrace["index"])
        )
        needed = "B1" if is_buy else "S1"
        lower_ok = any(
            x.point_type == needed and x.dt == retrace["end_dt"] and abs(x.price - float(retrace["end"])) <= _EPS
            for x in local_first
        )
        if lower_ok:
            out.append(
                FrozenTradingPoint(
                    "B2" if is_buy else "S2",
                    retrace["end_dt"],
                    float(retrace["end"]),
                    int(retrace["index"]),
                    "SUBLEVEL_BS1_ON_FIRST_RETRACE",
                    None,
                    (p.segment_index, int(rebound["index"]), int(retrace["index"])),
                )
            )

    for z in zone_dicts:
        departure_pos = None
        kind = None
        for pos in range(max(0, int(z["start"]) + 2), min(len(units), int(z["end"]) + 2)):
            unit = units[pos]
            if unit["direction"] == "up" and float(unit["end"]) > float(z["zg"]) + _EPS:
                departure_pos, kind = pos, "B3"
                break
            if unit["direction"] == "down" and float(unit["end"]) < float(z["zd"]) - _EPS:
                departure_pos, kind = pos, "S3"
                break
        if departure_pos is None or kind is None or departure_pos + 1 >= len(units):
            continue
        depart, pullback = units[departure_pos], units[departure_pos + 1]
        valid = (
            kind == "B3" and pullback["direction"] == "down" and float(pullback["low"]) >= float(z["zg"]) - _EPS
        ) or (
            kind == "S3" and pullback["direction"] == "up" and float(pullback["high"]) <= float(z["zd"]) + _EPS
        )
        if valid:
            out.append(
                FrozenTradingPoint(
                    kind, pullback["end_dt"], float(pullback["end"]), int(pullback["index"]),
                    "ZONE_DEPARTURE_FIRST_RETEST", int(z["index"]),
                    (int(depart["index"]), int(pullback["index"])),
                )
            )

    unique = {(x.point_type, x.dt, x.segment_index): x for x in out}
    return tuple(sorted(unique.values(), key=lambda x: (x.dt, x.point_type, x.segment_index)))


def compare_trading_points_with_reference(
    points: Sequence[TradingPoint],
    segments: Sequence[Segment],
    zones: Sequence[SegmentCentralZone],
    *,
    raw_bars: Sequence[RawBar] = (),
    segment_evidence: Sequence[SegmentEvidence] = (),
    strokes: Sequence[Stroke] = (),
) -> TradingPointReferenceComparison:
    reference = run_frozen_trading_point_reference(segments, zones, raw_bars=raw_bars)
    rows = []
    for i in range(max(len(points), len(reference))):
        ours = points[i] if i < len(points) else None
        ref = reference[i] if i < len(reference) else None
        match = _same(ours, ref)
        rows.append(
            {
                "序号": i, "一致": match,
                "本项目类型": ours.point_type.value if ours else None, "参考类型": ref.point_type if ref else None,
                "本项目时间": ours.dt if ours else None, "参考时间": ref.dt if ref else None,
                "本项目价格": ours.price if ours else None, "参考价格": ref.price if ref else None,
                "本项目线段": ours.segment_index if ours else None, "参考线段": ref.segment_index if ref else None,
                "本项目证据": ours.evidence_kind if ours else None, "参考证据": ref.evidence_kind if ref else None,
                "本项目中枢": ours.zone_index if ours else None, "参考中枢": ref.zone_index if ref else None,
                "本项目关联线段": " | ".join(str(x) for x in ours.related_segment_indexes) if ours else None,
                "参考关联线段": " | ".join(str(x) for x in ref.related_segment_indexes) if ref else None,
            }
        )
    return TradingPointReferenceComparison(REFERENCE_NAME, REFERENCE_CXT_URL, REFERENCE_WIKI_URL, tuple(rows))


def _first_points(units, zones, hist, segment_index_override):
    out = []
    for previous, last in zip(zones, zones[1:]):
        if float(last["zg"]) < float(previous["zd"]) - _EPS:
            direction, kind = "down", "B1"
        elif float(last["zd"]) > float(previous["zg"]) + _EPS:
            direction, kind = "up", "S1"
        else:
            continue
        entry = _entry(units, previous, last, direction)
        exit_ = _exit(units, last, direction)
        if entry is None or exit_ is None:
            continue
        a, b = units[entry], units[exit_]
        extreme = float(b["end"]) < float(a["end"]) - _EPS if direction == "down" else float(b["end"]) > float(a["end"]) + _EPS
        area_a, area_b = _area(a, hist), _area(b, hist)
        if extreme and area_a > _EPS and area_b < area_a - _EPS:
            out.append(
                FrozenTradingPoint(
                    kind, b["end_dt"], float(b["end"]),
                    segment_index_override if segment_index_override is not None else int(b["index"]),
                    "TREND_MACD_DIVERGENCE", int(last["index"]),
                    (int(a["index"]), int(b["index"])),
                )
            )
    return out


def _entry(units, previous, last, direction):
    lo, hi = max(0, int(previous["end"])), min(len(units) - 1, int(last["start"]) - 1)
    for pos in range(hi, lo - 1, -1):
        x = units[pos]
        if x["direction"] != direction:
            continue
        if direction == "down" and float(x["start"]) > float(last["zg"]) + _EPS and float(x["end"]) <= float(last["zg"]) + _EPS:
            return pos
        if direction == "up" and float(x["start"]) < float(last["zd"]) - _EPS and float(x["end"]) >= float(last["zd"]) - _EPS:
            return pos
    return None


def _exit(units, zone, direction):
    start, stop = max(0, int(zone["start"]) + 2), min(len(units) - 1, int(zone["end"]) + 1)
    for pos in range(start, stop + 1):
        x = units[pos]
        if x["direction"] != direction:
            continue
        if direction == "down" and float(x["start"]) >= float(zone["zd"]) - _EPS and float(x["end"]) < float(zone["zd"]) - _EPS:
            return pos
        if direction == "up" and float(x["start"]) <= float(zone["zg"]) + _EPS and float(x["end"]) > float(zone["zg"]) + _EPS:
            return pos
    return None


def _stroke_zones(units):
    groups = []
    for x in units:
        if not groups:
            groups.append([x]); continue
        current = groups[-1]
        first3 = current[:3]
        zg = min(float(v["high"]) for v in first3)
        zd = max(float(v["low"]) for v in first3)
        separated = (x["direction"] == "up" and float(x["high"]) < zd) or (x["direction"] == "down" and float(x["low"]) > zg)
        if separated:
            groups.append([x])
        else:
            current.append(x)
    zones = []
    cursor = 0
    for group in groups:
        start = cursor; end = cursor + len(group) - 1; cursor = end + 1
        if len(group) < 3:
            continue
        zg = min(float(v["high"]) for v in group[:3]); zd = max(float(v["low"]) for v in group[:3])
        if zg < zd:
            continue
        valid = all(float(v["high"]) >= zd and float(v["low"]) <= zg for v in group)
        if valid:
            zones.append({"index": len(zones), "start": start, "end": end, "zg": zg, "zd": zd,
                          "gg": max(float(v["high"]) for v in group), "dd": min(float(v["low"]) for v in group)})
    return tuple(zones)


def _unit_dict(x):
    return {
        "index": int(x.index), "direction": x.direction.value,
        "start_dt": x.start_dt, "end_dt": x.end_dt,
        "start": float(x.start_value), "end": float(x.end_value),
        "high": float(x.high), "low": float(x.low), "power": float(x.power),
        "source_start": x.source_start, "source_end": x.source_end,
    }


def _hist(bars):
    if not bars:
        return {}
    closes = [float(x.close) for x in bars]
    e12, e26 = _ema(closes, 12), _ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    return {x.open_time: 2 * (a - b) for x, a, b in zip(bars, dif, dea)}


def _ema(values, span):
    if not values: return []
    alpha = 2 / (span + 1); out = [float(values[0])]
    for x in values[1:]: out.append(alpha * float(x) + (1 - alpha) * out[-1])
    return out


def _area(unit, hist):
    return float(sum(abs(v) for dt, v in hist.items() if unit["source_start"] <= dt <= unit["source_end"]))


def _bars_from_segments(segments):
    values = []
    for segment in segments:
        for stroke in segment.strokes:
            for merged in stroke.bars: values.extend(merged.elements)
    return unique_elements(values)


def _same(ours: TradingPoint | None, ref: FrozenTradingPoint | None) -> bool:
    if ours is None or ref is None:
        return False
    return bool(
        ours.point_type.value == ref.point_type and ours.dt == ref.dt
        and abs(ours.price - ref.price) <= _EPS and ours.segment_index == ref.segment_index
        and ours.evidence_kind == ref.evidence_kind and ours.zone_index == ref.zone_index
        and ours.related_segment_indexes == ref.related_segment_indexes
    )
