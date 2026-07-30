from __future__ import annotations

from collections.abc import Sequence
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .engine import AnalysisResult
from .models import FractalMark, MergedBar, RawBar, TradingPointType
from .live import LiveStructureOverlay, ProvisionalLine
from .chart_styles import ChartStyle, DEFAULT_CHART_STYLE, MarkerLayerStyle


CHART_HEIGHT = 920
HEADER_TOP_MARGIN = 150
HEADER_TITLE_Y = 1.165
HEADER_META_Y = 1.105
HEADER_STATUS_Y = 1.012


PLOTLY_CONFIG = {
    "scrollZoom": True,
    "displayModeBar": True,
    "displaylogo": False,
    "responsive": True,
    "modeBarButtonsToAdd": ["drawline", "drawopenpath", "eraseshape"],
}


def build_raw_chart(
    result: AnalysisResult,
    *,
    title: str | None = None,
    show_fractals: bool = True,
    show_strokes: bool = True,
    show_segments: bool = True,
    show_central_zones: bool = True,
    show_segment_central_zones: bool = True,
    show_trading_points: bool = True,
    live_overlay: LiveStructureOverlay | None = None,
    style: ChartStyle | None = None,
) -> go.Figure:
    style = style or DEFAULT_CHART_STYLE
    bars = live_overlay.display_raw_bars if live_overlay is not None else result.raw_bars
    chart_title = title or _title(result, "原始 K 线 + 分型 + 笔 + 线段 + 双层中枢 + 买卖点")
    fig = _base_figure(bars, style)
    if show_central_zones:
        _add_central_zones(fig, result, style)
    if show_segment_central_zones:
        _add_segment_central_zones(fig, result, style)
    if show_strokes:
        _add_strokes(fig, result, style)
        if live_overlay is not None:
            _add_provisional_strokes(fig, live_overlay, style)
    if show_fractals:
        _add_fractals(fig, result, style)
    if show_segments:
        _add_segments(fig, result, style)
        if live_overlay is not None:
            _add_provisional_segments(fig, live_overlay, style)
    if show_trading_points:
        _add_trading_points(fig, result, style)
    if show_segment_central_zones:
        _add_segment_central_zone_status(fig, result, style)
    if show_trading_points:
        _add_trading_point_status(fig, result)
    if live_overlay is not None:
        _add_live_status(fig, live_overlay, style)
    _add_chart_header(fig, result, chart_title, live_overlay=live_overlay)
    return _finish(fig, bars)


def build_merged_chart(
    result: AnalysisResult,
    *,
    title: str | None = None,
    show_fractals: bool = True,
    show_strokes: bool = True,
    show_segments: bool = True,
    show_central_zones: bool = True,
    show_segment_central_zones: bool = True,
    show_trading_points: bool = True,
    live_overlay: LiveStructureOverlay | None = None,
    style: ChartStyle | None = None,
) -> go.Figure:
    style = style or DEFAULT_CHART_STYLE
    bars = live_overlay.live_result.merged_bars if live_overlay is not None else result.merged_bars
    chart_title = title or _title(result, "无包含 K 线 + 分型 + 笔 + 线段 + 双层中枢 + 买卖点")
    fig = _base_figure(bars, style)
    if show_central_zones:
        _add_central_zones(fig, result, style)
    if show_segment_central_zones:
        _add_segment_central_zones(fig, result, style)
    if show_strokes:
        _add_strokes(fig, result, style)
        if live_overlay is not None:
            _add_provisional_strokes(fig, live_overlay, style)
    if show_fractals:
        _add_fractals(fig, result, style)
    if show_segments:
        _add_segments(fig, result, style)
        if live_overlay is not None:
            _add_provisional_segments(fig, live_overlay, style)
    if show_trading_points:
        _add_trading_points(fig, result, style)
    if show_segment_central_zones:
        _add_segment_central_zone_status(fig, result, style)
    if show_trading_points:
        _add_trading_point_status(fig, result)
    if live_overlay is not None:
        _add_live_status(fig, live_overlay, style)
    _add_chart_header(fig, result, chart_title, live_overlay=live_overlay)
    return _finish(fig, bars)



def provisional_lines_frame(
    overlay: LiveStructureOverlay,
    *,
    structure: str,
) -> pd.DataFrame:
    """导出尾部候选结构，和图上的同色虚线一一对应。"""
    if structure not in {"stroke", "segment"}:
        raise ValueError("structure 必须是 stroke 或 segment")
    values = (
        overlay.provisional_strokes
        if structure == "stroke"
        else overlay.provisional_segments
    )
    return pd.DataFrame(
        [
            {
                "结构": item.label,
                "方向": item.direction.label,
                "起点时间": item.start_dt,
                "起点价格": item.start_value,
                "终点时间": item.end_dt,
                "终点价格": item.end_value,
                "确认状态": "未确认 / 可迁移",
                "原因": item.reason,
                "来源序号": " | ".join(str(x) for x in item.source_indexes),
                "计算时间": overlay.computed_at,
            }
            for item in values
        ]
    )


def raw_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open_time": x.open_time,
                "close_time": x.close_time,
                "symbol": x.symbol,
                "interval": x.interval,
                "open": x.open,
                "high": x.high,
                "low": x.low,
                "close": x.close,
                "volume": x.volume,
                "quote_volume": x.quote_volume,
                "trade_count": x.trade_count,
            }
            for x in result.raw_bars
        ]
    )

