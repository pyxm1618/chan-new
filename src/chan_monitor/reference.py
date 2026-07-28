from __future__ import annotations

"""CZSC 源码差分校验。

本模块把同一批原始 K 线分别送入：

- 本项目业务实现；
- 项目内冻结的 CZSC v0.9.69 ``analyze.py`` 独立源码快照。

比较范围覆盖去包含 K 线、分型、笔，以及成笔状态机留下的未完成笔 K 线。
"""

from dataclasses import dataclass
from math import isclose
from typing import Sequence

import pandas as pd

from .engine import AnalysisResult
from .models import FractalMark, RawBar, StrokeDirection
from .vendor import czsc_v0_9_69_core as upstream

REFERENCE_NAME = "CZSC v0.9.69 旧成笔状态机源码快照（对照基线）"
REFERENCE_URL = "https://github.com/waditu/czsc/blob/v0.9.69/czsc/analyze.py"


@dataclass(frozen=True, slots=True)
class ReferenceNewBar:
    id: int
    symbol: str
    dt: object
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    elements: tuple[upstream.RawBar, ...]


@dataclass(frozen=True, slots=True)
class ReferenceFractal:
    symbol: str
    dt: object
    mark: str
    high: float
    low: float
    value: float
    elements: tuple[ReferenceNewBar, ReferenceNewBar, ReferenceNewBar]
    merged_index: int


@dataclass(frozen=True, slots=True)
class ReferenceStroke:
    symbol: str
    fx_a: ReferenceFractal
    fx_b: ReferenceFractal
    fractals: tuple[ReferenceFractal, ...]
    direction: str
    bars: tuple[ReferenceNewBar, ...]

    @property
    def high(self) -> float:
        return max(self.fx_a.high, self.fx_b.high)

    @property
    def low(self) -> float:
        return min(self.fx_a.low, self.fx_b.low)


@dataclass(frozen=True, slots=True)
class ReferenceRun:
    merged_bars: tuple[ReferenceNewBar, ...]
    fractals: tuple[ReferenceFractal, ...]
    strokes: tuple[ReferenceStroke, ...]
    unfinished_bars: tuple[ReferenceNewBar, ...]


@dataclass(frozen=True, slots=True)
class ReferenceComparison:
    reference_name: str
    reference_url: str
    merged_rows: tuple[dict[str, object], ...]
    fractal_rows: tuple[dict[str, object], ...]
    stroke_rows: tuple[dict[str, object], ...]
    unfinished_rows: tuple[dict[str, object], ...]

    @property
    def merged_match(self) -> bool:
        return all(bool(row["一致"]) for row in self.merged_rows)

    @property
    def fractal_match(self) -> bool:
        return all(bool(row["一致"]) for row in self.fractal_rows)

    @property
    def stroke_match(self) -> bool:
        return all(bool(row["一致"]) for row in self.stroke_rows)

    @property
    def unfinished_match(self) -> bool:
        return all(bool(row["一致"]) for row in self.unfinished_rows)

    @property
    def all_match(self) -> bool:
        return self.merged_match and self.fractal_match and self.stroke_match and self.unfinished_match

    @property
    def merged_match_count(self) -> int:
        return sum(bool(row["一致"]) for row in self.merged_rows)

    @property
    def fractal_match_count(self) -> int:
        return sum(bool(row["一致"]) for row in self.fractal_rows)

    @property
    def stroke_match_count(self) -> int:
        return sum(bool(row["一致"]) for row in self.stroke_rows)

    @property
    def unfinished_match_count(self) -> int:
        return sum(bool(row["一致"]) for row in self.unfinished_rows)

    def merged_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.merged_rows)

    def fractal_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.fractal_rows)

    def stroke_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.stroke_rows)

    def unfinished_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.unfinished_rows)

    def summary(self) -> dict[str, object]:
        return {
            "reference": self.reference_name,
            "reference_url": self.reference_url,
            "merged_total": len(self.merged_rows),
            "merged_match": self.merged_match_count,
            "merged_all_match": self.merged_match,
            "fractal_total": len(self.fractal_rows),
            "fractal_match": self.fractal_match_count,
            "fractal_all_match": self.fractal_match,
            "stroke_total": len(self.stroke_rows),
            "stroke_match": self.stroke_match_count,
            "stroke_all_match": self.stroke_match,
            "unfinished_total": len(self.unfinished_rows),
            "unfinished_match": self.unfinished_match_count,
            "unfinished_all_match": self.unfinished_match,
            "all_match": self.all_match,
        }


