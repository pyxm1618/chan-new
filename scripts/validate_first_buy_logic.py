from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import StructureState, analyze_bars
from chan_monitor.models import (
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Segment,
    Stroke,
    StrokeDirection,
    TradingPointType,
)
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.segments import SegmentMode
from chan_monitor.trading_point_reference import compare_trading_points_with_reference
from chan_monitor.trading_points import (
    _directional_macd_area,
    build_macd_anchor,
    detect_trading_points,
    validate_trading_points,
)

_EPS = 1e-9


@dataclass
class Validation:
    checks: int = 0
    failures: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []

    def require(self, condition: bool, kind: str, **context: object) -> None:
        self.checks += 1
        if not condition:
            self.failures.append({"kind": kind, **context})


def _fractal(dt: datetime, mark: FractalMark, value: float, index: int) -> Fractal:
    high = value if mark is FractalMark.TOP else value + 0.5
    low = value - 0.5 if mark is FractalMark.TOP else value
    elements = []
    for j, offset in enumerate((-2, -1, 0)):
        t = dt + timedelta(minutes=offset)
        raw = RawBar(
            "VERIFYUSDT", "1m", t, t + timedelta(minutes=1), low + 0.1,
            high, low, high - 0.1, 1, 1, 1,
        )
        elements.append(MergedBar.from_raw(raw, id_=index * 100 + j))
    return Fractal("VERIFYUSDT", dt, mark, high, low, value, tuple(elements), index)


def _stroke(a: Fractal, b: Fractal, index: int, duration: int) -> Stroke:
    direction = StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
    bars = []
    steps = max(3, duration + 2)
    for j in range(steps):
        r0, r1 = j / steps, (j + 1) / steps
        dt = a.dt + timedelta(minutes=j)
        open_ = a.value + (b.value - a.value) * r0
        close = a.value + (b.value - a.value) * r1
        wiggle = abs(b.value - a.value) * 0.01 + 0.02
        raw = RawBar(
            "VERIFYUSDT", "1m", dt, dt + timedelta(minutes=1), open_,
            max(open_, close) + wiggle, min(open_, close) - wiggle, close,
            1, 1, 1,
        )
        bars.append(MergedBar.from_raw(raw, id_=index * 1000 + j))
    return Stroke("VERIFYUSDT", a, b, (a, b), direction, tuple(bars), index)


def _segments(values: Iterable[float], durations: Iterable[int], *, start_bottom: bool) -> list[Segment]:
    values = tuple(values)
    durations = tuple(durations)
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point_times = [origin]
    for duration in durations:
        point_times.append(point_times[-1] + timedelta(minutes=max(3, duration + 2)))
    points = []
    for i, (value, dt) in enumerate(zip(values, point_times)):
        bottom = (i % 2 == 0) if start_bottom else (i % 2 == 1)
        points.append(_fractal(
            dt,
            FractalMark.BOTTOM if bottom else FractalMark.TOP,
            float(value),
            i,
        ))
    result = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        stroke = _stroke(a, b, i, durations[i])
        result.append(Segment("VERIFYUSDT", a, b, stroke.direction, (stroke,), i))
    return result