def fractals_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "时间": fx.dt,
                "类型": fx.label,
                "价格": fx.value,
                "无包含K序号": fx.merged_index,
                "原始起点": fx.source_start,
                "原始终点": fx.source_end,
                "涉及原始K数": sum(x.raw_count for x in fx.elements),
            }
            for fx in result.fractals
        ]
    )


def strokes_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "笔序号": stroke.index,
                "方向": f"{stroke.direction.arrow} {stroke.direction.label}",
                "起点时间": stroke.start_dt,
                "起点类型": stroke.fx_a.label,
                "起点价格": stroke.start_value,
                "终点时间": stroke.end_dt,
                "终点类型": stroke.fx_b.label,
                "终点价格": stroke.end_value,
                "无包含K数": stroke.length,
                "内部分型数": len(stroke.fractals),
                "价差力度": stroke.power,
                "涨跌幅": stroke.change,
                "原始K起点": stroke.source_start,
                "原始K终点": stroke.source_end,
                "内部无包含K时间": " | ".join(x.dt.isoformat() for x in stroke.bars),
                "内部分型": " | ".join(
                    f"{x.dt.isoformat()}:{x.mark.value}:{x.value:.12g}" for x in stroke.fractals
                ),
            }
            for stroke in result.strokes
        ]
    )


def segments_frame(result: AnalysisResult) -> pd.DataFrame:
    evidence_by_index = {x.segment_index: x for x in result.segment_evidence}
    rows = []
    for segment in result.segments:
        evidence = evidence_by_index.get(segment.index)
        rows.append(
            {
                "线段序号": segment.index,
                "方向": f"{segment.direction.arrow} {segment.direction.label}",
                "起点时间": segment.start_dt,
                "起点类型": segment.fx_a.label,
                "起点价格": segment.start_value,
                "终点时间": segment.end_dt,
                "终点类型": segment.fx_b.label,
                "终点价格": segment.end_value,
                "内部笔数": segment.stroke_count,
                "确认方式": evidence.confirmation if evidence else None,
                "初始主特征分型有缺口": (
                    (evidence.gap_origin_fractal or evidence.primary_fractal).gap
                    if evidence else None
                ),
                "端点是否迁移": (
                    evidence.end_position
                    != (evidence.gap_origin_fractal or evidence.primary_fractal).endpoint_position
                    if evidence else None
                ),
                "确认发生笔位置": evidence.confirmed_at_position if evidence else None,
                "价差力度": segment.power,
                "涨跌幅": segment.change,
                "原始K起点": segment.source_start,
                "原始K终点": segment.source_end,
                "内部笔序号": " | ".join(str(x.index) for x in segment.strokes),
                "内部笔端点": " | ".join(
                    f"{x.start_dt.isoformat()}->{x.end_dt.isoformat()}" for x in segment.strokes
                ),
            }
        )
    return pd.DataFrame(rows)


def segment_evidence_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "线段序号": item.segment_index,
                "起始笔位置": item.start_position,
                "终点边界位置": item.end_position,
                "确认方式": item.confirmation,
                "确认发生笔位置": item.confirmed_at_position,
                "主分型方向": item.primary_fractal.segment_direction.label,
                "主分型类型": item.primary_fractal.label,
                "主分型时间": item.primary_fractal.dt,
                "主分型价格": item.primary_fractal.value,
                "主分型有缺口": item.primary_fractal.gap,
                "初始缺口端点位置": (
                    item.gap_origin_fractal.endpoint_position
                    if item.gap_origin_fractal else None
                ),
                "初始缺口端点时间": (
                    item.gap_origin_fractal.dt if item.gap_origin_fractal else None
                ),
                "初始缺口端点价格": (
                    item.gap_origin_fractal.value if item.gap_origin_fractal else None
                ),
                "最终线段端点位置": item.end_position,
                "最终线段端点时间": (
                    item.final_endpoint.dt if item.final_endpoint else None
                ),
                "最终线段端点价格": (
                    item.final_endpoint.value if item.final_endpoint else None
                ),
                "端点发生迁移": (
                    item.gap_origin_fractal is not None
                    and item.end_position != item.gap_origin_fractal.endpoint_position
                ),
                "主分型真实突破": item.primary_fractal.actual_break,
                "主分型突破状态": item.primary_fractal.break_status.label,
                "主分型三元素": " / ".join(
                    ",".join(str(x) for x in ele.stroke_positions)
                    for ele in (
                        item.primary_fractal.left,
                        item.primary_fractal.middle,
                        item.primary_fractal.right,
                    )
                ),
                "反向分型时间": item.reverse_fractal.dt if item.reverse_fractal else None,
                "反向分型类型": item.reverse_fractal.label if item.reverse_fractal else None,
                "反向分型三元素": (
                    " / ".join(
                        ",".join(str(x) for x in ele.stroke_positions)
                        for ele in (
                            item.reverse_fractal.left,
                            item.reverse_fractal.middle,
                            item.reverse_fractal.right,
                        )
                    )
                    if item.reverse_fractal
                    else None
                ),
            }
            for item in result.segment_evidence
        ]
    )


