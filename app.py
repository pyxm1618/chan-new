from __future__ import annotations

import time
from datetime import datetime, timezone

import streamlit as st

from chan_monitor.binance import BinanceKlineClient, BinanceMarket
from chan_monitor.chart import (
    PLOTLY_CONFIG,
    build_merged_chart,
    build_raw_chart,
    central_zone_groups_frame,
    central_zones_frame,
    segment_central_zone_candidates_frame,
    segment_central_zones_frame,
    trading_points_frame,
    trading_point_candidates_frame,
    trend_divergences_frame,
    fractals_frame,
    merged_frame,
    provenance_text,
    provisional_lines_frame,
    raw_frame,
    segments_frame,
    segment_evidence_frame,
    feature_elements_frame,
    feature_fractals_frame,
    unresolved_segment_prefix_frame,
    strokes_frame,
    unfinished_frame,
    unfinished_segment_frame,
)
from chan_monitor.chart_styles import (
    ChartStyle,
    DEFAULT_CHART_STYLE,
    LineLayerStyle,
    LiveBarStyle,
    HoverLabelStyle,
    MarkerLayerStyle,
    ZoneLayerStyle,
)
from chan_monitor.central_zone_reference import compare_central_zones_with_czsc
from chan_monitor.central_zones import validate_central_zones
from chan_monitor.segment_central_zone_reference import compare_segment_central_zones_with_reference
from chan_monitor.segment_central_zones import validate_segment_central_zones
from chan_monitor.trading_point_reference import compare_trading_points_with_reference
from chan_monitor.trading_points import validate_trading_points
from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.live import analyze_snapshot, analyze_static, recommended_refresh_seconds
from chan_monitor.metadata import AnalysisMetadata
from chan_monitor.reference import compare_with_czsc_reference
from chan_monitor.feature_sequence_reference import compare_feature_sequence_reference
from chan_monitor.segments import SegmentMode, validate_segment_chain
from chan_monitor.strokes import validate_stroke_chain


APP_VERSION = "0.10.8"


STYLE_WIDGET_KEYS = (
    "style_stroke_color", "style_stroke_width", "style_stroke_marker_size",
    "style_segment_color", "style_segment_width", "style_segment_marker_size",
    "style_central_zone_color", "style_central_zone_width", "style_central_zone_marker_size",
    "style_central_zone_opacity", "style_segment_zone_color", "style_segment_zone_width",
    "style_segment_zone_marker_size", "style_segment_zone_opacity",
    "style_top_fractal_color", "style_top_fractal_size", "style_top_fractal_border",
    "style_bottom_fractal_color", "style_bottom_fractal_size", "style_bottom_fractal_border",
    "style_buy1_color", "style_buy1_size", "style_buy2_color", "style_buy2_size",
    "style_buy3_color", "style_buy3_size", "style_sell1_color", "style_sell1_size",
    "style_sell2_color", "style_sell2_size", "style_sell3_color", "style_sell3_size",
    "style_trading_point_border", "style_live_bar_color", "style_live_bar_opacity",
    "style_hover_enabled", "style_hover_background_color", "style_hover_background_opacity",
)


def _reset_chart_style() -> None:
    for key in STYLE_WIDGET_KEYS:
        st.session_state.pop(key, None)