def run_frozen_czsc_reference(raw_bars: Sequence[RawBar], *, min_bi_len: int = 6) -> ReferenceRun:
    source_bars = [
        upstream.RawBar(
            id=i,
            symbol=bar.symbol,
            freq=bar.interval,
            dt=bar.open_time,
            open=bar.open,
            close=bar.close,
            high=bar.high,
            low=bar.low,
            vol=bar.volume,
            amount=bar.quote_volume,
        )
        for i, bar in enumerate(raw_bars)
    ]

    # 第一条独立路径：完整序列上的去包含与分型。
    merged_source: list[upstream.NewBar] = []
    for bar in source_bars:
        if len(merged_source) < 2:
            merged_source.append(_new_from_raw(bar))
            continue
        included, new_bar = upstream.remove_include(merged_source[-2], merged_source[-1], bar)
        if included:
            merged_source[-1] = new_bar
        else:
            merged_source.append(new_bar)

    fractals_source = upstream.check_fxs(merged_source)
    merged = tuple(_convert_new_bar(x) for x in merged_source)
    index_by_identity = {id(source): i for i, source in enumerate(merged_source)}
    converted_by_identity = {id(source): converted for source, converted in zip(merged_source, merged)}
    fractals = tuple(
        _convert_fx(
            fx,
            merged_index=index_by_identity[id(fx.elements[1])],
            converted_by_identity=converted_by_identity,
        )
        for fx in fractals_source
    )

    # 第二条独立路径：逐根运行 CZSC 的成笔状态机。
    analyzer = upstream.FrozenCZSC(source_bars, min_bi_len=min_bi_len)
    strokes = tuple(_convert_bi(x) for x in analyzer.bi_list)
    unfinished = tuple(_convert_new_bar(x) for x in analyzer.bars_ubi)
    return ReferenceRun(merged, fractals, strokes, unfinished)


def compare_with_czsc_reference(result: AnalysisResult) -> ReferenceComparison:
    reference = run_frozen_czsc_reference(result.raw_bars, min_bi_len=result.min_bi_len)
    return ReferenceComparison(
        reference_name=REFERENCE_NAME,
        reference_url=REFERENCE_URL,
        merged_rows=tuple(_compare_merged(result, reference)),
        fractal_rows=tuple(_compare_fractals(result, reference)),
        stroke_rows=tuple(_compare_strokes(result, reference)),
        unfinished_rows=tuple(_compare_unfinished(result, reference)),
    )


def _new_from_raw(bar: upstream.RawBar) -> upstream.NewBar:
    return upstream.NewBar(
        id=bar.id,
        symbol=bar.symbol,
        freq=bar.freq,
        dt=bar.dt,
        open=bar.open,
        close=bar.close,
        high=bar.high,
        low=bar.low,
        vol=bar.vol,
        amount=bar.amount,
        elements=[bar],
    )


def _convert_new_bar(bar: upstream.NewBar) -> ReferenceNewBar:
    return ReferenceNewBar(
        id=bar.id,
        symbol=bar.symbol,
        dt=bar.dt,
        open=bar.open,
        close=bar.close,
        high=bar.high,
        low=bar.low,
        vol=bar.vol,
        amount=bar.amount,
        elements=tuple(bar.elements),
    )


def _convert_fx(
    fx: upstream.FX,
    *,
    merged_index: int = -1,
    converted_by_identity: dict[int, ReferenceNewBar] | None = None,
) -> ReferenceFractal:
    if converted_by_identity is None:
        elements = tuple(_convert_new_bar(x) for x in fx.elements)
    else:
        elements = tuple(converted_by_identity[id(x)] for x in fx.elements)
    return ReferenceFractal(
        symbol=fx.symbol,
        dt=fx.dt,
        mark=fx.mark.value,
        high=fx.high,
        low=fx.low,
        value=fx.fx,
        elements=elements,  # type: ignore[arg-type]
        merged_index=merged_index,
    )