def feature_elements_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序列起点笔位置": item.sequence_start_position,
                "待识别线段方向": item.segment_direction.label,
                "特征元素序号": item.element_index,
                "元素合并方向": item.merge_direction.label,
                "特征笔方向": item.feature_direction.label,
                "包含笔位置": " | ".join(str(x) for x in item.stroke_positions),
                "high": item.high,
                "low": item.low,
                "起点时间": item.start_dt,
                "终点时间": item.end_dt,
            }
            for item in result.feature_elements
        ]
    )


def feature_fractals_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "待识别线段方向": item.segment_direction.label,
                "分型类型": item.label,
                "候选端点笔位置": item.endpoint_position,
                "候选端点时间": item.dt,
                "候选端点价格": item.value,
                "第一元素笔位置": " | ".join(str(x) for x in item.left.stroke_positions),
                "第二元素笔位置": " | ".join(str(x) for x in item.middle.stroke_positions),
                "第三元素笔位置": " | ".join(str(x) for x in item.right.stroke_positions),
                "第一二元素有缺口": item.gap,
                "真实突破": item.actual_break,
                "真实突破状态": item.break_status.label,
                "确认观察至笔位置": item.detected_at_position,
            }
            for item in result.feature_fractals
        ]
    )


def unresolved_segment_prefix_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": i,
                "笔序号": stroke.index,
                "方向": f"{stroke.direction.arrow} {stroke.direction.label}",
                "起点时间": stroke.start_dt,
                "起点价格": stroke.start_value,
                "终点时间": stroke.end_dt,
                "终点价格": stroke.end_value,
            }
            for i, stroke in enumerate(result.unresolved_segment_prefix_strokes)
        ]
    )


def central_zones_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "中枢序号": zone.index,
                "分组序号": zone.group_index,
                "起点时间": zone.sdt,
                "终点时间": zone.edt,
                "首笔方向": zone.sdir.label,
                "末笔方向": zone.edir.label,
                "内部笔数": zone.stroke_count,
                "ZG上沿": zone.zg,
                "ZD下沿": zone.zd,
                "ZZ中轴": zone.zz,
                "GG最高": zone.gg,
                "DD最低": zone.dd,
                "有效": zone.is_valid,
                "原始K起点": zone.source_start,
                "原始K终点": zone.source_end,
                "内部笔序号": " | ".join(str(x.index) for x in zone.strokes),
            }
            for zone in result.central_zones
        ]
    )


def central_zone_groups_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "分组序号": zone.group_index,
                "是否有效中枢": zone.is_valid,
                "起点时间": zone.sdt,
                "终点时间": zone.edt,
                "内部笔数": zone.stroke_count,
                "ZG上沿": zone.zg,
                "ZD下沿": zone.zd,
                "ZZ中轴": zone.zz,
                "GG最高": zone.gg,
                "DD最低": zone.dd,
                "内部笔序号": " | ".join(str(x.index) for x in zone.strokes),
            }
            for zone in result.central_zone_groups
        ]
    )


def segment_central_zones_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "线段中枢序号": zone.index,
                "起始位置": zone.start_position,
                "结束位置": zone.end_position,
                "起点时间": zone.sdt,
                "终点时间": zone.edt,
                "首段方向": zone.sdir.label,
                "末段方向": zone.edir.label,
                "内部线段数": zone.segment_count,
                "ZG上沿": zone.zg,
                "ZD下沿": zone.zd,
                "ZZ中轴": zone.zz,
                "GG最高": zone.gg,
                "DD最低": zone.dd,
                "有效": zone.is_valid,
                "原始K起点": zone.source_start,
                "原始K终点": zone.source_end,
                "内部线段序号": " | ".join(str(x.index) for x in zone.segments),
            }
            for zone in result.segment_central_zones
        ]
    )


def segment_central_zone_candidates_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "候选序号": i,
                "起始位置": zone.start_position,
                "结束位置": zone.end_position,
                "起点时间": zone.sdt,
                "终点时间": zone.edt,
                "三段序号": " | ".join(str(x.index) for x in zone.segments),
                "ZG上沿": zone.zg,
                "ZD下沿": zone.zd,
                "ZZ中轴": zone.zz,
                "共同重叠宽度": zone.zg - zone.zd,
            }
            for i, zone in enumerate(result.segment_central_zone_candidates)
        ]
    )


def trading_points_frame(result: AnalysisResult) -> pd.DataFrame:
    columns = [
        "点位类型", "点位名称", "方向", "结构发生时间", "结构价格", "确认可通知时间",
        "操作级别", "对应线段", "关联线段", "线段中枢", "证据类型", "证据明细",
    ]
    rows = [
        {
            "点位类型": point.point_type.value,
            "点位名称": point.label,
            "方向": "买" if point.is_buy else "卖",
            "结构发生时间": point.dt,
            "结构价格": point.price,
            "确认可通知时间": point.confirmed_at_dt,
            "操作级别": point.source_level,
            "对应线段": point.segment_index,
            "关联线段": " | ".join(str(x) for x in point.related_segment_indexes),
            "线段中枢": point.zone_index,
            "证据类型": point.evidence_kind,
            "证据明细": " | ".join(f"{k}={v}" for k, v in point.evidence),
        }
        for point in result.trading_points
    ]
    return pd.DataFrame(rows, columns=columns)