def _chart_style_controls() -> ChartStyle:
    defaults = DEFAULT_CHART_STYLE
    with st.expander("图层样式：颜色 / 粗细", expanded=False):
        st.caption("样式在自动刷新和 Streamlit 重跑期间保持；未确认笔、线段自动继承对应实线样式。")
        st.button("恢复默认样式", key="reset_chart_style", on_click=_reset_chart_style, use_container_width=True)

        st.markdown("**笔与线段**")
        c1, c2, c3 = st.columns([1.2, 1, 1])
        stroke_color = c1.color_picker("笔颜色", defaults.stroke.color, key="style_stroke_color")
        stroke_width = c2.slider(
            "笔线宽", 0.4, 5.0, float(defaults.stroke.width), 0.1, key="style_stroke_width"
        )
        stroke_marker_size = c3.slider(
            "笔端点", 2.0, 14.0, float(defaults.stroke.marker_size), 0.5, key="style_stroke_marker_size"
        )
        c1, c2, c3 = st.columns([1.2, 1, 1])
        segment_color = c1.color_picker("线段颜色", defaults.segment.color, key="style_segment_color")
        segment_width = c2.slider(
            "线段线宽", 0.6, 8.0, float(defaults.segment.width), 0.1, key="style_segment_width"
        )
        segment_marker_size = c3.slider(
            "线段端点", 3.0, 18.0, float(defaults.segment.marker_size), 0.5, key="style_segment_marker_size"
        )

        st.markdown("**中枢框**")
        c1, c2 = st.columns(2)
        central_zone_color = c1.color_picker(
            "笔中枢颜色", defaults.central_zone.color, key="style_central_zone_color"
        )
        central_zone_width = c2.slider(
            "笔中枢边框", 0.4, 6.0, float(defaults.central_zone.width), 0.1,
            key="style_central_zone_width",
        )
        c1, c2 = st.columns(2)
        central_zone_marker_size = c1.slider(
            "笔中枢中轴", 3.0, 18.0, float(defaults.central_zone.marker_size), 0.5,
            key="style_central_zone_marker_size",
        )
        central_zone_opacity = c2.slider(
            "笔中枢填充", 0.0, 0.60, float(defaults.central_zone.fill_opacity), 0.01,
            key="style_central_zone_opacity",
        )
        c1, c2 = st.columns(2)
        segment_zone_color = c1.color_picker(
            "线段中枢颜色", defaults.segment_central_zone.color, key="style_segment_zone_color"
        )
        segment_zone_width = c2.slider(
            "线段中枢边框", 0.4, 6.0, float(defaults.segment_central_zone.width), 0.1,
            key="style_segment_zone_width",
        )
        c1, c2 = st.columns(2)
        segment_zone_marker_size = c1.slider(
            "线段中枢中轴", 3.0, 18.0, float(defaults.segment_central_zone.marker_size), 0.5,
            key="style_segment_zone_marker_size",
        )
        segment_zone_opacity = c2.slider(
            "线段中枢填充", 0.0, 0.60, float(defaults.segment_central_zone.fill_opacity), 0.01,
            key="style_segment_zone_opacity",
        )

        st.markdown("**分型标记**")
        c1, c2, c3 = st.columns([1.2, 1, 1])
        top_fractal_color = c1.color_picker(
            "顶分型颜色", defaults.top_fractal.color, key="style_top_fractal_color"
        )
        top_fractal_size = c2.slider(
            "顶分型大小", 3.0, 22.0, float(defaults.top_fractal.size), 0.5,
            key="style_top_fractal_size",
        )
        top_fractal_border = c3.slider(
            "顶分型边框", 0.0, 5.0, float(defaults.top_fractal.border_width), 0.1,
            key="style_top_fractal_border",
        )
        c1, c2, c3 = st.columns([1.2, 1, 1])
        bottom_fractal_color = c1.color_picker(
            "底分型颜色", defaults.bottom_fractal.color, key="style_bottom_fractal_color"
        )
        bottom_fractal_size = c2.slider(
            "底分型大小", 3.0, 22.0, float(defaults.bottom_fractal.size), 0.5,
            key="style_bottom_fractal_size",
        )
        bottom_fractal_border = c3.slider(
            "底分型边框", 0.0, 5.0, float(defaults.bottom_fractal.border_width), 0.1,
            key="style_bottom_fractal_border",
        )

        st.markdown("**买卖点**")
        point_border = st.slider(
            "买卖点边框粗细", 0.0, 5.0, float(defaults.buy1.border_width), 0.1,
            key="style_trading_point_border",
        )
        buy1_color, buy2_color, buy3_color = (
            st.color_picker("一买颜色", defaults.buy1.color, key="style_buy1_color"),
            st.color_picker("二买颜色", defaults.buy2.color, key="style_buy2_color"),
            st.color_picker("三买颜色", defaults.buy3.color, key="style_buy3_color"),
        )
        buy1_size, buy2_size, buy3_size = (
            st.slider("一买大小", 4.0, 26.0, float(defaults.buy1.size), 0.5, key="style_buy1_size"),
            st.slider("二买大小", 4.0, 26.0, float(defaults.buy2.size), 0.5, key="style_buy2_size"),
            st.slider("三买大小", 4.0, 26.0, float(defaults.buy3.size), 0.5, key="style_buy3_size"),
        )
        sell1_color, sell2_color, sell3_color = (
            st.color_picker("一卖颜色", defaults.sell1.color, key="style_sell1_color"),
            st.color_picker("二卖颜色", defaults.sell2.color, key="style_sell2_color"),
            st.color_picker("三卖颜色", defaults.sell3.color, key="style_sell3_color"),
        )
        sell1_size, sell2_size, sell3_size = (
            st.slider("一卖大小", 4.0, 26.0, float(defaults.sell1.size), 0.5, key="style_sell1_size"),
            st.slider("二卖大小", 4.0, 26.0, float(defaults.sell2.size), 0.5, key="style_sell2_size"),
            st.slider("三卖大小", 4.0, 26.0, float(defaults.sell3.size), 0.5, key="style_sell3_size"),
        )

        st.markdown("**实时未收盘 K 背景**")
        c1, c2 = st.columns(2)
        live_bar_color = c1.color_picker(
            "背景颜色", defaults.live_bar.color, key="style_live_bar_color"
        )
        live_bar_opacity = c2.slider(
            "背景填充", 0.0, 0.50, float(defaults.live_bar.fill_opacity), 0.01,
            key="style_live_bar_opacity",
        )

        st.markdown("**鼠标悬停数据框**")
        hover_enabled = st.toggle(
            "显示悬停数据框",
            value=defaults.hover.enabled,
            key="style_hover_enabled",
            help="关闭后，鼠标经过 K 线、笔、线段、中枢和买卖点时都不会弹出数据框。",
        )
        c1, c2 = st.columns(2)
        hover_background_color = c1.color_picker(
            "悬停背景颜色",
            defaults.hover.background_color,
            key="style_hover_background_color",
            disabled=not hover_enabled,
        )
        hover_background_opacity = c2.slider(
            "悬停背景不透明度",
            0.0,
            1.0,
            float(defaults.hover.background_opacity),
            0.01,
            key="style_hover_background_opacity",
            disabled=not hover_enabled,
            help="0 表示完全透明，1 表示完全不透明。",
        )

    return ChartStyle(
        stroke=LineLayerStyle(stroke_color, stroke_width, stroke_marker_size),
        segment=LineLayerStyle(segment_color, segment_width, segment_marker_size),
        central_zone=ZoneLayerStyle(
            central_zone_color, central_zone_width, central_zone_marker_size, central_zone_opacity
        ),
        segment_central_zone=ZoneLayerStyle(
            segment_zone_color, segment_zone_width, segment_zone_marker_size, segment_zone_opacity
        ),
        top_fractal=MarkerLayerStyle(
            top_fractal_color, top_fractal_size, top_fractal_border, defaults.top_fractal.opacity
        ),
        bottom_fractal=MarkerLayerStyle(
            bottom_fractal_color, bottom_fractal_size, bottom_fractal_border, defaults.bottom_fractal.opacity
        ),
        buy1=MarkerLayerStyle(buy1_color, buy1_size, point_border),
        buy2=MarkerLayerStyle(buy2_color, buy2_size, point_border),
        buy3=MarkerLayerStyle(buy3_color, buy3_size, point_border),
        sell1=MarkerLayerStyle(sell1_color, sell1_size, point_border),
        sell2=MarkerLayerStyle(sell2_color, sell2_size, point_border),
        sell3=MarkerLayerStyle(sell3_color, sell3_size, point_border),
        live_bar=LiveBarStyle(live_bar_color, live_bar_opacity),
        hover=HoverLabelStyle(hover_enabled, hover_background_color, hover_background_opacity),
    )


