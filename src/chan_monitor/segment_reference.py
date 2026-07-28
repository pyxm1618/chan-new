from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from .models import Fractal, FractalMark, MergedBar, Segment, Stroke, StrokeDirection
from .segments import SegmentMode, stroke_endpoints

REFERENCE_SEGMENT_NAME = "CZSC 0.3.9 KlineAnalyze._find_xd（冻结 Python 逻辑）"
REFERENCE_SEGMENT_URL = "https://github.com/waditu/czsc/blob/0.3.9/czsc/analyze.py#L399-L470"


@dataclass(frozen=True, slots=True)
class LegacySegmentPoint:
    dt: object
    mark: str
    value: float


@dataclass(frozen=True, slots=True)
class SegmentReferenceComparison:
    reference_name: str
    reference_url: str
    marker_rows: tuple[dict[str, object], ...]
    segment_rows: tuple[dict[str, object], ...]

    @property
    def marker_match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.marker_rows)

    @property
    def segment_match_count(self) -> int:
        return sum(bool(x["一致"]) for x in self.segment_rows)

    @property
    def marker_match(self) -> bool:
        return self.marker_match_count == len(self.marker_rows)

    @property
    def segment_match(self) -> bool:
        return self.segment_match_count == len(self.segment_rows)

    @property
    def all_match(self) -> bool:
        return self.marker_match and self.segment_match

    def marker_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.marker_rows)

    def segment_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.segment_rows)

    def summary(self) -> dict[str, object]:
        return {
            "segment_reference_name": self.reference_name,
            "segment_reference_url": self.reference_url,
            "segment_marker_rows": len(self.marker_rows),
            "segment_marker_match_count": self.marker_match_count,
            "segment_marker_match": self.marker_match,
            "segments_rows": len(self.segment_rows),
            "segments_match_count": self.segment_match_count,
            "segments_match": self.segment_match,
            "segments_all_match": self.all_match,
        }


def run_legacy_czsc_segment_reference(
    strokes: Sequence[Stroke],
    *,
    latest_bar: MergedBar | None = None,
    mode: SegmentMode | str = SegmentMode.STRICT,
    handle_last: bool = True,
) -> tuple[LegacySegmentPoint, ...]:
    """逐行翻译 CZSC 0.3.9 ``__extract_potential`` / ``__handle_hist_xd``。

    参考路径只接收本项目已确认的笔端点，目的是单独校验线段层，不把不同年代的
    笔定义差异混入比较。
    """
    mode = SegmentMode(mode)
    points = [
        {"dt": x.dt, "fx_mark": "d" if x.mark is FractalMark.BOTTOM else "g", "bi": x.value}
        for x in stroke_endpoints(strokes)
    ]

    def extract_potential(fx_mark: str) -> list[dict[str, object]]:
        seq = [x.copy() for x in points if x["fx_mark"] == fx_mark]
        seq = sorted(seq, key=lambda x: x["dt"])
        values: list[dict[str, object]] = []
        for i in range(len(seq) - 2):
            window = seq[i : i + 3]
            if fx_mark == "d":
                if window[0]["bi"] >= window[1]["bi"] <= window[2]["bi"]:
                    values.append(window[1].copy())
            elif fx_mark == "g":
                if window[0]["bi"] <= window[1]["bi"] >= window[2]["bi"]:
                    values.append(window[1].copy())
            else:  # pragma: no cover
                raise ValueError
        return values

    bi_p = [*extract_potential("d"), *extract_potential("g")]
    bi_p = sorted(bi_p, key=lambda x: x["dt"])
    xd: list[dict[str, object]] = []
    for source in bi_p:
        k = source.copy()
        k["xd"] = k["bi"]
        del k["bi"]
        if len(xd) == 0:
            xd.append(k)
        else:
            k0 = xd[-1]
            if k0["fx_mark"] == k["fx_mark"]:
                if (k0["fx_mark"] == "g" and k0["xd"] < k["xd"]) or (
                    k0["fx_mark"] == "d" and k0["xd"] > k["xd"]
                ):
                    xd.pop(-1)
                    xd.append(k)
            else:
                if (k0["fx_mark"] == "g" and k["xd"] >= k0["xd"]) or (
                    k0["fx_mark"] == "d" and k["xd"] <= k0["xd"]
                ):
                    xd.pop(-1)
                    continue
                bi_m = [x for x in points if k0["dt"] <= x["dt"] <= k["dt"]]
                bi_r = [x for x in points if x["dt"] >= k["dt"]]
                if len(bi_m) >= 4:
                    if len(bi_m) == 4:
                        if mode is SegmentMode.LOOSE:
                            if (k["fx_mark"] == "g" and bi_m[-1]["bi"] > bi_m[-3]["bi"]) or (
                                k["fx_mark"] == "d" and bi_m[-1]["bi"] < bi_m[-3]["bi"]
                            ):
                                xd.append(k)
                        elif mode is SegmentMode.STRICT:
                            if len(bi_r) <= 1:
                                continue
                            lp2 = bi_m[-2]
                            rp2 = bi_r[1]
                            if (
                                k["fx_mark"] == "g"
                                and lp2["bi"] < rp2["bi"]
                                and bi_m[-1]["bi"] > bi_m[-3]["bi"]
                            ) or (
                                k["fx_mark"] == "d"
                                and lp2["bi"] > rp2["bi"]
                                and bi_m[-1]["bi"] < bi_m[-3]["bi"]
                            ):
                                xd.append(k)
                        else:  # pragma: no cover
                            raise ValueError("xd_mode value error")
                    else:
                        xd.append(k)

    if handle_last and xd and latest_bar is not None:
        if (xd[-1]["fx_mark"] == "d" and latest_bar.low < xd[-1]["xd"]) or (
            xd[-1]["fx_mark"] == "g" and latest_bar.high > xd[-1]["xd"]
        ):
            xd.pop(-1)

    return tuple(
        LegacySegmentPoint(dt=x["dt"], mark=str(x["fx_mark"]), value=float(x["xd"]))
        for x in xd
    )