def trading_point_candidates_frame(result: AnalysisResult) -> pd.DataFrame:
    columns = [
        "类型", "名称", "状态", "时间", "价格", "线段", "中枢", "关联线段", "结论", "逐项检查"
    ]
    rows = [
        {
            "类型": item.point_type.value,
            "名称": item.label,
            "状态": item.status.label,
            "时间": item.dt,
            "价格": item.price,
            "线段": item.segment_index,
            "中枢": item.zone_index,
            "关联线段": " | ".join(str(x) for x in item.related_segment_indexes),
            "结论": item.reason,
            "逐项检查": " | ".join(f"{k}={v}" for k, v in item.checks),
        }
        for item in result.trading_point_candidates
    ]
    return pd.DataFrame(rows, columns=columns)


def trend_divergences_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "级别": item.level,
                "方向": item.direction.label,
                "前中枢": item.previous_zone_index,
                "最后中枢": item.last_zone_index,
                "进入单元": item.entry_unit_index,
                "离开单元": item.exit_unit_index,
                "进入MACD面积": item.entry_macd_area,
                "离开MACD面积": item.exit_macd_area,
                "进入价格力度": item.entry_power,
                "离开价格力度": item.exit_power,
                "创新极值": item.price_extreme,
                "MACD背驰": item.macd_divergence,
                "最终有效": item.is_valid,
                "进入时间": f"{item.entry_start_dt.isoformat()} ~ {item.entry_end_dt.isoformat()}",
                "离开时间": f"{item.exit_start_dt.isoformat()} ~ {item.exit_end_dt.isoformat()}",
            }
            for item in result.trend_divergences
        ]
    )


def unfinished_segment_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": i,
                "笔序号": stroke.index,
                "方向": f"{stroke.direction.arrow} {stroke.direction.label}",
                "起点时间": stroke.start_dt,
                "起点价格": stroke.start_value,
                "终点时间": stroke.end_dt,
                "终点价格": stroke.end_value,
            }
            for i, stroke in enumerate(result.unfinished_segment_strokes)
        ]
    )


def unfinished_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": i,
                "时间": x.dt,
                "open": x.open,
                "high": x.high,
                "low": x.low,
                "close": x.close,
                "原始K数": x.raw_count,
                "原始起点": x.first_dt,
                "原始终点": x.last_dt,
            }
            for i, x in enumerate(result.unfinished_bars)
        ]
    )


def merged_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": i,
                "内部ID": x.id,
                "时间": x.dt,
                "open": x.open,
                "high": x.high,
                "low": x.low,
                "close": x.close,
                "原始K数": x.raw_count,
                "原始起点": x.first_dt,
                "原始终点": x.last_dt,
            }
            for i, x in enumerate(result.merged_bars)
        ]
    )


def provenance_text(result: AnalysisResult) -> str:
    if not result.raw_bars:
        return "无 K 线数据"
    first = result.raw_bars[0]
    last = result.raw_bars[-1]
    parts = [
        f"数据源：{result.metadata.source_name}",
        f"市场：{result.metadata.market}",
        f"币种：{first.symbol}",
        f"周期：{first.interval}",
        f"首根：{_fmt(first.open_time)}",
        f"末根：{_fmt(last.open_time)}",
        f"最小笔长：{result.min_bi_len} 根无包含K",
        f"线段算法：{result.segment_mode.label}",
        "中枢口径：笔中枢 + 线段中枢（颜色与边框可配置）",
        "买卖点：趋势MACD背驰一类点 + 次级别一类点确认二类点 + 中枢回试三类点",
    ]
    if result.metadata.note:
        parts.append(f"说明：{result.metadata.note}")
    return " ｜ ".join(parts)


def _base_figure(
    bars: Sequence[RawBar] | Sequence[MergedBar], style: ChartStyle
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.78, 0.22],
    )
    x_values = [bar.open_time if isinstance(bar, RawBar) else bar.dt for bar in bars]
    fig.add_trace(
        go.Candlestick(
            x=x_values,
            open=[bar.open for bar in bars],
            high=[bar.high for bar in bars],
            low=[bar.low for bar in bars],
            close=[bar.close for bar in bars],
            name="K线",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=x_values, y=[bar.volume for bar in bars], name="成交量", opacity=0.55),
        row=2,
        col=1,
    )
    if style.hover.enabled:
        fig.update_layout(
            hovermode="x unified",
            hoverlabel={
                "bgcolor": style.hover.bgcolor,
                "bordercolor": style.hover.background_color,
                "font": {"color": style.hover.text_color},
                "namelength": -1,
            },
            dragmode="pan",
            height=CHART_HEIGHT,
            autosize=True,
        )
    else:
        fig.update_layout(
            hovermode=False, hoverdistance=-1, dragmode="pan",
            height=CHART_HEIGHT, autosize=True,
        )
    return fig