st.set_page_config(page_title=f"CZSC 结构检查台 v{APP_VERSION}", page_icon="📈", layout="wide")
st.title(f"CZSC 结构检查台 · 5000 根实时数据版 v{APP_VERSION}")
st.caption(
    "Binance 5000 根已收盘 K + 当前实时 K → 确认结构用实线 → 未确认笔/线段用同色虚线 → 双层中枢 → 买卖点"
)

with st.sidebar:
    source = st.radio("数据源", ["Binance", "CSV", "演示数据"], index=0)
    symbol = st.text_input("交易对", "BTCUSDT").upper().strip()
    interval = st.selectbox(
        "周期",
        ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"],
        index=2,
    )
    count = st.number_input("已收盘 K 线历史数量", min_value=30, max_value=5000, value=5000, step=100)
    recommended_seconds = recommended_refresh_seconds(interval)
    auto_refresh = st.toggle(
        "自动刷新实时 K",
        value=True,
        disabled=source != "Binance",
        help="首次拉取完整历史；之后只增量拉取尾部 K，不会每次重复下载 5000 根。",
    )
    refresh_seconds = st.number_input(
        "刷新间隔（秒）",
        min_value=5,
        max_value=3600,
        value=recommended_seconds,
        step=5,
        key=f"refresh_seconds_{interval}",
        disabled=source != "Binance" or not auto_refresh,
        help=f"{interval} 推荐 {recommended_seconds} 秒。当前 K 的交易所推送更快，但 UI 无需按每个 tick 全量重绘。",
    )
    st.caption(
        "推荐：1m 10s、3m 20s、5m 30s、15m 60s、30m 90s、1h 120s；"
        "高周期 3~30 分钟刷新。"
    )
    min_bi_len = st.number_input(
        "最小笔长（无包含 K 数）",
        min_value=3,
        max_value=30,
        value=6,
        step=1,
        help="CZSC v0.9.69 默认值为 6；老笔规则常用 7。",
    )
    segment_mode = SegmentMode.FEATURE_SEQUENCE
    st.info(
        "已确认结构只使用已收盘 K。当前未收盘 K 及尚未形成完整分型/特征序列的尾部结构，"
        "只会作为同色虚线候选展示，不参与中枢和买卖点确认。"
    )
    compatibility = st.toggle(
        "CZSC check_fxs 兼容过滤",
        value=True,
        help="成笔状态机使用 CZSC v0.9.69 分型兼容规则。",
    )
    show_central_zones = st.toggle("图上显示笔中枢", value=True)
    show_segment_central_zones = st.toggle("图上显示线段中枢", value=True)
    show_segments = st.toggle("图上显示线段", value=True)
    show_trading_points = st.toggle("图上显示一/二/三类买卖点", value=True)
    show_strokes = st.toggle("图上显示笔", value=True)
    show_fractals = st.toggle("图上显示全部分型", value=False)
    chart_style = _chart_style_controls()
    market_value = st.selectbox(
        "Binance 市场",
        [BinanceMarket.SPOT, BinanceMarket.USD_M_FUTURES],
        format_func=lambda x: x.label,
        disabled=source != "Binance",
    )
    uploaded = st.file_uploader("上传 CSV", type=["csv"], disabled=source != "CSV")
    c_load, c_refresh = st.columns(2)
    load = c_load.button("完整加载", type="primary", use_container_width=True)
    manual_refresh = c_refresh.button(
        "立即刷新", use_container_width=True, disabled=source != "Binance"
    )


def _config_fingerprint() -> tuple:
    return (
        source,
        symbol,
        interval,
        int(count),
        int(min_bi_len),
        bool(compatibility),
        market_value.value if source == "Binance" else None,
        getattr(uploaded, "name", None),
    )


def _load_initial_bundle():
    if source == "演示数据":
        bars = demo_bars(int(count), symbol="DEMOUSDT", interval=interval)
        metadata = AnalysisMetadata.demo()
        return analyze_static(
            bars,
            czsc_compatibility=compatibility,
            min_bi_len=int(min_bi_len),
            metadata=metadata,
            segment_mode=segment_mode,
        )
    if source == "CSV":
        if uploaded is None:
            st.info("请先上传 CSV；至少包含 open_time/open/high/low/close。")
            st.stop()
        bars = bars_from_csv(uploaded, symbol=symbol or "CSV", interval=interval)[-int(count):]
        metadata = AnalysisMetadata(
            source_name=f"用户上传 CSV：{uploaded.name}",
            market="CSV / 自定义数据",
            note="CSV 数据按已收盘 K 处理；请自行确认市场、复权和时区口径",
        )
        return analyze_static(
            bars,
            czsc_compatibility=compatibility,
            min_bi_len=int(min_bi_len),
            metadata=metadata,
            segment_mode=segment_mode,
        )

    client = BinanceKlineClient()
    with st.spinner(f"正在分页获取 Binance 最近 {int(count)} 根已收盘 K，并读取当前实时 K……"):
        snapshot = client.fetch_snapshot(
            symbol,
            interval,
            history_limit=int(count),
            market=market_value,
        )
    metadata = AnalysisMetadata.binance_rest(
        market=f"Binance {market_value.label}",
        source_url=client.source_url(market_value),
    )
    return analyze_snapshot(
        snapshot,
        czsc_compatibility=compatibility,
        min_bi_len=int(min_bi_len),
        metadata=metadata,
        segment_mode=segment_mode,
    )