def _convert_bi(bi: upstream.BI) -> ReferenceStroke:
    return ReferenceStroke(
        symbol=bi.symbol,
        fx_a=_convert_fx(bi.fx_a),
        fx_b=_convert_fx(bi.fx_b),
        fractals=tuple(_convert_fx(x) for x in bi.fxs),
        direction="up" if bi.direction is upstream.Direction.Up else "down",
        bars=tuple(_convert_new_bar(x) for x in bi.bars),
    )


def _compare_merged(result: AnalysisResult, reference: ReferenceRun) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    total = max(len(result.merged_bars), len(reference.merged_bars))
    for i in range(total):
        ours = result.merged_bars[i] if i < len(result.merged_bars) else None
        ref = reference.merged_bars[i] if i < len(reference.merged_bars) else None
        match = _same_bar(ours, ref)
        rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目时间": ours.dt if ours else None,
                "CZSC时间": ref.dt if ref else None,
                "本项目OHLC": _ohlc(ours) if ours else None,
                "CZSC OHLC": _ohlc(ref) if ref else None,
                "本项目原始K数": ours.raw_count if ours else None,
                "CZSC原始K数": len(ref.elements) if ref else None,
                "本项目原始范围": _range_ours(ours) if ours else None,
                "CZSC原始范围": _range_ref(ref) if ref else None,
            }
        )
    return rows


def _compare_fractals(result: AnalysisResult, reference: ReferenceRun) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    total = max(len(result.fractals), len(reference.fractals))
    for i in range(total):
        ours = result.fractals[i] if i < len(result.fractals) else None
        ref = reference.fractals[i] if i < len(reference.fractals) else None
        ours_mark = ours.mark.value if ours else None
        match = bool(
            ours is not None
            and ref is not None
            and ours.dt == ref.dt
            and ours_mark == ref.mark
            and _same_float(ours.high, ref.high)
            and _same_float(ours.low, ref.low)
            and _same_float(ours.value, ref.value)
            and ours.merged_index == ref.merged_index
            and tuple(x.dt for x in ours.elements) == tuple(x.dt for x in ref.elements)
        )
        rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目时间": ours.dt if ours else None,
                "CZSC时间": ref.dt if ref else None,
                "本项目类型": FractalMark(ours_mark).label if ours_mark else None,
                "CZSC类型": FractalMark(ref.mark).label if ref else None,
                "本项目价格": ours.value if ours else None,
                "CZSC价格": ref.value if ref else None,
                "本项目无包含K序号": ours.merged_index if ours else None,
                "CZSC无包含K序号": ref.merged_index if ref else None,
                "本项目三K时间": _three_ours(ours) if ours else None,
                "CZSC三K时间": _three_ref(ref) if ref else None,
            }
        )
    return rows


def _compare_strokes(result: AnalysisResult, reference: ReferenceRun) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    total = max(len(result.strokes), len(reference.strokes))
    for i in range(total):
        ours = result.strokes[i] if i < len(result.strokes) else None
        ref = reference.strokes[i] if i < len(reference.strokes) else None
        match = bool(
            ours is not None
            and ref is not None
            and ours.direction.value == ref.direction
            and _same_fx(ours.fx_a, ref.fx_a)
            and _same_fx(ours.fx_b, ref.fx_b)
            and len(ours.bars) == len(ref.bars)
            and all(_same_bar(a, b) for a, b in zip(ours.bars, ref.bars))
            and _fx_signature_ours(ours.fractals) == _fx_signature_ref(ref.fractals)
        )
        rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目方向": ours.direction.label if ours else None,
                "CZSC方向": StrokeDirection(ref.direction).label if ref else None,
                "本项目起点": _stroke_endpoint_ours(ours.fx_a) if ours else None,
                "CZSC起点": _stroke_endpoint_ref(ref.fx_a) if ref else None,
                "本项目终点": _stroke_endpoint_ours(ours.fx_b) if ours else None,
                "CZSC终点": _stroke_endpoint_ref(ref.fx_b) if ref else None,
                "本项目无包含K数": ours.length if ours else None,
                "CZSC无包含K数": len(ref.bars) if ref else None,
                "本项目内部分型": _fx_signature_ours(ours.fractals) if ours else None,
                "CZSC内部分型": _fx_signature_ref(ref.fractals) if ref else None,
                "本项目K线时间": _bar_times_ours(ours.bars) if ours else None,
                "CZSC K线时间": _bar_times_ref(ref.bars) if ref else None,
            }
        )
    return rows