def _add_central_zones(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    """用用户配置的矩形样式绘制有效笔中枢的 ZD~ZG 区间。"""
    if not result.central_zones:
        return

    for zone in result.central_zones:
        fig.add_shape(
            type="rect",
            x0=zone.sdt,
            x1=zone.edt,
            y0=zone.zd,
            y1=zone.zg,
            xref="x",
            yref="y",
            line={"color": style.central_zone.color, "width": style.central_zone.width},
            fillcolor=style.central_zone.fillcolor,
            layer="below",
        )

    fig.add_trace(
        go.Scatter(
            x=[zone.sdt + (zone.edt - zone.sdt) / 2 for zone in result.central_zones],
            y=[zone.zz for zone in result.central_zones],
            mode="markers+text",
            text=[f"中枢{zone.index}" for zone in result.central_zones],
            textposition="top center",
            marker={
                "size": style.central_zone.marker_size,
                "symbol": "square-open",
                "color": style.central_zone.color,
                "line": {"width": style.central_zone.width, "color": style.central_zone.color},
            },
            customdata=[
                [
                    zone.index,
                    zone.stroke_count,
                    zone.zg,
                    zone.zd,
                    zone.zz,
                    zone.gg,
                    zone.dd,
                    _fmt(zone.sdt),
                    _fmt(zone.edt),
                    " | ".join(str(x.index) for x in zone.strokes),
                ]
                for zone in result.central_zones
            ],
            hovertemplate=(
                "第 %{customdata[0]} 中枢<br>"
                "时间 %{customdata[7]} ~ %{customdata[8]}<br>"
                "内部笔数 %{customdata[1]}<br>"
                "ZG %{customdata[2]}<br>ZD %{customdata[3]}<br>ZZ %{customdata[4]}<br>"
                "GG %{customdata[5]}<br>DD %{customdata[6]}<br>"
                "内部笔 %{customdata[9]}<extra></extra>"
            ),
            name="笔中枢",
        ),
        row=1,
        col=1,
    )


def _add_segment_central_zone_status(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    """在图内明确说明线段中枢是否存在，避免把“无中枢”误认为图层失效。"""
    if result.segment_central_zones:
        text = f"线段中枢：{len(result.segment_central_zones)} 个"
        color = style.segment_central_zone.color
    elif len(result.segments) < 3:
        text = f"线段中枢：0（当前仅 {len(result.segments)} 条已确认线段，至少需要 3 条）"
        color = style.segment_central_zone.color
    else:
        text = f"线段中枢：0（{len(result.segments)} 条已确认线段中，无连续三段共同重叠）"
        color = style.segment_central_zone.color

    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=1,
        y=HEADER_STATUS_Y,
        xanchor="right",
        yanchor="bottom",
        text=text,
        showarrow=False,
        font={"size": 12, "color": color},
        bgcolor=style.segment_central_zone.fillcolor,
        bordercolor=style.segment_central_zone.color,
        borderwidth=style.segment_central_zone.width,
        borderpad=4,
    )


def _add_segment_central_zones(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    """用用户配置的矩形样式绘制三个连续线段重叠形成的中枢。"""
    if not result.segment_central_zones:
        return

    for zone in result.segment_central_zones:
        fig.add_shape(
            type="rect",
            x0=zone.sdt,
            x1=zone.edt,
            y0=zone.zd,
            y1=zone.zg,
            xref="x",
            yref="y",
            line={"color": style.segment_central_zone.color, "width": style.segment_central_zone.width},
            fillcolor=style.segment_central_zone.fillcolor,
            layer="below",
        )

    fig.add_trace(
        go.Scatter(
            x=[zone.sdt + (zone.edt - zone.sdt) / 2 for zone in result.segment_central_zones],
            y=[zone.zz for zone in result.segment_central_zones],
            mode="markers+text",
            text=[f"段中枢{zone.index}" for zone in result.segment_central_zones],
            textposition="bottom center",
            marker={
                "size": style.segment_central_zone.marker_size,
                "symbol": "diamond-open",
                "color": style.segment_central_zone.color,
                "line": {"width": style.segment_central_zone.width, "color": style.segment_central_zone.color},
            },
            customdata=[
                [
                    zone.index,
                    zone.segment_count,
                    zone.zg,
                    zone.zd,
                    zone.zz,
                    zone.gg,
                    zone.dd,
                    _fmt(zone.sdt),
                    _fmt(zone.edt),
                    " | ".join(str(x.index) for x in zone.segments),
                    zone.start_position,
                    zone.end_position,
                ]
                for zone in result.segment_central_zones
            ],
            hovertemplate=(
                "第 %{customdata[0]} 个线段中枢<br>"
                "时间 %{customdata[7]} ~ %{customdata[8]}<br>"
                "线段位置 %{customdata[10]} ~ %{customdata[11]}<br>"
                "内部线段数 %{customdata[1]}<br>"
                "ZG %{customdata[2]}<br>ZD %{customdata[3]}<br>ZZ %{customdata[4]}<br>"
                "GG %{customdata[5]}<br>DD %{customdata[6]}<br>"
                "内部线段 %{customdata[9]}<extra></extra>"
            ),
            name="线段中枢",
        ),
        row=1,
        col=1,
    )


def _add_trading_point_status(fig: go.Figure, result: AnalysisResult) -> None:
    counts = {key: sum(x.point_type.value == key for x in result.trading_points) for key in ("B1", "B2", "B3", "S1", "S2", "S3")}
    text = "买卖点：" + " / ".join(f"{key} {counts[key]}" for key in counts)
    text += f" ｜ 候选审计 {len(result.trading_point_candidates)}"
    fig.add_annotation(
        xref="paper", yref="paper", x=0.5, y=HEADER_STATUS_Y, xanchor="center", yanchor="bottom",
        text=text, showarrow=False, font={"size": 12, "color": "#334155"},
        bgcolor="rgba(248, 250, 252, 0.94)", bordercolor="#CBD5E1", borderwidth=1, borderpad=4,
    )


def _add_trading_points(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    if not result.trading_points:
        return

    symbols = {
        TradingPointType.BUY1: ("star", "bottom center"),
        TradingPointType.BUY2: ("triangle-up", "bottom center"),
        TradingPointType.BUY3: ("diamond", "bottom center"),
        TradingPointType.SELL1: ("star", "top center"),
        TradingPointType.SELL2: ("triangle-down", "top center"),
        TradingPointType.SELL3: ("diamond", "top center"),
    }
    for point_type in TradingPointType:
        items = [x for x in result.trading_points if x.point_type is point_type]
        if not items:
            continue
        point_style: MarkerLayerStyle = style.trading_point(point_type)
        symbol, textposition = symbols[point_type]
        color = point_style.color
        fig.add_trace(
            go.Scatter(
                x=[x.dt for x in items],
                y=[x.price for x in items],
                mode="markers+text",
                text=[x.label for x in items],
                textposition=textposition,
                textfont={"color": color, "size": 12},
                marker={
                    "size": point_style.size,
                    "symbol": symbol,
                    "color": color,
                    "line": {"width": point_style.border_width, "color": "#FFFFFF"},
                },
                customdata=[
                    [
                        x.point_type.value,
                        x.label,
                        x.segment_index,
                        _fmt(x.confirmed_at_dt),
                        x.evidence_kind,
                        x.zone_index,
                        " | ".join(str(v) for v in x.related_segment_indexes),
                        " | ".join(f"{k}={v}" for k, v in x.evidence),
                    ]
                    for x in items
                ],
                hovertemplate=(
                    "%{customdata[1]}（%{customdata[0]}）<br>"
                    "结构时间 %{x}<br>价格 %{y}<br>"
                    "对应线段 %{customdata[2]}<br>确认可通知时间 %{customdata[3]}<br>"
                    "证据类型 %{customdata[4]}<br>线段中枢 %{customdata[5]}<br>"
                    "关联线段 %{customdata[6]}<br>%{customdata[7]}<extra></extra>"
                ),
                name=f"{point_type.label}（{point_type.value}）",
            ),
            row=1,
            col=1,
        )


def _add_live_status(fig: go.Figure, overlay: LiveStructureOverlay, style: ChartStyle) -> None:
    snapshot = overlay.snapshot
    if snapshot is None:
        return
    current = snapshot.current_bar
    if current is not None:
        fig.add_vrect(
            x0=current.open_time,
            x1=current.close_time,
            fillcolor=style.live_bar.fillcolor,
            line_width=0,
            layer="below",
            row=1,
            col=1,
        )
        text = f"实时 K 未收盘 · {_fmt(current.open_time)} · 下次收盘前结构均可能变化"
    else:
        text = "当前未取得未收盘 K；图中结构全部基于已收盘数据"
    fig.add_annotation(
        xref="paper", yref="paper", x=0, y=HEADER_STATUS_Y, xanchor="left", yanchor="bottom",
        text=text, showarrow=False, font={"size": 11, "color": style.live_bar.color},
        bgcolor=style.live_bar.fillcolor, bordercolor=style.live_bar.color, borderwidth=1, borderpad=4,
    )


def _add_provisional_strokes(fig: go.Figure, overlay: LiveStructureOverlay, style: ChartStyle) -> None:
    _add_provisional_lines(
        fig, overlay.provisional_strokes, color=style.stroke.color, width=style.stroke.width,
        marker_size=style.stroke.marker_size, marker_symbol="diamond-open", name="未确认笔（同色虚线）",
    )


def _add_provisional_segments(fig: go.Figure, overlay: LiveStructureOverlay, style: ChartStyle) -> None:
    _add_provisional_lines(
        fig, overlay.provisional_segments, color=style.segment.color, width=style.segment.width,
        marker_size=style.segment.marker_size, marker_symbol="circle-open", name="未确认线段（同色虚线）",
    )


def _add_provisional_lines(
    fig: go.Figure, values: Sequence[ProvisionalLine], *, color: str, width: float,
    marker_size: float, marker_symbol: str, name: str,
) -> None:
    if not values:
        return
    xs: list[object] = []
    ys: list[float | None] = []
    customdata: list[list[object] | None] = []
    texts: list[str | None] = []
    for item in values:
        detail = [
            item.label, item.direction.label, item.reason,
            " | ".join(str(x) for x in item.source_indexes),
        ]
        xs.extend([item.start_dt, item.end_dt, None])
        ys.extend([item.start_value, item.end_value, None])
        customdata.extend([detail, detail, None])
        texts.extend([None, f"候选{item.direction.arrow}", None])
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, mode="lines+markers+text", text=texts,
            textposition="middle right",
            line={"width": width, "color": color, "dash": "dash"},
            marker={
                "size": marker_size, "symbol": marker_symbol,
                "color": color, "line": {"width": 1.4, "color": color},
            },
            customdata=customdata, connectgaps=False,
            hovertemplate=(
                "%{customdata[0]} · %{customdata[1]}<br>%{x}<br>候选端点 %{y}<br>"
                "%{customdata[2]}<br>来源序号 %{customdata[3]}<extra></extra>"
            ),
            name=name,
        ), row=1, col=1,
    )


def _add_segments(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    if not result.segments:
        return

    xs: list[object] = []
    ys: list[float | None] = []
    customdata: list[list[object] | None] = []
    texts: list[str | None] = []
    evidence_by_index = {x.segment_index: x for x in result.segment_evidence}
    for segment in result.segments:
        evidence = evidence_by_index.get(segment.index)
        detail = [
            segment.index,
            segment.direction.label,
            segment.stroke_count,
            segment.power,
            f"{segment.change:.2%}",
            _fmt(segment.source_start),
            _fmt(segment.source_end),
            evidence.confirmation if evidence else "未记录",
            "是" if evidence and (evidence.gap_origin_fractal or evidence.primary_fractal).gap else "否",
            "是" if evidence and evidence.gap_origin_fractal and evidence.end_position != evidence.gap_origin_fractal.endpoint_position else "否",
        ]
        xs.extend([segment.start_dt, segment.end_dt, None])
        ys.extend([segment.start_value, segment.end_value, None])
        customdata.extend([detail, detail, None])
        texts.extend([None, f"段{segment.index}{segment.direction.arrow}", None])

    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers+text",
            text=texts,
            textposition="middle right",
            line={"width": style.segment.width, "color": style.segment.color},
            marker={
                "size": style.segment.marker_size,
                "symbol": "circle",
                "color": style.segment.color,
                "line": {"width": 1, "color": "#FFFFFF"},
            },
            customdata=customdata,
            connectgaps=False,
            hovertemplate=(
                "第 %{customdata[0]} 线段 · %{customdata[1]}<br>"
                "%{x}<br>端点价格 %{y}<br>内部笔数 %{customdata[2]}<br>"
                "价差 %{customdata[3]}<br>涨跌幅 %{customdata[4]}<br>"
                "原始范围 %{customdata[5]} ~ %{customdata[6]}<br>"
                "确认方式 %{customdata[7]}<br>初始主特征分型缺口 %{customdata[8]}<br>"
                "等待期端点迁移 %{customdata[9]}<extra></extra>"
            ),
            name="线段",
        ),
        row=1,
        col=1,
    )