def _refresh_binance_bundle(previous):
    if previous.snapshot is None:
        return _load_initial_bundle()
    client = BinanceKlineClient()
    snapshot = client.refresh_snapshot(previous.snapshot)
    return analyze_snapshot(
        snapshot,
        czsc_compatibility=compatibility,
        min_bi_len=int(min_bi_len),
        metadata=previous.confirmed.metadata,
        segment_mode=segment_mode,
        previous=previous,
    )


fingerprint = _config_fingerprint()
needs_initial_load = (
    load
    or "live_bundle" not in st.session_state
    or st.session_state.get("config_fingerprint") != fingerprint
)
if needs_initial_load:
    try:
        bundle = _load_initial_bundle()
        st.session_state.live_bundle = bundle
        st.session_state.analysis = bundle.confirmed
        st.session_state.config_fingerprint = fingerprint
        st.session_state.last_refresh_monotonic = time.monotonic()
        st.session_state.last_refresh_error = None
    except Exception as exc:
        st.error(str(exc))
        st.stop()
elif manual_refresh and source == "Binance":
    try:
        bundle = _refresh_binance_bundle(st.session_state.live_bundle)
        st.session_state.live_bundle = bundle
        st.session_state.analysis = bundle.confirmed
        st.session_state.last_refresh_monotonic = time.monotonic()
        st.session_state.last_refresh_error = None
    except Exception as exc:
        st.session_state.last_refresh_error = str(exc)
        st.error(f"立即刷新失败：{exc}")

bundle = st.session_state.live_bundle
result = bundle.confirmed
live_overlay = bundle.overlay
st.info(provenance_text(result))
if bundle.snapshot is not None:
    snapshot = bundle.snapshot
    live_text = (
        f"已收盘历史 {len(snapshot.closed_bars)} 根；实时未收盘 K "
        f"{'1 根' if snapshot.current_bar else '暂未取得'}；刷新时间 "
        f"{snapshot.fetched_at.strftime('%Y-%m-%d %H:%M:%S UTC')}；时间缺口 {snapshot.gap_count}。"
    )
    st.success(live_text)
    if auto_refresh:
        st.caption(f"自动刷新已开启：每 {int(refresh_seconds)} 秒增量更新尾部 K。")
if st.session_state.get("last_refresh_error"):
    st.warning(f"上次自动刷新失败，已保留上一份完整快照：{st.session_state.last_refresh_error}")
if result.metadata.source_url:
    st.link_button("打开数据接口 / 来源", result.metadata.source_url)
if result.metadata.is_demo:
    st.warning("当前是 DEMO / 模拟数据，不代表任何真实市场行情。")

m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
m1.metric("原始 K", len(result.raw_bars))
m2.metric("无包含 K", len(result.merged_bars))
m3.metric("分型", len(result.fractals))
m4.metric("笔", len(result.strokes))
m5.metric("已确认线段", len(result.segments))
m6.metric("笔中枢", len(result.central_zones))
m7.metric("线段中枢", len(result.segment_central_zones))
m8.metric("买卖点", len(result.trading_points))

live_m1, live_m2, live_m3, live_m4 = st.columns(4)
live_m1.metric("实时未收盘 K", 1 if bundle.snapshot and bundle.snapshot.current_bar else 0)
live_m2.metric("未确认笔虚线", len(live_overlay.provisional_strokes))
live_m3.metric("未确认线段虚线", len(live_overlay.provisional_segments))
live_m4.metric("数据缺口", bundle.snapshot.gap_count if bundle.snapshot else 0)

with st.expander("实时尾部候选数据（虚线）", expanded=False):
    st.caption(
        "这些行与图中的同色虚线一一对应，会随着当前 K 和后续已收盘 K 迁移或消失；"
        "它们不参与中枢、买卖点或后续消息确认。"
    )
    provisional_stroke_df = provisional_lines_frame(live_overlay, structure="stroke")
    provisional_segment_df = provisional_lines_frame(live_overlay, structure="segment")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**未确认笔**")
        if provisional_stroke_df.empty:
            st.info("当前没有未确认笔候选。")
        else:
            st.dataframe(provisional_stroke_df, use_container_width=True, hide_index=True)
            st.download_button(
                "下载未确认笔 CSV",
                provisional_stroke_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="provisional_strokes.csv",
                mime="text/csv",
                use_container_width=True,
                key="download_provisional_strokes_csv",
            )
    with c2:
        st.markdown("**未确认线段**")
        if provisional_segment_df.empty:
            st.info("当前没有未确认线段候选。")
        else:
            st.dataframe(provisional_segment_df, use_container_width=True, hide_index=True)
            st.download_button(
                "下载未确认线段 CSV",
                provisional_segment_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="provisional_segments.csv",
                mime="text/csv",
                use_container_width=True,
                key="download_provisional_segments_csv",
            )

s1, s2, s3 = st.columns(3)
s1.metric("最小笔长", result.min_bi_len)
s2.metric("线段模式", result.segment_mode.label)
if len(result.segments) < 3:
    segment_zone_status = f"不足 3 段（当前 {len(result.segments)} 段）"
elif result.segment_central_zones:
    segment_zone_status = f"已识别 {len(result.segment_central_zones)} 个"
else:
    segment_zone_status = "无三段共同重叠"
s3.metric("线段中枢状态", segment_zone_status)

(
    trading_point_tab,
    trading_point_compare_tab,
    segment_central_zone_tab,
    segment_central_zone_compare_tab,
    central_zone_tab,
    central_zone_compare_tab,
    segment_tab,
    segment_compare_tab,
    pen_tab,
    compare_tab,
    raw_tab,
    merged_tab,
    fractal_tab,
    diagnostics_tab,
) = st.tabs(
    [
        "买卖点数据验证",
        "买卖点独立差分",
        "线段中枢数据验证",
        "线段中枢独立差分",
        "笔中枢数据验证",
        "CZSC 笔中枢差分",
        "线段数据验证",
        "特征序列独立差分",
        "笔数据验证",
        "CZSC 基础层差分",
        "原始 K 线画双层中枢",
        "去包含 K 线画双层中枢",
        "分型明细",
        "诊断",
    ]
)

