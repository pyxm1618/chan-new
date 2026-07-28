from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from chan_monitor.models import (
    Fractal, FractalMark, MergedBar, RawBar, Segment, Stroke, StrokeDirection,
    TradingPointType,
)
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.trading_point_reference import compare_trading_points_with_reference
from chan_monitor.trading_points import detect_trading_points, validate_trading_points


def fractal(dt: datetime, mark: FractalMark, value: float, index: int) -> Fractal:
    high = value if mark is FractalMark.TOP else value + 0.5
    low = value - 0.5 if mark is FractalMark.TOP else value
    items = []
    for j, offset in enumerate((-2, -1, 0)):
        t = dt + timedelta(minutes=offset)
        raw = RawBar("DEMOUSDT", "1m", t, t + timedelta(minutes=1), low + 0.1, high, low, high - 0.1, 1, 1, 1)
        items.append(MergedBar.from_raw(raw, id_=index * 100 + j))
    return Fractal("DEMOUSDT", dt, mark, high, low, value, tuple(items), index)


def stroke(a: Fractal, b: Fractal, index: int, duration: int) -> Stroke:
    direction = StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
    bars = []
    steps = max(3, duration + 2)
    span = b.dt - a.dt
    for j in range(steps):
        r0, r1 = j / steps, (j + 1) / steps
        t = a.dt + span * r0
        o = a.value + (b.value - a.value) * r0
        c = a.value + (b.value - a.value) * r1
        wiggle = abs(b.value - a.value) * 0.01 + 0.02
        raw = RawBar("DEMOUSDT", "1m", t, t + timedelta(minutes=1), o, max(o, c)+wiggle, min(o, c)-wiggle, c, 1, 1, 1)
        bars.append(MergedBar.from_raw(raw, id_=index * 1000 + j))
    return Stroke("DEMOUSDT", a, b, (a, b), direction, tuple(bars), index)


def segment_chain(values, *, start_bottom: bool, durations, origin) -> list[Segment]:
    points = []
    for i, value in enumerate(values):
        bottom = (i % 2 == 0) if start_bottom else (i % 2 == 1)
        points.append(fractal(origin + timedelta(hours=i * 20), FractalMark.BOTTOM if bottom else FractalMark.TOP, value, i))
    result = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        s = stroke(a, b, i, durations[i])
        result.append(Segment("DEMOUSDT", a, b, s.direction, (s,), i))
    return result


def with_internal_strokes(segment: Segment, values, durations) -> Segment:
    points = []
    span = segment.end_dt - segment.start_dt
    for i, value in enumerate(values):
        dt = segment.start_dt + span * (i / (len(values)-1))
        if segment.fx_a.mark is FractalMark.TOP:
            mark = FractalMark.TOP if i % 2 == 0 else FractalMark.BOTTOM
        else:
            mark = FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP
        points.append(fractal(dt, mark, value, 1000 + segment.index * 100 + i))
    points[0], points[-1] = segment.fx_a, segment.fx_b
    strokes = tuple(stroke(a, b, 1000 + segment.index * 100 + i, durations[i]) for i, (a, b) in enumerate(zip(points, points[1:])))
    return replace(segment, strokes=strokes)


def raw_bars(segments):
    by_dt = {}
    for seg in segments:
        for st in seg.strokes:
            for bar in st.bars:
                for raw in bar.elements:
                    by_dt[raw.open_time] = raw
    return tuple(by_dt[k] for k in sorted(by_dt))


def down_case():
    segs = segment_chain(
        [140,120,135,125,132,100,112,102,110,90,108,94],
        start_bottom=False, durations=[5,5,5,5,20,5,5,5,2,6,10],
        origin=datetime(2026,1,1,tzinfo=timezone.utc),
    )
    segs[10] = with_internal_strokes(segs[10], [108,104,107,105,106.5,100,103,101,102,94], [5,5,5,5,20,5,5,5,2])
    return segs


def up_case():
    segs = segment_chain(
        [60,80,65,75,68,100,88,98,90,110,92,106],
        start_bottom=True, durations=[5,5,5,5,20,5,5,5,2,6,10],
        origin=datetime(2026,3,1,tzinfo=timezone.utc),
    )
    segs[10] = with_internal_strokes(segs[10], [92,96,93,95,93.5,101,98,100,99,106], [5,5,5,5,20,5,5,5,2])
    return segs