def _add_strokes(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    if not result.strokes:
        return

    xs: list[object] = []
    ys: list[float | None] = []
    customdata: list[list[object] | None] = []
    texts: list[str | None] = []
    for stroke in result.strokes:
        detail = [
            stroke.index,
            stroke.direction.label,
            stroke.length,
            stroke.power,
            f"{stroke.change:.2%}",
            _fmt(stroke.source_start),
            _fmt(stroke.source_end),
        ]
        xs.extend([stroke.start_dt, stroke.end_dt, None])
        ys.extend([stroke.start_value, stroke.end_value, None])
        customdata.extend([detail, detail, None])
        texts.extend([None, stroke.direction.arrow, None])

    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers+text",
            text=texts,
            textposition="middle right",
            line={"width": style.stroke.width, "color": style.stroke.color},
            marker={"size": style.stroke.marker_size, "symbol": "diamond", "color": style.stroke.color},
            customdata=customdata,
            connectgaps=False,
            hovertemplate=(
                "第 %{customdata[0]} 笔 · %{customdata[1]}<br>"
                "%{x}<br>端点价格 %{y}<br>无包含K数 %{customdata[2]}<br>"
                "价差 %{customdata[3]}<br>涨跌幅 %{customdata[4]}<br>"
                "原始范围 %{customdata[5]} ~ %{customdata[6]}<extra></extra>"
            ),
            name="笔",
        ),
        row=1,
        col=1,
    )