with trading_point_tab:
    st.subheader("一、二、三类买卖点数据验证")
    st.caption(
        "正式口径：B1/S1 必须由至少两个同向线段中枢构成趋势，并以进入/离开最后中枢的同向线段做 MACD 柱面积背驰；"
        "B2/S2 除首次回试不破一类点外，回试终点还必须出现笔级别一类点；"
        "B3/S3 是离开线段中枢后的首次反向走势不重新进入固定 ZD~ZG。"
        "结构时间与实际可通知时间分开保存。"
    )
    point_issues = validate_trading_points(
        result.trading_points, result.segments, result.segment_central_zones, raw_bars=result.raw_bars
    )
    if point_issues:
        st.error("买卖点数据层校验失败，应停止画点并检查下表。")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in point_issues],
            use_container_width=True, hide_index=True,
        )
    else:
        st.success("买卖点不变量校验通过：方向、线段端点、二类点回试及三类点中枢边界均满足。")

    counts = {k: sum(x.point_type.value == k for x in result.trading_points) for k in ("B1", "B2", "B3", "S1", "S2", "S3")}
    cols = st.columns(6)
    for col, key in zip(cols, ("B1", "B2", "B3", "S1", "S2", "S3")):
        col.metric(key, counts[key])
    point_df = trading_points_frame(result)
    if point_df.empty:
        st.info("当前已确认线段尚未形成满足本级别规则的买卖点。")
    else:
        st.dataframe(point_df, use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button(
            "下载买卖点明细 CSV",
            point_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="trading_points.csv", mime="text/csv", use_container_width=True,
            key="download_trading_points_csv",
        )
        d2.download_button(
            "下载本次原始 K 线 CSV",
            raw_frame(result).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{result.raw_bars[0].symbol}_{result.raw_bars[0].interval}_raw_bars.csv",
            mime="text/csv", use_container_width=True, key="download_trading_point_raw_bars_csv",
        )

    st.subheader("一类点趋势背驰证据")
    divergence_df = trend_divergences_frame(result)
    if divergence_df.empty:
        st.info("当前没有形成可比较进入段与离开段的完整趋势。")
    else:
        st.dataframe(divergence_df, use_container_width=True, hide_index=True)

    st.subheader("全部买卖点候选与淘汰原因")
    candidate_df = trading_point_candidates_frame(result)
    if candidate_df.empty:
        st.info("当前没有产生买卖点候选。")
    else:
        st.dataframe(candidate_df, use_container_width=True, hide_index=True)
        st.download_button(
            "下载买卖点候选诊断 CSV",
            candidate_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="trading_point_candidates.csv", mime="text/csv", use_container_width=True,
            key="download_trading_point_candidates_csv",
        )

with trading_point_compare_tab:
    point_comparison = compare_trading_points_with_reference(
        result.trading_points, result.segments, result.segment_central_zones, raw_bars=result.raw_bars
    )
    st.caption(
        f"参考：{point_comparison.reference_name}。冻结参考将线段转换为基础字典后独立执行，不调用生产识别器。"
    )
    l1, l2 = st.columns(2)
    l1.link_button("打开 CZSC 仓库", point_comparison.cxt_url)
    l2.link_button("打开缠论技术原理", point_comparison.wiki_url)
    c1, c2 = st.columns(2)
    c1.metric("逐点一致", f"{point_comparison.match_count}/{len(point_comparison.rows)}")
    c2.metric("差分结论", "全部一致" if point_comparison.all_match else "存在差异")
    if point_comparison.all_match:
        st.success("六类买卖点生产实现与独立字典复算逐项一致。")
    else:
        st.error("买卖点差分存在不一致，应停止画点并检查数据层。")
    point_compare_df = point_comparison.frame()
    show_all_points = st.toggle("显示全部买卖点比较行", value=False, key="show_all_trading_point_rows")
    if not show_all_points and not point_compare_df.empty:
        point_compare_df = point_compare_df[point_compare_df["一致"] == False]  # noqa: E712
    if point_compare_df.empty:
        st.success("没有差异行。")
    else:
        st.dataframe(point_compare_df, use_container_width=True, hide_index=True)

with segment_central_zone_tab:
    st.subheader("已识别线段中枢")
    st.caption(
        "线段中枢只使用标准特征序列已经确认的完整线段。任意三个连续线段存在共同价格重叠时形成种子，"
        "ZG/ZD 固定由这三个线段确定；后续线段仍与固定区间相交时，中枢继续延伸。"
        "未完成线段尾部不参与计算。"
    )
    segment_zone_issues = validate_segment_central_zones(
        result.segment_central_zones,
        result.segments,
    )
    if segment_zone_issues:
        st.error("线段中枢数据层校验失败，应停止绘制线段中枢并检查下表。")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in segment_zone_issues],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("线段中枢校验通过：三段重叠、固定边界、连续切片、延伸和最大性均满足。")

    segment_zone_df = segment_central_zones_frame(result)
    if segment_zone_df.empty:
        st.warning("当前已确认线段不足，或尚未出现三个连续线段的共同重叠区。")
    else:
        st.dataframe(segment_zone_df, use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button(
            "下载线段中枢明细 CSV",
            segment_zone_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="segment_central_zones.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_segment_central_zones_csv",
        )
        d2.download_button(
            "下载本次原始 K 线 CSV",
            raw_frame(result).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{result.raw_bars[0].symbol}_{result.raw_bars[0].interval}_raw_bars.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_segment_central_zone_raw_bars_csv",
        )

    st.subheader("全部三线段重叠候选")
    st.caption(
        "候选表逐个列出所有连续三线段窗口的有效重叠。最终中枢采用时间最早有效窗口优先，"
        "并向后最大延伸，因此同一个最终中枢内部可能包含多个三段候选。"
    )
    candidate_df = segment_central_zone_candidates_frame(result)
    if candidate_df.empty:
        st.info("没有三线段重叠候选。")
    else:
        st.dataframe(candidate_df, use_container_width=True, hide_index=True)

with segment_central_zone_compare_tab:
    segment_zone_comparison = compare_segment_central_zones_with_reference(
        result.segment_central_zones,
        result.segment_central_zone_candidates,
        result.segments,
    )
    st.caption(
        f"参考：{segment_zone_comparison.reference_name}。参考模块不调用生产识别器，"
        "以原始线段字典重新执行三段交集、固定边界和最大延伸。"
    )
    l1, l2 = st.columns(2)
    l1.link_button("打开中枢定义参考", segment_zone_comparison.definition_url)
    l2.link_button("打开 CZSC ZS 数值源码", segment_zone_comparison.object_url)
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "三段候选",
        f"{segment_zone_comparison.candidate_match_count}/{len(segment_zone_comparison.candidate_rows)}",
    )
    c2.metric(
        "最终线段中枢",
        f"{segment_zone_comparison.zone_match_count}/{len(segment_zone_comparison.zone_rows)}",
    )
    c3.metric("差分结论", "全部一致" if segment_zone_comparison.all_match else "存在差异")
    if segment_zone_comparison.all_match:
        st.success("线段中枢生产实现与独立冻结参考逐项一致。")
    else:
        st.error("线段中枢差分存在不一致，应停止画图并检查数据层。")

    show_all_segment_zones = st.toggle("显示全部线段中枢比较行", value=False)
    for heading, frame in [
        ("最终线段中枢逐项比较", segment_zone_comparison.zone_frame()),
        ("三段候选逐项比较", segment_zone_comparison.candidate_frame()),
    ]:
        st.subheader(heading)
        if not show_all_segment_zones and not frame.empty:
            frame = frame[frame["一致"] == False]  # noqa: E712
        if frame.empty:
            st.success("没有差异行。")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)