def compare_segments_with_legacy_czsc(
    segments: Sequence[Segment],
    markers: Sequence[Fractal],
    strokes: Sequence[Stroke],
    *,
    latest_bar: MergedBar | None = None,
    mode: SegmentMode | str = SegmentMode.STRICT,
) -> SegmentReferenceComparison:
    reference = run_legacy_czsc_segment_reference(
        strokes,
        latest_bar=latest_bar,
        mode=mode,
    )
    marker_rows: list[dict[str, object]] = []
    total = max(len(markers), len(reference))
    for i in range(total):
        ours = markers[i] if i < len(markers) else None
        ref = reference[i] if i < len(reference) else None
        ours_mark = None
        if ours is not None:
            ours_mark = "d" if ours.mark is FractalMark.BOTTOM else "g"
        match = bool(
            ours is not None
            and ref is not None
            and ours.dt == ref.dt
            and ours_mark == ref.mark
            and abs(ours.value - ref.value) <= 1e-9
        )
        marker_rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目时间": ours.dt if ours else None,
                "CZSC时间": ref.dt if ref else None,
                "本项目类型": ours.label if ours else None,
                "CZSC类型": _mark_label(ref.mark) if ref else None,
                "本项目价格": ours.value if ours else None,
                "CZSC价格": ref.value if ref else None,
            }
        )

    reference_segments = list(zip(reference, reference[1:]))
    segment_rows: list[dict[str, object]] = []
    total_segments = max(len(segments), len(reference_segments))
    for i in range(total_segments):
        ours = segments[i] if i < len(segments) else None
        ref = reference_segments[i] if i < len(reference_segments) else None
        ref_direction = None
        if ref:
            ref_direction = "up" if ref[0].mark == "d" else "down"
        match = bool(
            ours is not None
            and ref is not None
            and ours.start_dt == ref[0].dt
            and ours.end_dt == ref[1].dt
            and abs(ours.start_value - ref[0].value) <= 1e-9
            and abs(ours.end_value - ref[1].value) <= 1e-9
            and ours.direction.value == ref_direction
        )
        segment_rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目方向": ours.direction.label if ours else None,
                "CZSC方向": StrokeDirection(ref_direction).label if ref_direction else None,
                "本项目起点": _ours_endpoint(ours.fx_a) if ours else None,
                "CZSC起点": _ref_endpoint(ref[0]) if ref else None,
                "本项目终点": _ours_endpoint(ours.fx_b) if ours else None,
                "CZSC终点": _ref_endpoint(ref[1]) if ref else None,
                "本项目笔数": ours.stroke_count if ours else None,
                "CZSC笔数": _stroke_count(strokes, ref[0].dt, ref[1].dt) if ref else None,
            }
        )

    return SegmentReferenceComparison(
        reference_name=REFERENCE_SEGMENT_NAME,
        reference_url=REFERENCE_SEGMENT_URL,
        marker_rows=tuple(marker_rows),
        segment_rows=tuple(segment_rows),
    )


def _stroke_count(strokes: Sequence[Stroke], start_dt, end_dt) -> int:
    return sum(x.start_dt >= start_dt and x.end_dt <= end_dt for x in strokes)


def _mark_label(mark: str) -> str:
    return "顶分型" if mark == "g" else "底分型"


def _ours_endpoint(point: Fractal) -> str:
    return f"{point.dt.isoformat()} | {point.label} | {point.value:.12g}"


def _ref_endpoint(point: LegacySegmentPoint) -> str:
    return f"{point.dt.isoformat()} | {_mark_label(point.mark)} | {point.value:.12g}"