def _compare_unfinished(result: AnalysisResult, reference: ReferenceRun) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    total = max(len(result.unfinished_bars), len(reference.unfinished_bars))
    for i in range(total):
        ours = result.unfinished_bars[i] if i < len(result.unfinished_bars) else None
        ref = reference.unfinished_bars[i] if i < len(reference.unfinished_bars) else None
        rows.append(
            {
                "序号": i,
                "一致": _same_bar(ours, ref),
                "本项目时间": ours.dt if ours else None,
                "CZSC时间": ref.dt if ref else None,
                "本项目OHLC": _ohlc(ours) if ours else None,
                "CZSC OHLC": _ohlc(ref) if ref else None,
                "本项目原始范围": _range_ours(ours) if ours else None,
                "CZSC原始范围": _range_ref(ref) if ref else None,
            }
        )
    return rows


def _same_fx(ours, ref: ReferenceFractal) -> bool:
    return bool(
        ours.dt == ref.dt
        and ours.mark.value == ref.mark
        and _same_float(ours.high, ref.high)
        and _same_float(ours.low, ref.low)
        and _same_float(ours.value, ref.value)
        and tuple(x.dt for x in ours.elements) == tuple(x.dt for x in ref.elements)
    )


def _same_bar(ours, ref) -> bool:
    return bool(
        ours is not None
        and ref is not None
        and ours.dt == ref.dt
        and _same_float(ours.open, ref.open)
        and _same_float(ours.high, ref.high)
        and _same_float(ours.low, ref.low)
        and _same_float(ours.close, ref.close)
        and _same_float(ours.volume, ref.vol)
        and _same_float(ours.quote_volume, ref.amount)
        and tuple(x.open_time for x in ours.elements) == tuple(x.dt for x in ref.elements)
    )


def _same_float(a: float, b: float) -> bool:
    return isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-9)


def _ohlc(bar) -> str:
    return f"{bar.open:.12g}/{bar.high:.12g}/{bar.low:.12g}/{bar.close:.12g}"


def _range_ours(bar) -> str:
    return f"{bar.elements[0].open_time.isoformat()} ~ {bar.elements[-1].open_time.isoformat()}"


def _range_ref(bar) -> str:
    return f"{bar.elements[0].dt.isoformat()} ~ {bar.elements[-1].dt.isoformat()}"


def _three_ours(fx) -> str:
    return " | ".join(x.dt.isoformat() for x in fx.elements)


def _three_ref(fx) -> str:
    return " | ".join(x.dt.isoformat() for x in fx.elements)


def _stroke_endpoint_ours(fx) -> str:
    return f"{fx.dt.isoformat()} {fx.mark.value} {fx.value:.12g}"


def _stroke_endpoint_ref(fx) -> str:
    return f"{fx.dt.isoformat()} {fx.mark} {fx.value:.12g}"


def _fx_signature_ours(fxs) -> str:
    return " | ".join(f"{x.dt.isoformat()}:{x.mark.value}:{x.value:.12g}" for x in fxs)


def _fx_signature_ref(fxs) -> str:
    return " | ".join(f"{x.dt.isoformat()}:{x.mark}:{x.value:.12g}" for x in fxs)


def _bar_times_ours(bars) -> str:
    return " | ".join(x.dt.isoformat() for x in bars)


def _bar_times_ref(bars) -> str:
    return " | ".join(x.dt.isoformat() for x in bars)