with central_zone_tab:
    st.subheader("已识别笔中枢")
    st.caption(
        "本阶段使用 CZSC 的笔中枢口径：前三笔的价格重叠区定义 ZD~ZG；后续笔仍与该区间相交时延伸中枢。"
        "先验证连续笔切片、前三笔重叠边界和每笔相交条件，再允许图上绘制。"
    )
    zone_issues = validate_central_zones(result.central_zones, result.strokes)
    if zone_issues:
        st.error("中枢不变量校验失败，应停止画图并检查数据层。")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in zone_issues],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("有效中枢校验通过：笔数、连续性、ZD/ZG 边界和全体笔相交条件均满足。")

    zone_df = central_zones_frame(result)
    if zone_df.empty:
        st.warning("当前笔链尚未形成有效中枢。")
    else:
        st.dataframe(zone_df, use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button(
            "下载中枢明细 CSV",
            zone_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="central_zones.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_central_zones_csv",
        )
        d2.download_button(
            "下载本次原始 K 线 CSV",
            raw_frame(result).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{result.raw_bars[0].symbol}_{result.raw_bars[0].interval}_raw_bars.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_central_zone_raw_bars_csv",
        )

    st.subheader("全部中枢分组")
    st.caption("保留不足三笔或无效的分组，方便核对为什么某一段笔链没有被认定为有效中枢。")
    st.dataframe(central_zone_groups_frame(result), use_container_width=True, hide_index=True)

with central_zone_compare_tab:
    central_comparison = compare_central_zones_with_czsc(
        result.central_zones,
        result.central_zone_groups,
        result.strokes,
    )
    st.caption(
        f"参考：{central_comparison.reference_name}。分组按历史 get_zs_seq 独立执行，"
        "ZG/ZD/ZZ/GG/DD 与有效性按当前 Rust ZS 独立计算。"
    )
    l1, l2 = st.columns(2)
    l1.link_button("打开 get_zs_seq 参考源码", central_comparison.reference_url)
    l2.link_button("打开当前 Rust ZS 源码", central_comparison.object_url)
    c1, c2, c3 = st.columns(3)
    c1.metric("中枢分组", f"{central_comparison.group_match_count}/{len(central_comparison.group_rows)}")
    c2.metric("有效中枢", f"{central_comparison.zone_match_count}/{len(central_comparison.zone_rows)}")
    c3.metric("差分结论", "全部一致" if central_comparison.all_match else "存在差异")
    if central_comparison.all_match:
        st.success("中枢分组与有效中枢结果均与冻结 CZSC 参考逻辑逐项一致。")
    else:
        st.error("中枢差分存在不一致，应停止画图并检查数据层。")

    show_all_zones = st.toggle("显示全部中枢比较行", value=False)
    for heading, frame in [
        ("有效中枢逐项比较", central_comparison.zone_frame()),
        ("全部分组逐项比较", central_comparison.group_frame()),
    ]:
        st.subheader(heading)
        if not show_all_zones and not frame.empty:
            frame = frame[frame["一致"] == False]  # noqa: E712
        if frame.empty:
            st.success("没有差异行。")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)

