from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from chan_monitor.chart import build_raw_chart
from chan_monitor.chart_styles import (
    ChartStyle,
    LineLayerStyle,
    LiveBarStyle,
    HoverLabelStyle,
    MarkerLayerStyle,
    ZoneLayerStyle,
    color_with_opacity,
)
from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import analyze_bars
from chan_monitor.models import TradingPoint, TradingPointType


def _real_result():
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    return analyze_bars(bars_from_csv(path, symbol="BTCUSDT", interval="1h"))


def test_custom_line_and_zone_styles_are_applied() -> None:
    result = _real_result()
    style = ChartStyle(
        stroke=LineLayerStyle("#123456", 0.9, 4.5),
        segment=LineLayerStyle("#654321", 1.7, 5.5),
        central_zone=ZoneLayerStyle("#00AACC", 0.8, 6.0, 0.19),
        segment_central_zone=ZoneLayerStyle("#CC7700", 1.1, 7.0, 0.16),
    )
    figure = build_raw_chart(result, style=style)
    traces = {trace.name: trace for trace in figure.data}
    assert traces["笔"].line.color == "#123456"
    assert traces["笔"].line.width == 0.9
    assert traces["线段"].line.color == "#654321"
    assert traces["线段"].line.width == 1.7
    assert traces["笔中枢"].marker.color == "#00AACC"
    assert traces["线段中枢"].marker.color == "#CC7700"

    zone_shapes = [shape for shape in figure.layout.shapes if shape.type == "rect"]
    assert any(
        shape.line.color == "#00AACC"
        and shape.line.width == 0.8
        and shape.fillcolor == color_with_opacity("#00AACC", 0.19)
        for shape in zone_shapes
    )
    assert any(
        shape.line.color == "#CC7700"
        and shape.line.width == 1.1
        and shape.fillcolor == color_with_opacity("#CC7700", 0.16)
        for shape in zone_shapes
    )


def test_custom_fractal_and_trading_point_styles_are_applied() -> None:
    result = analyze_bars(demo_bars(220, symbol="TESTUSDT", interval="5m"))
    last = result.raw_bars[-1]
    point = TradingPoint(
        symbol="TESTUSDT",
        point_type=TradingPointType.BUY3,
        dt=last.open_time,
        price=last.low,
        segment_index=0,
        confirmed_at_dt=last.close_time + timedelta(seconds=1),
        evidence_kind="STYLE_TEST",
    )
    result = replace(result, trading_points=(point,))
    style = ChartStyle(
        top_fractal=MarkerLayerStyle("#AA0000", 6.0, 0.4, 0.8),
        bottom_fractal=MarkerLayerStyle("#00AA00", 7.0, 0.5, 0.9),
        buy3=MarkerLayerStyle("#1122EE", 17.0, 2.3),
        live_bar=LiveBarStyle("#ABCDEF", 0.17),
    )
    figure = build_raw_chart(result, show_fractals=True, show_trading_points=True, style=style)
    traces = {trace.name: trace for trace in figure.data}
    assert traces["顶分型"].marker.color == "#AA0000"
    assert traces["顶分型"].marker.size == 6.0
    assert traces["底分型"].marker.color == "#00AA00"
    assert traces["底分型"].marker.size == 7.0
    assert traces["三买（B3）"].marker.color == "#1122EE"
    assert traces["三买（B3）"].marker.size == 17.0
    assert traces["三买（B3）"].marker.line.width == 2.3


def test_invalid_style_values_are_rejected() -> None:
    try:
        LineLayerStyle("red", 1.0, 5.0)
    except ValueError as exc:
        assert "#RRGGBB" in str(exc)
    else:
        raise AssertionError("无效颜色应被拒绝")

    try:
        ZoneLayerStyle("#123456", 0, 5, 0.1)
    except ValueError as exc:
        assert "边框粗细" in str(exc)
    else:
        raise AssertionError("零边框粗细应被拒绝")


def test_hover_box_style_can_be_configured_or_disabled() -> None:
    result = _real_result()
    enabled = ChartStyle(hover=HoverLabelStyle(True, "#123456", 0.37))
    figure = build_raw_chart(result, style=enabled)
    assert figure.layout.hovermode == "x unified"
    assert figure.layout.hoverlabel.bgcolor == color_with_opacity("#123456", 0.37)
    assert figure.layout.hoverlabel.bordercolor == "#123456"
    assert figure.layout.hoverlabel.font.color == "#F8FAFC"

    disabled = ChartStyle(hover=HoverLabelStyle(False, "#FFFFFF", 0.92))
    figure = build_raw_chart(result, style=disabled)
    assert figure.layout.hovermode is False
    assert figure.layout.hoverdistance == -1


def test_invalid_hover_opacity_is_rejected() -> None:
    try:
        HoverLabelStyle(True, "#FFFFFF", 1.1)
    except ValueError as exc:
        assert "悬停背景不透明度" in str(exc)
    else:
        raise AssertionError("越界悬停背景不透明度应被拒绝")