def simple_case(values, start_bottom, origin):
    return segment_chain(values, start_bottom=start_bottom, durations=[5]*(len(values)-1), origin=origin)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "regression"
    output.mkdir(parents=True, exist_ok=True)
    cases = [
        ("下跌趋势：一买 + 二买", down_case()),
        ("上涨趋势：一卖 + 二卖", up_case()),
        ("中枢向上破坏：三买", simple_case([100,120,105,118,108,130,118], True, datetime(2026,5,1,tzinfo=timezone.utc))),
        ("中枢向下破坏：三卖", simple_case([130,110,125,112,122,100,112], False, datetime(2026,6,1,tzinfo=timezone.utc))),
    ]
    fig = make_subplots(rows=4, cols=1, vertical_spacing=0.07, subplot_titles=[x[0] for x in cases])
    styles = {
        TradingPointType.BUY1:("#15803D","star"), TradingPointType.BUY2:("#16A34A","triangle-up"),
        TradingPointType.BUY3:("#22C55E","diamond"), TradingPointType.SELL1:("#B91C1C","star"),
        TradingPointType.SELL2:("#DC2626","triangle-down"), TradingPointType.SELL3:("#EF4444","diamond"),
    }
    points_rows, segments_rows, candidates_rows, summary_rows = [], [], [], []
    for row, (name, segments) in enumerate(cases, 1):
        bars = raw_bars(segments)
        zones = detect_segment_central_zones(segments).zones
        result = detect_trading_points(segments, zones, raw_bars=bars)
        issues = validate_trading_points(result.points, segments, zones, raw_bars=bars)
        comparison = compare_trading_points_with_reference(result.points, segments, zones, raw_bars=bars)
        assert not issues and comparison.all_match
        fig.add_trace(go.Candlestick(x=[x.open_time for x in bars], open=[x.open for x in bars], high=[x.high for x in bars], low=[x.low for x in bars], close=[x.close for x in bars], name="模拟K线", showlegend=row==1), row=row, col=1)
        fig.add_trace(go.Scatter(x=[segments[0].start_dt]+[x.end_dt for x in segments], y=[segments[0].start_value]+[x.end_value for x in segments], mode="lines+markers", line={"color":"#7E22CE","width":5}, marker={"size":7}, name="已确认线段", showlegend=row==1), row=row, col=1)
        xref = "x" if row == 1 else f"x{row}"; yref = "y" if row == 1 else f"y{row}"
        for zone in zones:
            fig.add_shape(type="rect", x0=zone.sdt, x1=zone.edt, y0=zone.zd, y1=zone.zg, xref=xref, yref=yref, line={"color":"#FB923C","width":3}, fillcolor="rgba(253,186,116,0.18)")
        for point in result.points:
            color, symbol = styles[point.point_type]
            fig.add_trace(go.Scatter(x=[point.dt], y=[point.price], mode="markers+text", text=[point.label], textposition="bottom center" if point.is_buy else "top center", marker={"color":color,"symbol":symbol,"size":15,"line":{"color":"white","width":1.5}}, name=point.label, showlegend=row==1), row=row, col=1)
            points_rows.append({"案例":name,"类型":point.point_type.value,"名称":point.label,"时间":point.dt,"价格":point.price,"线段":point.segment_index,"中枢":point.zone_index,"证据类型":point.evidence_kind,"关联线段":" | ".join(map(str,point.related_segment_indexes)),"证据":" | ".join(f"{k}={v}" for k,v in point.evidence)})
        for candidate in result.candidates:
            candidates_rows.append({"案例":name,"类型":candidate.point_type.value,"状态":candidate.status.value,"时间":candidate.dt,"线段":candidate.segment_index,"结论":candidate.reason,"检查":" | ".join(f"{k}={v}" for k,v in candidate.checks)})
        for seg in segments:
            segments_rows.append({"案例":name,"线段":seg.index,"方向":seg.direction.value,"起点":seg.start_dt,"起价":seg.start_value,"终点":seg.end_dt,"终价":seg.end_value,"价格力度":seg.power,"内部笔数":seg.stroke_count})
        summary_rows.append({"案例":name,"线段数":len(segments),"中枢数":len(zones),"买卖点":" | ".join(x.point_type.value for x in result.points),"候选数":len(result.candidates),"独立差分":comparison.all_match,"不变量问题":len(issues)})
    fig.update_layout(height=1600, title="递归级别六类买卖点确定性回归（DEMO / 模拟数据）", hovermode="x unified", margin={"t":100})
    fig.add_annotation(x=.5,y=.5,xref="paper",yref="paper",text="DEMO / 模拟数据",showarrow=False,textangle=-18,opacity=.08,font={"size":80})
    fig.write_html(output / "trading_points_six_types.html", include_plotlyjs=True)
    pd.DataFrame(points_rows).to_csv(output / "trading_points_six_types.csv", index=False)
    pd.DataFrame(segments_rows).to_csv(output / "trading_points_six_types_segments.csv", index=False)
    pd.DataFrame(candidates_rows).to_csv(output / "trading_points_six_types_candidates.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(output / "trading_points_six_types_summary.csv", index=False)
    print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