with segment_tab:
    st.subheader("标准特征序列线段数据验证")
    st.caption(
        "向上线段只取向下笔组成特征序列并寻找顶分型；向下线段只取向上笔组成特征序列并寻找底分型。"
        "第一、二特征元素无缺口时直接确认；有缺口时必须等待从候选端点开始的反向特征序列分型，"
        "等待期间若出现更极端的合法端点会迁移并重启反向确认。"
        "首段会扫描所有可能起点，并额外校验向上段的最低底/最高顶、向下段的最高顶/最低底；"
        "终点最早的完整候选优先，候选起点之前的笔进入窗口前缀未解析区。"
    )
    feature_tail_position = max(
        (
            position
            for element in result.feature_elements
            for position in element.stroke_positions
        ),
        default=-1,
    )
    last_stroke_position = len(result.strokes) - 1
    feature_tail_gap = (
        last_stroke_position - feature_tail_position
        if feature_tail_position >= 0
        else len(result.strokes)
    )
    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric("特征元素", len(result.feature_elements))
    fc2.metric("特征分型", len(result.feature_fractals))
    fc3.metric("扫描至笔位置", f"{feature_tail_position} / {last_stroke_position}")
    fc4.metric("尾部未扫描笔数", feature_tail_gap)

    first_evidence = result.segment_evidence[0] if result.segment_evidence else None
    boundary_violations = sum(
        item.code == "FIRST_SEGMENT_EXTREME_VIOLATION"
        for item in result.segment_diagnostics
    )
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.metric(
        "首段起点笔位置",
        first_evidence.start_position if first_evidence is not None else "—",
    )
    bc2.metric(
        "首段终点笔位置",
        first_evidence.end_position if first_evidence is not None else "—",
    )
    bc3.metric("窗口前缀未解析笔", len(result.unresolved_segment_prefix_strokes))
    bc4.metric("已排除极值违规候选", boundary_violations)

    segment_issues = validate_segment_chain(
        result.segments,
        result.strokes,
        mode=result.segment_mode,
        evidence=result.segment_evidence,
        exclude_last_stroke_confirmation=True,
    )
    if segment_issues:
        st.error("线段数据层校验失败，应停止绘图并检查下表。")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in segment_issues],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("线段链与每条线段的特征序列确认依据均通过校验。")

    segment_df = segments_frame(result)
    if segment_df.empty:
        st.warning("当前笔链尚未形成可确认的完整线段。")
    else:
        st.dataframe(segment_df, use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button(
            "下载线段明细 CSV",
            segment_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="segments_feature_sequence.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_segments_feature_sequence_csv",
        )
        d2.download_button(
            "下载本次原始 K 线 CSV",
            raw_frame(result).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{result.raw_bars[0].symbol}_{result.raw_bars[0].interval}_raw_bars.csv",
            mime="text/csv",
            use_container_width=True,
            key="download_segment_feature_raw_bars_csv",
        )

    st.subheader("逐条线段确认依据")
    evidence_df = segment_evidence_frame(result)
    if evidence_df.empty:
        st.info("暂无已确认线段依据。")
    else:
        st.dataframe(evidence_df, use_container_width=True, hide_index=True)

    st.subheader("标准特征序列元素")
    element_df = feature_elements_frame(result)
    if element_df.empty:
        st.info("当前数据尚未形成可展示的特征元素。")
    else:
        st.dataframe(element_df, use_container_width=True, hide_index=True)

    st.subheader("特征序列分型")
    feature_fx_df = feature_fractals_frame(result)
    if feature_fx_df.empty:
        st.info("当前数据尚未形成特征序列分型。")
    else:
        st.dataframe(feature_fx_df, use_container_width=True, hide_index=True)

    p1, p2 = st.columns(2)
    with p1:
        st.subheader("窗口前缀未解析笔")
        st.caption("行情窗口缺少更早历史时，前部笔不强行归入第一条线段。")
        prefix_df = unresolved_segment_prefix_frame(result)
        if prefix_df.empty:
            st.info("没有未解析窗口前缀。")
        else:
            st.dataframe(prefix_df, use_container_width=True, hide_index=True)
    with p2:
        st.subheader("未完成线段区域")
        st.caption("最后一个已确认线段端点之后的笔仍在演化，不绘制成已完成线段。")
        unfinished_segment_df = unfinished_segment_frame(result)
        if unfinished_segment_df.empty:
            st.info("当前没有未完成线段区域。")
        else:
            st.dataframe(unfinished_segment_df, use_container_width=True, hide_index=True)

with segment_compare_tab:
    segment_comparison = compare_feature_sequence_reference(
        result.segments,
        result.segment_evidence,
        result.strokes,
    )
    st.caption(
        f"参考：{segment_comparison.reference_name}。参考模块不调用生产线段识别器，"
        "以独立状态对象重新执行包含处理、特征分型、真实突破和缺口反向确认。"
    )
    st.link_button("打开线段原理参考", segment_comparison.reference_url)
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "线段",
        f"{segment_comparison.segment_match_count}/{len(segment_comparison.segment_rows)}",
    )
    c2.metric(
        "确认依据",
        f"{segment_comparison.evidence_match_count}/{len(segment_comparison.evidence_rows)}",
    )
    c3.metric("差分结论", "全部一致" if segment_comparison.all_match else "存在差异")
    if segment_comparison.all_match:
        st.success("生产实现与独立标准特征序列参考实现逐项一致。")
    else:
        st.error("特征序列差分存在不一致，应停止绘图并检查数据层。")

    show_all_segments = st.toggle("显示全部特征序列比较行", value=False)
    for heading, frame in [
        ("线段逐条比较", segment_comparison.segment_frame()),
        ("确认依据逐条比较", segment_comparison.evidence_frame()),
    ]:
        st.subheader(heading)
        if not show_all_segments and not frame.empty:
            frame = frame[frame["一致"] == False]  # noqa: E712
        if frame.empty:
            st.success("没有差异行。")
        else:
            st.dataframe(frame, use_container_width=True, hide_index=True)

with pen_tab:
    st.subheader("已识别笔")
    chain_issues = validate_stroke_chain(result.strokes, min_bi_len=result.min_bi_len)
    if chain_issues:
        st.error("最终笔链不变量校验失败。")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in chain_issues],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("最终笔链校验通过。")
    st.dataframe(strokes_frame(result), use_container_width=True, hide_index=True)
    st.subheader("未完成笔区域 bars_ubi")
    st.dataframe(unfinished_frame(result), use_container_width=True, hide_index=True)