def _add_fractals(fig: go.Figure, result: AnalysisResult, style: ChartStyle) -> None:
    top = [x for x in result.fractals if x.mark is FractalMark.TOP]
    bottom = [x for x in result.fractals if x.mark is FractalMark.BOTTOM]
    if top:
        fig.add_trace(
            go.Scatter(
                x=[x.dt for x in top],
                y=[x.value for x in top],
                mode="markers+text",
                text=["顶" for _ in top],
                textposition="top center",
                marker={
                    "symbol": "triangle-down", "size": style.top_fractal.size,
                    "color": style.top_fractal.color, "opacity": style.top_fractal.opacity,
                    "line": {"width": style.top_fractal.border_width, "color": style.top_fractal.color},
                },
                customdata=[
                    [_fmt(x.source_start), _fmt(x.source_end), sum(b.raw_count for b in x.elements)]
                    for x in top
                ],
                hovertemplate=(
                    "顶分型<br>%{x}<br>价格 %{y}<br>原始范围 %{customdata[0]} ~ "
                    "%{customdata[1]}<br>原始K数 %{customdata[2]}<extra></extra>"
                ),
                name="顶分型",
            ),
            row=1,
            col=1,
        )
    if bottom:
        fig.add_trace(
            go.Scatter(
                x=[x.dt for x in bottom],
                y=[x.value for x in bottom],
                mode="markers+text",
                text=["底" for _ in bottom],
                textposition="bottom center",
                marker={
                    "symbol": "triangle-up", "size": style.bottom_fractal.size,
                    "color": style.bottom_fractal.color, "opacity": style.bottom_fractal.opacity,
                    "line": {"width": style.bottom_fractal.border_width, "color": style.bottom_fractal.color},
                },
                customdata=[
                    [_fmt(x.source_start), _fmt(x.source_end), sum(b.raw_count for b in x.elements)]
                    for x in bottom
                ],
                hovertemplate=(
                    "底分型<br>%{x}<br>价格 %{y}<br>原始范围 %{customdata[0]} ~ "
                    "%{customdata[1]}<br>原始K数 %{customdata[2]}<extra></extra>"
                ),
                name="底分型",
            ),
            row=1,
            col=1,
        )