def _with_internal_strokes(
    segment: Segment, values: Iterable[float], durations: Iterable[int]
) -> Segment:
    values = tuple(values)
    durations = tuple(durations)
    spans = [max(3, duration + 2) for duration in durations]
    available = int((segment.end_dt - segment.start_dt).total_seconds() // 60)
    if sum(spans) > available:
        raise ValueError("内部笔持续时间超过线段时间范围")
    spans[-1] += available - sum(spans)
    effective_durations = [max(1, span - 2) for span in spans]
    times = [segment.start_dt]
    for span in spans:
        times.append(times[-1] + timedelta(minutes=span))
    points = []
    for i, (value, dt) in enumerate(zip(values, times)):
        if segment.fx_a.mark is FractalMark.TOP:
            mark = FractalMark.TOP if i % 2 == 0 else FractalMark.BOTTOM
        else:
            mark = FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP
        points.append(_fractal(dt, mark, float(value), 1000 + segment.index * 100 + i))
    points[0], points[-1] = segment.fx_a, segment.fx_b
    strokes = tuple(
        _stroke(a, b, 1000 + segment.index * 100 + i, effective_durations[i])
        for i, (a, b) in enumerate(zip(points, points[1:]))
    )
    return replace(segment, strokes=strokes)


def _bars(segments: Iterable[Segment]) -> tuple[RawBar, ...]:
    by_dt: dict[datetime, RawBar] = {}
    for segment in segments:
        for stroke in segment.strokes:
            for merged in stroke.bars:
                for bar in merged.elements:
                    by_dt[bar.open_time] = bar
    return tuple(by_dt[key] for key in sorted(by_dt))


def _commit_times(segments):
    return {x.fingerprint: max(x.end_dt, x.source_end) + timedelta(microseconds=1) for x in segments}


def _detect_trading_points(segments, zones, **kwargs):
    if not kwargs.get("segment_evidence") and "segment_commit_times" not in kwargs:
        kwargs["segment_commit_times"] = _commit_times(segments)
    return detect_trading_points(segments, zones, **kwargs)


def _point_key(point) -> tuple:
    return (point.point_type.value, point.dt.isoformat(), round(point.price, 12), point.segment_index)


def _verify_formal_points(v: Validation, points, *, label: str) -> None:
    for point in points:
        if point.point_type not in {TradingPointType.BUY1, TradingPointType.SELL1}:
            continue
        evidence = point.evidence_dict
        v.require(
            point.evidence_kind == "STRICT_TREND_DIRECTIONAL_MACD_DIVERGENCE",
            "evidence_kind",
            label=label,
            point=_point_key(point),
        )
        try:
            pgg = float(evidence["前中枢GG"])
            pdd = float(evidence["前中枢DD"])
            lgg = float(evidence["后中枢GG"])
            ldd = float(evidence["后中枢DD"])
            area_a = float(evidence["进入MACD面积"])
            area_c = float(evidence["离开MACD面积"])
        except (KeyError, ValueError) as exc:
            v.require(False, "evidence_parse", label=label, error=str(exc))
            continue
        strict = lgg < pdd - _EPS if point.point_type is TradingPointType.BUY1 else ldd > pgg + _EPS
        v.require(strict, "strict_gg_dd", label=label, point=_point_key(point))
        v.require(area_a > _EPS and area_c < area_a - _EPS, "directional_macd", label=label, point=_point_key(point))
        v.require(evidence.get("MACD状态") == "精确", "macd_exact", label=label, point=_point_key(point))
        try:
            sublevel_zone_count = int(evidence["c内次级别中枢数"])
        except (KeyError, ValueError):
            sublevel_zone_count = -1
        v.require(sublevel_zone_count >= 2, "c_sublevel_zone_count", label=label, point=_point_key(point))
        v.require(point.confirmed_at_dt >= point.dt, "confirmation_time", label=label, point=_point_key(point))


def _synthetic_validation(v: Validation, random_cases: int) -> dict[str, object]:
    base = [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80]
    durations = [5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 25]
    segments = _segments(base, durations, start_bottom=False)
    segments[10] = _with_internal_strokes(
        segments[10], [108, 98, 104, 100, 103, 90, 96, 92, 95, 80], [1] * 9
    )
    bars = _bars(segments)
    zones = detect_segment_central_zones(segments).zones
    result = _detect_trading_points(segments, zones, raw_bars=bars, macd_history_anchored=True)
    buys = [x for x in result.points if x.point_type is TradingPointType.BUY1]
    v.require(len(buys) == 1 and buys[0].segment_index == 10, "deterministic_buy1")
    _verify_formal_points(v, result.points, label="deterministic_down")
    v.require(
        not validate_trading_points(
            result.points,
            segments,
            zones,
            raw_bars=bars,
            segment_commit_times=_commit_times(segments),
        ),
        "deterministic_validator",
    )

    # 校验器必须从原始结构和 K 线重新计算，不能盲信点位里保存的证据。
    formal_b1 = buys[0]
    forged_evidence = tuple(
        (key, "0" if key in {"b方向MACD面积", "进入MACD面积"} else value)
        for key, value in formal_b1.evidence
    )
    forged = replace(formal_b1, evidence=forged_evidence)
    forged_codes = {
        x.code
        for x in validate_trading_points(
            (forged,),
            segments,
            zones,
            raw_bars=bars,
            segment_commit_times=_commit_times(segments),
        )
    }
    v.require("BS1_MACD_EVIDENCE_MISMATCH" in forged_codes, "validator_macd_mutation")

    weakened = list(segments)
    weakened[10] = _with_internal_strokes(weakened[10], [108, 95, 101, 80], [5, 5, 2])
    weakened_bars = _bars(weakened)
    weakened_zones = detect_segment_central_zones(weakened).zones
    weakened_codes = {
        x.code for x in validate_trading_points(
            (formal_b1,),
            weakened,
            weakened_zones,
            raw_bars=weakened_bars,
            segment_commit_times=_commit_times(weakened),
        )
    }
    v.require("BS1_C_NOT_COMPLETE" in weakened_codes, "validator_c_structure_mutation")

    mirrored = [200 - x for x in base]
    sell_segments = _segments(mirrored, durations, start_bottom=True)
    sell_segments[10] = _with_internal_strokes(
        sell_segments[10], [92, 102, 96, 100, 97, 110, 104, 108, 105, 120], [1] * 9
    )
    sell_bars = _bars(sell_segments)
    sell_zones = detect_segment_central_zones(sell_segments).zones
    sell_result = _detect_trading_points(
        sell_segments, sell_zones, raw_bars=sell_bars, macd_history_anchored=True
    )
    sells = [x for x in sell_result.points if x.point_type is TradingPointType.SELL1]
    v.require(len(sells) == 1 and sells[0].segment_index == 10, "deterministic_sell1")
    _verify_formal_points(v, sell_result.points, label="deterministic_up")

    # 中途离开后返回中枢，最终 C 又没有创新低：不得把第一次越界提前当一买。
    invalid = _segments(
        [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 94],
        [5, 5, 5, 5, 20, 5, 5, 5, 2, 6, 10],
        start_bottom=False,
    )
    invalid_result = _detect_trading_points(
        invalid,
        detect_segment_central_zones(invalid).zones,
        raw_bars=_bars(invalid),
        macd_history_anchored=True,
    )
    v.require(
        not any(x.point_type is TradingPointType.BUY1 for x in invalid_result.points),
        "intermediate_departure_false_positive",
    )

    # 定向面积独立反例：下跌只累计负柱，上涨只累计正柱。
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    unit = type("Unit", (), {"source_start": start, "source_end": start + timedelta(minutes=3)})()
    hist = {
        start: -2.0,
        start + timedelta(minutes=1): 5.0,
        start + timedelta(minutes=2): -3.0,
        start + timedelta(minutes=3): 7.0,
    }
    v.require(_directional_macd_area(unit, StrokeDirection.DOWN, hist) == 5.0, "negative_hist_area")
    v.require(_directional_macd_area(unit, StrokeDirection.UP, hist) == 12.0, "positive_hist_area")

    # 精确 MACD 锚点必须使完整历史与滚动窗口逐值一致；无锚窗口只能 pending。
    first = bars[0].open_time
    warmup = []
    price = 150.0
    for i in range(160):
        dt = first - timedelta(minutes=160 - i)
        close = price + (i % 9 - 4) * 0.08
        warmup.append(RawBar(
            "VERIFYUSDT", "1m", dt, dt + timedelta(minutes=1), price,
            max(price, close) + 0.05, min(price, close) - 0.05, close, 1, 1, 1,
        ))
        price = close
    full = _detect_trading_points(
        segments, zones, raw_bars=tuple(warmup) + bars, macd_history_anchored=True
    )
    restored = _detect_trading_points(
        segments, zones, raw_bars=bars, macd_anchor=build_macd_anchor(warmup)
    )
    v.require(
        tuple(_point_key(x) for x in full.points) == tuple(_point_key(x) for x in restored.points),
        "macd_anchor_points",
    )
    v.require(
        tuple((x.entry_macd_area, x.exit_macd_area) for x in full.trend_divergences)
        == tuple((x.entry_macd_area, x.exit_macd_area) for x in restored.trend_divergences),
        "macd_anchor_areas",
    )
    unanchored = _detect_trading_points(segments, zones, raw_bars=bars)
    v.require(
        not any(x.point_type is TradingPointType.BUY1 for x in unanchored.points),
        "unanchored_formal_buy1",
    )
    v.require(
        any(x.point_type is TradingPointType.BUY1 and x.status.value == "pending" for x in unanchored.candidates),
        "unanchored_pending_buy1",
    )

    rng = random.Random(20260731)
    reference_mismatches = 0
    formal_buy1_count = 0
    for case in range(random_cases):
        scale = rng.uniform(0.35, 3.5)
        shift = rng.uniform(-250, 250)
        values = [shift + scale * x for x in base]
        # 在不破坏交替方向的前提下随机改变最终 C 深度，覆盖创新低/不创新低。
        values[-1] = shift + scale * rng.uniform(70, 98)
        ds = [rng.randint(2, 16) for _ in durations]
        ds[4] = rng.randint(14, 35)
        ds[10] = rng.randint(25, 40)
        ss = _segments(values, ds, start_bottom=False)
        c_start, c_end = values[10], values[11]
        # 保持 C 内“离开—不回中枢的回抽—继续下跌”结构；当最终 C 不创新低时，
        # 生产与独立参考都必须拒绝正式一买。
        final_departure = shift + scale * 95
        if c_end < final_departure:
            internal_values = [
                c_start,
                shift + scale * 98,
                shift + scale * 104,
                shift + scale * 100,
                shift + scale * 103,
                shift + scale * 90,
                shift + scale * 96,
                shift + scale * 92,
                final_departure,
                c_end,
            ]
            ss[10] = _with_internal_strokes(ss[10], internal_values, [1] * 9)
        bb = _bars(ss)
        zz = detect_segment_central_zones(ss).zones
        rr = _detect_trading_points(ss, zz, raw_bars=bb, macd_history_anchored=True)
        cmp = compare_trading_points_with_reference(
            rr.points, ss, zz, raw_bars=bb, macd_history_anchored=True
        )
        if not cmp.all_match:
            reference_mismatches += 1
            v.require(False, "random_reference_mismatch", case=case, rows=cmp.rows[:3])
        _verify_formal_points(v, rr.points, label=f"random_{case}")
        formal_buy1_count += sum(x.point_type is TradingPointType.BUY1 for x in rr.points)

    return {
        "random_cases": random_cases,
        "random_reference_mismatches": reference_mismatches,
        "random_formal_buy1_count": formal_buy1_count,
    }


def _dataset_validation(v: Validation, *, demo_count: int, real_count: int) -> dict[str, object]:
    demo = demo_bars(demo_count, symbol="BTCUSDT", interval="5m")
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    previous_points: dict[tuple, object] = {}
    point_scans = 0
    for position, bar in enumerate(demo, start=1):
        before = len(state.segments)
        state.update(bar)
        if len(state.segments) == before:
            continue
        zones = detect_segment_central_zones(state.segments).zones
        result = _detect_trading_points(
            state.segments,
            zones,
            raw_bars=demo[:position],
            segment_evidence=state.evidence,
            strokes=state.resolved_stable_strokes,
            macd_history_anchored=True,
        )
        current = {_point_key(x): x for x in result.points}
        v.require(set(previous_points).issubset(current), "demo_point_retraction", position=position)
        _verify_formal_points(v, result.points, label=f"demo_prefix_{position}")
        v.require(
            not validate_trading_points(
                result.points,
                state.segments,
                zones,
                raw_bars=demo[:position],
                segment_evidence=state.evidence,
                strokes=state.resolved_stable_strokes,
                macd_history_anchored=True,
            ),
            "demo_prefix_validator",
            position=position,
        )
        previous_points = current
        point_scans += 1

    full_demo = analyze_bars(demo, left_boundary_anchored=True)
    demo_cmp = compare_trading_points_with_reference(
        full_demo.trading_points,
        full_demo.segments,
        full_demo.segment_central_zones,
        raw_bars=full_demo.raw_bars,
        macd_history_anchored=True,
    )
    v.require(demo_cmp.all_match, "demo_reference", rows=demo_cmp.rows[:5])
    _verify_formal_points(v, full_demo.trading_points, label="demo_full")

    real_path = Path("artifacts/real/BTCUSDT_spot_1h_20191014-0600_20191104-0100_bars.csv")
    real_bars = bars_from_csv(real_path, symbol="BTCUSDT", interval="1h")[:real_count]
    real = analyze_bars(real_bars, left_boundary_anchored=True)
    real_cmp = compare_trading_points_with_reference(
        real.trading_points,
        real.segments,
        real.segment_central_zones,
        raw_bars=real.raw_bars,
        macd_history_anchored=True,
    )
    v.require(real_cmp.all_match, "real_reference", rows=real_cmp.rows[:5])
    v.require(
        not validate_trading_points(
            real.trading_points,
            real.segments,
            real.segment_central_zones,
            raw_bars=real.raw_bars,
            segment_evidence=real.segment_evidence,
            strokes=real.resolved_strokes,
            macd_history_anchored=real.left_boundary_anchored,
            macd_anchor=real.macd_anchor,
        ),
        "real_validator",
    )
    _verify_formal_points(v, real.trading_points, label="real")

    return {
        "demo_bars": demo_count,
        "demo_formal_segments": len(full_demo.segments),
        "demo_point_scans": point_scans,
        "demo_trading_points": len(full_demo.trading_points),
        "demo_first_points": sum(
            x.point_type in {TradingPointType.BUY1, TradingPointType.SELL1}
            for x in full_demo.trading_points
        ),
        "real_bars": len(real_bars),
        "real_formal_segments": len(real.segments),
        "real_trading_points": len(real.trading_points),
        "real_first_points": sum(
            x.point_type in {TradingPointType.BUY1, TradingPointType.SELL1}
            for x in real.trading_points
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证严格一买/一卖、定向 MACD、窗口锚点和逐根稳定性。")
    parser.add_argument("--demo-bars", type=int, default=5000)
    parser.add_argument("--real-bars", type=int, default=500)
    parser.add_argument("--random-cases", type=int, default=1000)
    args = parser.parse_args()
    if min(args.demo_bars, args.real_bars, args.random_cases) <= 0:
        parser.error("所有数量参数必须大于 0")

    validation = Validation()
    synthetic = _synthetic_validation(validation, args.random_cases)
    datasets = _dataset_validation(
        validation,
        demo_count=args.demo_bars,
        real_count=args.real_bars,
    )
    result = {
        **synthetic,
        **datasets,
        "checks": validation.checks,
        "failure_count": len(validation.failures),
        "failures": validation.failures[:100],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if validation.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