with compare_tab:
    comparison = compare_with_czsc_reference(result)
    st.caption(
        f"参考：{comparison.reference_name}。本项目笔层包含共享端点校正，因此笔差异可能是预期；"
        "去包含 K 与分型必须一致。"
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("无包含 K", f"{comparison.merged_match_count}/{len(comparison.merged_rows)}")
    c2.metric("分型", f"{comparison.fractal_match_count}/{len(comparison.fractal_rows)}")
    c3.metric("笔", f"{comparison.stroke_match_count}/{len(comparison.stroke_rows)}")
    c4.metric("未完成区", f"{comparison.unfinished_match_count}/{len(comparison.unfinished_rows)}")
    if comparison.merged_match and comparison.fractal_match:
        st.success("基础数据层一致。")
    else:
        st.error("去包含 K 或分型存在差异，应先停止。")

with raw_tab:
    if show_segment_central_zones:
        if len(result.segments) < 3:
            st.info(
                f"当前只有 {len(result.segments)} 条已确认线段；线段中枢至少需要 3 条连续已确认线段，"
                "因此本图不会出现线段中枢框。"
            )
        elif not result.segment_central_zones:
            st.info(
                f"当前已有 {len(result.segments)} 条已确认线段，但没有任意连续三条线段存在共同价格重叠，"
                "因此本图不会出现线段中枢框。"
            )
        else:
            st.success(f"已识别 {len(result.segment_central_zones)} 个线段中枢，图中以当前用户配置的颜色显示。")
    st.plotly_chart(
        build_raw_chart(
            result,
            show_fractals=show_fractals,
            show_strokes=show_strokes,
            show_segments=show_segments,
            show_central_zones=show_central_zones,
            show_segment_central_zones=show_segment_central_zones,
            show_trading_points=show_trading_points,
            live_overlay=live_overlay,
            style=chart_style,
        ),
        use_container_width=True,
        config=PLOTLY_CONFIG,
    )
    st.caption("笔中枢、线段中枢、笔、线段、分型和买卖点均使用侧边栏的自定义样式；实线为已确认结构，虚线为未确认候选。触控板双指滚动缩放，拖拽平移；悬停数据框可在侧边栏关闭或调整背景。")

with merged_tab:
    if show_segment_central_zones:
        if len(result.segments) < 3:
            st.info(
                f"当前只有 {len(result.segments)} 条已确认线段；线段中枢至少需要 3 条连续已确认线段，"
                "因此本图不会出现线段中枢框。"
            )
        elif not result.segment_central_zones:
            st.info(
                f"当前已有 {len(result.segments)} 条已确认线段，但没有任意连续三条线段存在共同价格重叠，"
                "因此本图不会出现线段中枢框。"
            )
        else:
            st.success(f"已识别 {len(result.segment_central_zones)} 个线段中枢，图中以当前用户配置的颜色显示。")
    st.plotly_chart(
        build_merged_chart(
            result,
            show_fractals=show_fractals,
            show_strokes=show_strokes,
            show_segments=show_segments,
            show_central_zones=show_central_zones,
            show_segment_central_zones=show_segment_central_zones,
            show_trading_points=show_trading_points,
            live_overlay=live_overlay,
            style=chart_style,
        ),
        use_container_width=True,
        config=PLOTLY_CONFIG,
    )
    st.dataframe(merged_frame(result), use_container_width=True, hide_index=True)

with fractal_tab:
    st.dataframe(fractals_frame(result), use_container_width=True, hide_index=True)

with diagnostics_tab:
    if result.trading_point_diagnostics:
        st.subheader("买卖点识别记录")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in result.trading_point_diagnostics],
            use_container_width=True, hide_index=True,
        )
    else:
        st.success("本批数据没有买卖点诊断记录。")

    if result.segment_central_zone_diagnostics:
        st.subheader("线段中枢处理记录")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in result.segment_central_zone_diagnostics],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("本批数据没有线段中枢诊断记录。")

    if result.central_zone_diagnostics:
        st.subheader("中枢分组处理记录")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in result.central_zone_diagnostics],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("本批数据没有中枢分组诊断记录。")

    if result.segment_diagnostics:
        st.subheader("线段候选处理记录")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in result.segment_diagnostics],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("本批数据没有线段候选回退记录。")

    if result.stroke_diagnostics:
        st.subheader("笔状态回退记录")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in result.stroke_diagnostics],
            use_container_width=True,
            hide_index=True,
        )

    if result.diagnostics:
        st.subheader("分型序列诊断")
        st.dataframe(
            [{"代码": x.code, "时间": x.dt, "说明": x.message} for x in result.diagnostics],
            use_container_width=True,
            hide_index=True,
        )

# 自动刷新采用 Streamlit fragment：首次加载 5000 根，之后只更新尾部；
# 刷新失败时保留上一份已验证快照，不让半截数据进入结构计算。
_auto_run_every = int(refresh_seconds) if source == "Binance" and auto_refresh else None


@st.fragment(run_every=_auto_run_every)
def _live_refresh_fragment() -> None:
    if _auto_run_every is None:
        return
    elapsed = time.monotonic() - st.session_state.get("last_refresh_monotonic", 0.0)
    if elapsed < _auto_run_every * 0.8:
        return
    try:
        old_bundle = st.session_state.live_bundle
        new_bundle = _refresh_binance_bundle(old_bundle)
        st.session_state.live_bundle = new_bundle
        st.session_state.analysis = new_bundle.confirmed
        st.session_state.last_refresh_monotonic = time.monotonic()
        st.session_state.last_refresh_error = None
        st.rerun()
    except Exception as exc:  # 保留上一快照并在下一周期重试
        st.session_state.last_refresh_monotonic = time.monotonic()
        st.session_state.last_refresh_error = str(exc)
        st.warning(f"自动刷新失败，已保留上一份数据：{exc}")


_live_refresh_fragment()