def _add_chart_header(
    fig: go.Figure, result: AnalysisResult, title: str, *, live_overlay: LiveStructureOverlay | None = None
) -> None:
    """Add a responsive, explicitly wrapped chart header.

    Plotly annotations do not wrap automatically. Keeping the title and every
    provenance field on one line caused the header to overlap and be clipped
    on narrower Streamlit layouts. The title and metadata are therefore split
    into bounded lines and placed in reserved top margin space.
    """

    fig.add_annotation(
        x=0,
        y=HEADER_TITLE_Y,
        xref="paper",
        yref="paper",
        xanchor="left",
        yanchor="top",
        text=_header_title(title),
        showarrow=False,
        align="left",
        font={"size": 18},
    )
    fig.add_annotation(
        x=0,
        y=HEADER_META_Y,
        xref="paper",
        yref="paper",
        xanchor="left",
        yanchor="top",
        text=_chart_provenance_text(result, live_overlay=live_overlay),
        showarrow=False,
        align="left",
        font={"size": 10},
        bgcolor="rgba(245,247,250,0.92)",
        bordercolor="rgba(120,130,150,0.35)",
        borderwidth=1,
        borderpad=6,
    )
    if result.metadata.is_demo:
        fig.add_annotation(
            x=0.5,
            y=0.55,
            xref="paper",
            yref="paper",
            text="DEMO / 模拟数据",
            showarrow=False,
            textangle=-18,
            opacity=0.20,
            font={"size": 64},
        )


def _header_title(title: str) -> str:
    parts = [x.strip() for x in title.split(" · ") if x.strip()]
    if len(parts) >= 3:
        first_line = " · ".join(parts[:2])
        second_line = " · ".join(parts[2:])
        return f"<b>{escape(first_line)}</b><br>{escape(second_line)}"
    return f"<b>{escape(title)}</b>"


def _chart_provenance_text(
    result: AnalysisResult, *, live_overlay: LiveStructureOverlay | None = None
) -> str:
    if not result.raw_bars:
        return "无 K 线数据"
    first = result.raw_bars[0]
    last = result.raw_bars[-1]
    source = _ellipsize(result.metadata.source_name, 34)
    market = _ellipsize(result.metadata.market, 24)
    lines = [
        (
            f"数据源：{escape(source)} ｜ 市场：{escape(market)} ｜ "
            f"币种：{escape(first.symbol)} ｜ 周期：{escape(first.interval)}"
        ),
        (
            f"首根：{escape(_fmt_compact(first.open_time))} ｜ "
            f"末根：{escape(_fmt_compact(last.open_time))} ｜ "
            f"最小笔长：{result.min_bi_len} 根无包含 K ｜ "
            f"线段：{escape(result.segment_mode.label)}"
        ),
        "中枢：笔中枢 + 线段中枢 ｜ 买卖点：线段级 B1/B2/B3 与 S1/S2/S3",
    ]
    if live_overlay is not None and live_overlay.snapshot is not None:
        snapshot = live_overlay.snapshot
        lines.append(
            f"已收盘：{len(snapshot.closed_bars)} 根 ｜ "
            f"实时：{1 if snapshot.current_bar else 0} 根 ｜ "
            f"刷新：{escape(_fmt_compact(snapshot.fetched_at))} ｜ "
            f"缺口：{snapshot.gap_count} ｜ "
            f"虚线：笔 {len(live_overlay.provisional_strokes)} / 线段 {len(live_overlay.provisional_segments)}"
        )
    elif result.metadata.note:
        lines.append(f"说明：{escape(_ellipsize(result.metadata.note, 96))}")
    return "<br>".join(lines)


def _ellipsize(value: str, max_chars: int) -> str:
    value = str(value).strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "…"


def _fmt_compact(value) -> str:
    timezone = value.tzname() if getattr(value, "tzinfo", None) else ""
    suffix = f" {timezone}" if timezone else ""
    return value.strftime("%Y-%m-%d %H:%M") + suffix


def _finish(
    fig: go.Figure, bars: Sequence[RawBar] | Sequence[MergedBar] | None = None
) -> go.Figure:
    fig.update_xaxes(rangeslider={"visible": True}, row=1, col=1)
    if bars and len(bars) > 320:
        first_visible = bars[-320].open_time if isinstance(bars[-320], RawBar) else bars[-320].dt
        last_visible = bars[-1].close_time if isinstance(bars[-1], RawBar) else bars[-1].dt
        fig.update_xaxes(range=[first_visible, last_visible], row=1, col=1)
    fig.update_xaxes(rangeslider={"visible": False}, row=2, col=1)
    fig.update_yaxes(fixedrange=False)
    fig.update_layout(
        margin={"l": 60, "r": 25, "t": HEADER_TOP_MARGIN, "b": 45},
        legend={
            "orientation": "h",
            "x": 0.005,
            "xanchor": "left",
            "y": 0.995,
            "yanchor": "top",
            "bgcolor": "rgba(255,255,255,0.72)",
        },
    )
    return fig


def _title(result: AnalysisResult, suffix: str) -> str:
    if not result.raw_bars:
        return suffix
    first = result.raw_bars[0]
    return f"{first.symbol} · {first.interval} · {suffix}"


def _fmt(value) -> str:
    return value.isoformat()
