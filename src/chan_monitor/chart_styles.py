from __future__ import annotations

from dataclasses import dataclass

from .models import TradingPointType


def _validate_hex_color(value: str) -> str:
    value = value.strip().upper()
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"颜色必须是 #RRGGBB 格式: {value!r}")
    try:
        int(value[1:], 16)
    except ValueError as exc:
        raise ValueError(f"颜色必须是 #RRGGBB 格式: {value!r}") from exc
    return value


def color_with_opacity(color: str, opacity: float) -> str:
    """将十六进制颜色转换成 Plotly 可用的 rgba。"""
    color = _validate_hex_color(color)
    if not 0 <= opacity <= 1:
        raise ValueError("opacity 必须在 0 到 1 之间")
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    return f"rgba({red}, {green}, {blue}, {opacity:.3f})"


@dataclass(frozen=True)
class LineLayerStyle:
    color: str
    width: float
    marker_size: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", _validate_hex_color(self.color))
        if self.width <= 0:
            raise ValueError("线宽必须大于 0")
        if self.marker_size <= 0:
            raise ValueError("端点大小必须大于 0")


@dataclass(frozen=True)
class ZoneLayerStyle:
    color: str
    width: float
    marker_size: float
    fill_opacity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", _validate_hex_color(self.color))
        if self.width <= 0:
            raise ValueError("边框粗细必须大于 0")
        if self.marker_size <= 0:
            raise ValueError("中轴标记大小必须大于 0")
        if not 0 <= self.fill_opacity <= 1:
            raise ValueError("填充透明度必须在 0 到 1 之间")

    @property
    def fillcolor(self) -> str:
        return color_with_opacity(self.color, self.fill_opacity)


@dataclass(frozen=True)
class MarkerLayerStyle:
    color: str
    size: float
    border_width: float
    opacity: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", _validate_hex_color(self.color))
        if self.size <= 0:
            raise ValueError("标记大小必须大于 0")
        if self.border_width < 0:
            raise ValueError("标记边框粗细不能小于 0")
        if not 0 <= self.opacity <= 1:
            raise ValueError("标记透明度必须在 0 到 1 之间")


@dataclass(frozen=True)
class LiveBarStyle:
    color: str
    fill_opacity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", _validate_hex_color(self.color))
        if not 0 <= self.fill_opacity <= 1:
            raise ValueError("实时 K 背景透明度必须在 0 到 1 之间")

    @property
    def fillcolor(self) -> str:
        return color_with_opacity(self.color, self.fill_opacity)


@dataclass(frozen=True)
class HoverLabelStyle:
    enabled: bool
    background_color: str
    background_opacity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "background_color", _validate_hex_color(self.background_color))
        if not 0 <= self.background_opacity <= 1:
            raise ValueError("悬停背景不透明度必须在 0 到 1 之间")

    @property
    def bgcolor(self) -> str:
        return color_with_opacity(self.background_color, self.background_opacity)

    @property
    def text_color(self) -> str:
        # 根据背景亮度自动选择深色或浅色文字，避免用户选深色背景后不可读。
        color = self.background_color
        red = int(color[1:3], 16)
        green = int(color[3:5], 16)
        blue = int(color[5:7], 16)
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return "#111827" if luminance >= 150 else "#F8FAFC"


@dataclass(frozen=True)
class ChartStyle:
    """所有非 K 线图层的样式配置。点类图层用 size 表示视觉粗细。"""

    stroke: LineLayerStyle = LineLayerStyle("#EAB308", 1.1, 5.0)
    segment: LineLayerStyle = LineLayerStyle("#7E22CE", 2.2, 6.5)
    central_zone: ZoneLayerStyle = ZoneLayerStyle("#38BDF8", 1.2, 7.0, 0.12)
    segment_central_zone: ZoneLayerStyle = ZoneLayerStyle("#FB923C", 1.5, 8.0, 0.10)
    top_fractal: MarkerLayerStyle = MarkerLayerStyle("#EF4444", 8.0, 0.8, 0.72)
    bottom_fractal: MarkerLayerStyle = MarkerLayerStyle("#14B8A6", 8.0, 0.8, 0.72)
    buy1: MarkerLayerStyle = MarkerLayerStyle("#15803D", 13.0, 1.2)
    buy2: MarkerLayerStyle = MarkerLayerStyle("#16A34A", 12.0, 1.2)
    buy3: MarkerLayerStyle = MarkerLayerStyle("#22C55E", 11.0, 1.2)
    sell1: MarkerLayerStyle = MarkerLayerStyle("#B91C1C", 13.0, 1.2)
    sell2: MarkerLayerStyle = MarkerLayerStyle("#DC2626", 12.0, 1.2)
    sell3: MarkerLayerStyle = MarkerLayerStyle("#EF4444", 11.0, 1.2)
    live_bar: LiveBarStyle = LiveBarStyle("#FACC15", 0.08)
    hover: HoverLabelStyle = HoverLabelStyle(True, "#FFFFFF", 0.92)

    def trading_point(self, point_type: TradingPointType) -> MarkerLayerStyle:
        return {
            TradingPointType.BUY1: self.buy1,
            TradingPointType.BUY2: self.buy2,
            TradingPointType.BUY3: self.buy3,
            TradingPointType.SELL1: self.sell1,
            TradingPointType.SELL2: self.sell2,
            TradingPointType.SELL3: self.sell3,
        }[point_type]


DEFAULT_CHART_STYLE = ChartStyle()
