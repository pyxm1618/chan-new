from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class FractalMark(str, Enum):
    TOP = "G"
    BOTTOM = "D"

    @property
    def label(self) -> str:
        return "顶分型" if self is FractalMark.TOP else "底分型"


class StrokeDirection(str, Enum):
    UP = "up"
    DOWN = "down"

    @property
    def label(self) -> str:
        return "向上" if self is StrokeDirection.UP else "向下"

    @property
    def arrow(self) -> str:
        return "↑" if self is StrokeDirection.UP else "↓"


class TradingPointType(str, Enum):
    BUY1 = "B1"
    BUY2 = "B2"
    BUY3 = "B3"
    SELL1 = "S1"
    SELL2 = "S2"
    SELL3 = "S3"

    @property
    def label(self) -> str:
        return {
            TradingPointType.BUY1: "一买",
            TradingPointType.BUY2: "二买",
            TradingPointType.BUY3: "三买",
            TradingPointType.SELL1: "一卖",
            TradingPointType.SELL2: "二卖",
            TradingPointType.SELL3: "三卖",
        }[self]

    @property
    def is_buy(self) -> bool:
        return self in {TradingPointType.BUY1, TradingPointType.BUY2, TradingPointType.BUY3}

    @property
    def side(self) -> str:
        return "买" if self.is_buy else "卖"


class TradingPointStatus(str, Enum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    PENDING = "pending"

    @property
    def label(self) -> str:
        return {
            TradingPointStatus.CONFIRMED: "已确认",
            TradingPointStatus.REJECTED: "未通过",
            TradingPointStatus.PENDING: "待确认",
        }[self]


class FeatureBreakStatus(str, Enum):
    """特征分型的真实突破判定状态。"""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    REJECTED = "rejected"

    @property
    def label(self) -> str:
        return {
            FeatureBreakStatus.CONFIRMED: "已确认",
            FeatureBreakStatus.PENDING: "待后续验证",
            FeatureBreakStatus.REJECTED: "已否定",
        }[self]


@dataclass(frozen=True, slots=True)
class RawBar:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    quote_volume: float = 0.0
    trade_count: int = 0

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise ValueError("open_time 和 close_time 必须是带时区的 datetime")
        if self.close_time < self.open_time:
            raise ValueError("close_time 不能早于 open_time")
        if self.high < self.low:
            raise ValueError("high 不能小于 low")
        if self.high < max(self.open, self.close):
            raise ValueError("high 不能低于 open/close")
        if self.low > min(self.open, self.close):
            raise ValueError("low 不能高于 open/close")

    @classmethod
    def simple(
        cls,
        index: int,
        high: float,
        low: float,
        *,
        symbol: str = "TESTUSDT",
        interval: str = "1h",
        open_: float | None = None,
        close: float | None = None,
    ) -> "RawBar":
        """测试与演示用构造器。"""
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc).replace(hour=0) + _hours(index)
        open_value = low if open_ is None else open_
        close_value = high if close is None else close
        return cls(
            symbol=symbol,
            interval=interval,
            open_time=dt,
            close_time=dt + _hours(1),
            open=open_value,
            high=high,
            low=low,
            close=close_value,
            volume=1.0,
            quote_volume=1.0,
            trade_count=1,
        )


@dataclass(frozen=True, slots=True)
class MacdAnchor:
    """MACD 在输入窗口第一根 K 线之前的精确递推状态。

    有限窗口仅凭自身无法精确恢复 EMA12、EMA26 与 DEA。调用方在滚动窗口、
    服务重启或持久化恢复时，应保存上一根已处理 K 线后的该状态，并将其作为
    下一窗口的 ``macd_anchor`` 传入。
    """

    asof: datetime
    ema_fast: float
    ema_slow: float
    dea: float

    def __post_init__(self) -> None:
        if self.asof.tzinfo is None:
            raise ValueError("MacdAnchor.asof 必须是带时区的 datetime")


@dataclass(frozen=True, slots=True)
class MergedBar:
    id: int
    symbol: str
    interval: str
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    elements: tuple[RawBar, ...] = field(default_factory=tuple)

    @property
    def first_dt(self) -> datetime:
        return self.elements[0].open_time

    @property
    def last_dt(self) -> datetime:
        return self.elements[-1].open_time

    @property
    def raw_count(self) -> int:
        return len(self.elements)

    @classmethod
    def from_raw(cls, bar: RawBar, id_: int) -> "MergedBar":
        return cls(
            id=id_,
            symbol=bar.symbol,
            interval=bar.interval,
            dt=bar.open_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            quote_volume=bar.quote_volume,
            elements=(bar,),
        )


@dataclass(frozen=True, slots=True)
class Fractal:
    symbol: str
    dt: datetime
    mark: FractalMark
    high: float
    low: float
    value: float
    elements: tuple[MergedBar, MergedBar, MergedBar]
    merged_index: int

    @property
    def label(self) -> str:
        return self.mark.label

    @property
    def source_start(self) -> datetime:
        return self.elements[0].first_dt

    @property
    def source_end(self) -> datetime:
        return self.elements[2].last_dt


@dataclass(frozen=True, slots=True)
class Stroke:
    """CZSC 语义下的一笔。"""

    symbol: str
    fx_a: Fractal
    fx_b: Fractal
    fractals: tuple[Fractal, ...]
    direction: StrokeDirection
    bars: tuple[MergedBar, ...]
    index: int = -1

    @property
    def start_dt(self) -> datetime:
        return self.fx_a.dt

    @property
    def end_dt(self) -> datetime:
        return self.fx_b.dt

    @property
    def start_value(self) -> float:
        return self.fx_a.value

    @property
    def end_value(self) -> float:
        return self.fx_b.value

    @property
    def high(self) -> float:
        return max(self.fx_a.high, self.fx_b.high)

    @property
    def low(self) -> float:
        return min(self.fx_a.low, self.fx_b.low)

    @property
    def length(self) -> int:
        """构成笔的无包含 K 线数量。"""
        return len(self.bars)

    @property
    def power(self) -> float:
        return round(abs(self.end_value - self.start_value), 2)

    @property
    def change(self) -> float:
        if self.start_value == 0:
            return 0.0
        return round((self.end_value - self.start_value) / self.start_value, 4)

    @property
    def source_start(self) -> datetime:
        return self.bars[0].first_dt

    @property
    def source_end(self) -> datetime:
        return self.bars[-1].last_dt

    @property
    def raw_bars(self) -> tuple[RawBar, ...]:
        """与 CZSC BI.raw_bars 一致：不包含首尾两根无包含 K。"""
        values: list[RawBar] = []
        for bar in self.bars[1:-1]:
            values.extend(bar.elements)
        return tuple(values)


@dataclass(frozen=True, slots=True)
class Segment:
    """由连续奇数笔构成的一条线段。"""

    symbol: str
    fx_a: Fractal
    fx_b: Fractal
    direction: StrokeDirection
    strokes: tuple[Stroke, ...]
    index: int = -1

    @property
    def start_dt(self) -> datetime:
        return self.fx_a.dt

    @property
    def end_dt(self) -> datetime:
        return self.fx_b.dt

    @property
    def start_value(self) -> float:
        return self.fx_a.value

    @property
    def end_value(self) -> float:
        return self.fx_b.value

    @property
    def stroke_count(self) -> int:
        return len(self.strokes)

    @property
    def high(self) -> float:
        """线段价格区间上沿，以两个真实端点价格计算。"""
        return max(self.start_value, self.end_value)

    @property
    def low(self) -> float:
        """线段价格区间下沿，以两个真实端点价格计算。"""
        return min(self.start_value, self.end_value)

    @property
    def power(self) -> float:
        return round(abs(self.end_value - self.start_value), 2)

    @property
    def change(self) -> float:
        if self.start_value == 0:
            return 0.0
        return round((self.end_value - self.start_value) / self.start_value, 4)

    @property
    def source_start(self) -> datetime:
        return self.strokes[0].source_start

    @property
    def source_end(self) -> datetime:
        return self.strokes[-1].source_end

    @property
    def raw_bars(self) -> tuple[RawBar, ...]:
        values: list[RawBar] = []
        for stroke in self.strokes:
            values.extend(stroke.raw_bars)
        return unique_elements(values)

    @property
    def raw_bar_count(self) -> int:
        return len(self.raw_bars)

    @property
    def volume(self) -> float:
        return float(sum(x.volume for x in self.raw_bars))


@dataclass(frozen=True, slots=True)
class FeatureElement:
    """标准特征序列中的一个元素。

    一个元素由一根或多根同方向笔经过包含关系合并而成。``high`` / ``low``
    是按当前待识别线段方向处理包含后的区间，而不是简单的全体最高最低。
    """

    symbol: str
    segment_direction: StrokeDirection
    merge_direction: StrokeDirection
    strokes: tuple[Stroke, ...]
    stroke_positions: tuple[int, ...]
    high: float
    low: float
    sequence_start_position: int
    element_index: int

    def __post_init__(self) -> None:
        if not self.strokes or len(self.strokes) != len(self.stroke_positions):
            raise ValueError("特征元素必须包含数量一致的笔与位置")
        if self.high < self.low:
            raise ValueError("特征元素 high 不能小于 low")

    @property
    def feature_direction(self) -> StrokeDirection:
        return (
            StrokeDirection.DOWN
            if self.segment_direction is StrokeDirection.UP
            else StrokeDirection.UP
        )

    @property
    def start_dt(self) -> datetime:
        return self.strokes[0].start_dt

    @property
    def end_dt(self) -> datetime:
        return self.strokes[-1].end_dt

    @property
    def first_stroke_position(self) -> int:
        return self.stroke_positions[0]

    @property
    def last_stroke_position(self) -> int:
        return self.stroke_positions[-1]


@dataclass(frozen=True, slots=True)
class FeatureFractal:
    """标准特征序列上的顶/底分型。"""

    symbol: str
    segment_direction: StrokeDirection
    mark: FractalMark
    left: FeatureElement
    middle: FeatureElement
    right: FeatureElement
    endpoint: Fractal
    endpoint_position: int
    gap: bool
    break_status: FeatureBreakStatus
    detected_at_position: int

    @property
    def actual_break(self) -> bool:
        return self.break_status is FeatureBreakStatus.CONFIRMED

    @property
    def dt(self) -> datetime:
        return self.endpoint.dt

    @property
    def value(self) -> float:
        return self.endpoint.value

    @property
    def label(self) -> str:
        return self.mark.label


@dataclass(frozen=True, slots=True)
class SegmentEvidence:
    """一条已确认线段的数据层确认依据。

    ``gap_origin_fractal`` 记录进入“有缺口等待反向确认”状态时的首个主
    特征分型。等待期间端点可能被后续更高顶或更低底迁移；当最终极值尚未
    形成新的完整主特征分型时，``primary_fractal`` 仍保留最近可审计的主
    分型，``final_endpoint`` 则明确记录线段实际采用的最终端点。
    """

    segment_index: int
    start_position: int
    end_position: int
    confirmation: str
    primary_fractal: FeatureFractal
    reverse_fractal: FeatureFractal | None = None
    gap_origin_fractal: FeatureFractal | None = None
    final_endpoint: Fractal | None = None
    # 线段真正进入正式提交账本的时间。它与线段端点时间、特征序列确认笔
    # 时间是三个不同概念；实时通知与无未来函数回测必须使用该字段。
    committed_at: datetime | None = None
    # 当前分析输入中的原始 K 线零基位置。持久化到外部系统时应同时保存
    # committed_at；窗口切换后该位置只用于本次运行内审计。
    committed_at_bar_position: int | None = None

    @property
    def confirmed_at_position(self) -> int:
        if self.reverse_fractal is not None:
            return self.reverse_fractal.detected_at_position
        return self.primary_fractal.detected_at_position

    @property
    def is_committed(self) -> bool:
        return self.committed_at is not None


@dataclass(frozen=True, slots=True)
class CentralZone:
    """由连续笔构成的 CZSC 笔中枢。"""

    symbol: str
    strokes: tuple[Stroke, ...]
    index: int = -1
    group_index: int = -1

    def __post_init__(self) -> None:
        if not self.strokes:
            raise ValueError("中枢至少需要一笔作为分组输入")

    @property
    def sdt(self) -> datetime:
        return self.strokes[0].start_dt

    @property
    def edt(self) -> datetime:
        return self.strokes[-1].end_dt

    @property
    def sdir(self) -> StrokeDirection:
        return self.strokes[0].direction

    @property
    def edir(self) -> StrokeDirection:
        return self.strokes[-1].direction

    @property
    def stroke_count(self) -> int:
        return len(self.strokes)

    @property
    def zg(self) -> float:
        return min(x.high for x in self.strokes[:3])

    @property
    def zd(self) -> float:
        return max(x.low for x in self.strokes[:3])

    @property
    def zz(self) -> float:
        return self.zd + (self.zg - self.zd) * 0.5

    @property
    def gg(self) -> float:
        return max(x.high for x in self.strokes)

    @property
    def dd(self) -> float:
        return min(x.low for x in self.strokes)

    @property
    def departure_stroke(self) -> Stroke | None:
        """中枢尾部已经完成的离开笔；它不属于 GG/DD 趋势比较的盘整本体。"""
        last = self.strokes[-1]
        if last.end_value < self.zd or last.end_value > self.zg:
            return last
        return None

    @property
    def trend_strokes(self) -> tuple[Stroke, ...]:
        """用于同级别中枢 GG/DD 关系的盘整本体，不包含最终离开笔。"""
        if self.departure_stroke is not None:
            return self.strokes[:-1]
        return self.strokes

    @property
    def trend_gg(self) -> float:
        return max(x.high for x in self.trend_strokes)

    @property
    def trend_dd(self) -> float:
        return min(x.low for x in self.trend_strokes)

    @property
    def source_start(self) -> datetime:
        return self.strokes[0].source_start

    @property
    def source_end(self) -> datetime:
        return self.strokes[-1].source_end

    @property
    def is_valid(self) -> bool:
        if self.stroke_count < 3 or self.zg < self.zd:
            return False
        for stroke in self.strokes:
            high_in_range = self.zd <= stroke.high <= self.zg
            low_in_range = self.zd <= stroke.low <= self.zg
            contains_range = stroke.high >= self.zg and stroke.low <= self.zd
            if not (high_in_range or low_in_range or contains_range):
                return False
        return True


@dataclass(frozen=True, slots=True)
class SegmentCentralZone:
    """由至少三个连续已确认线段重叠形成的线段中枢。

    中枢区间 ``[ZD, ZG]`` 固定由起始三个连续线段的价格区间交集确定；
    后续线段只要仍与该固定区间相交，就属于同一个中枢延伸。
    """

    symbol: str
    segments: tuple[Segment, ...]
    index: int = -1
    start_position: int = -1
    end_position: int = -1

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("线段中枢至少需要一个线段输入")
        if self.start_position >= 0 and self.end_position >= 0:
            if self.end_position - self.start_position + 1 != len(self.segments):
                raise ValueError("线段中枢位置范围与内部线段数量不一致")

    @property
    def sdt(self) -> datetime:
        return self.segments[0].start_dt

    @property
    def edt(self) -> datetime:
        return self.segments[-1].end_dt

    @property
    def sdir(self) -> StrokeDirection:
        return self.segments[0].direction

    @property
    def edir(self) -> StrokeDirection:
        return self.segments[-1].direction

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def zg(self) -> float:
        return min(x.high for x in self.segments[:3])

    @property
    def zd(self) -> float:
        return max(x.low for x in self.segments[:3])

    @property
    def zz(self) -> float:
        return self.zd + (self.zg - self.zd) * 0.5

    @property
    def gg(self) -> float:
        return max(x.high for x in self.segments)

    @property
    def dd(self) -> float:
        return min(x.low for x in self.segments)

    @property
    def departure_segment(self) -> Segment | None:
        """中枢尾部已经完成的离开线段。

        线段为连续走势，最终离开段必然在起点处与固定中枢区间相交，因此
        扫描器会把它保留在中枢切片尾部。趋势 GG/DD 不能把这条 A/C 连接段
        当作中枢盘整本体，否则相邻中枢会因连续端点而被系统性误判为重叠。
        """
        last = self.segments[-1]
        if last.end_value < self.zd or last.end_value > self.zg:
            return last
        return None

    @property
    def trend_segments(self) -> tuple[Segment, ...]:
        """用于严格趋势关系的中枢盘整本体，不包含最终离开线段。"""
        if self.departure_segment is not None:
            return self.segments[:-1]
        return self.segments

    @property
    def trend_gg(self) -> float:
        return max(x.high for x in self.trend_segments)

    @property
    def trend_dd(self) -> float:
        return min(x.low for x in self.trend_segments)

    @property
    def source_start(self) -> datetime:
        return self.segments[0].source_start

    @property
    def source_end(self) -> datetime:
        return self.segments[-1].source_end

    @property
    def is_valid(self) -> bool:
        if self.segment_count < 3 or self.zg < self.zd:
            return False
        return all(
            segment.high >= self.zd and segment.low <= self.zg
            for segment in self.segments
        )


@dataclass(frozen=True, slots=True)
class TradingPoint:
    """按明确级别递归关系确认的一、二、三类买卖点。

    ``dt`` / ``price`` 是走势端点发生位置；``confirmed_at_dt`` 是结构数据
    足以确认该信号的时间。历史图上标记前者，后台提醒必须使用后者。
    ``source_level`` 记录本项目的操作级别，目前正式输出为 ``segment``。
    """

    symbol: str
    point_type: TradingPointType
    dt: datetime
    price: float
    segment_index: int
    confirmed_at_dt: datetime
    evidence_kind: str
    evidence: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    zone_index: int | None = None
    related_segment_indexes: tuple[int, ...] = field(default_factory=tuple)
    source_level: str = "segment"

    @property
    def label(self) -> str:
        return self.point_type.label

    @property
    def is_buy(self) -> bool:
        return self.point_type.is_buy

    @property
    def evidence_dict(self) -> dict[str, str]:
        return dict(self.evidence)


@dataclass(frozen=True, slots=True)
class TrendDivergence:
    """一类买卖点所依据的完整趋势与 MACD 背驰证据。"""

    symbol: str
    level: str
    direction: StrokeDirection
    previous_zone_index: int
    last_zone_index: int
    entry_unit_index: int
    exit_unit_index: int
    entry_macd_area: float
    exit_macd_area: float
    entry_power: float
    exit_power: float
    entry_start_dt: datetime
    entry_end_dt: datetime
    exit_start_dt: datetime
    exit_end_dt: datetime
    price_extreme: bool
    macd_divergence: bool
    # True 表示 MACD 由真实历史起点递推，或由持久化 MacdAnchor 无缝恢复。
    # 有限窗口自行用首价初始化只能作为候选证据，不能生成正式一买/一卖。
    macd_state_exact: bool = True
    strict_trend: bool = True
    # 操作级别 c 内部必须已经形成对最后中枢 B 的次级别三类点，并至少
    # 包含两个次级别中枢；stroke 是当前最低建模级别，只能以完成笔为下限。
    sublevel_third_point: bool = True
    sublevel_zone_count: int = 0

    @property
    def is_valid(self) -> bool:
        return (
            self.strict_trend
            and self.price_extreme
            and self.macd_divergence
            and self.macd_state_exact
            and self.sublevel_third_point
            and self.sublevel_zone_count >= (0 if self.level == "stroke" else 2)
        )


@dataclass(frozen=True, slots=True)
class TradingPointCandidate:
    """买卖点候选的逐条件审计记录。"""

    point_type: TradingPointType
    status: TradingPointStatus
    dt: datetime | None
    price: float | None
    segment_index: int | None
    reason: str
    checks: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    zone_index: int | None = None
    related_segment_indexes: tuple[int, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return self.point_type.label


@dataclass(frozen=True, slots=True)
class TradingPointDiagnostic:
    code: str
    message: str
    dt: datetime | None = None


@dataclass(frozen=True, slots=True)
class SegmentCentralZoneDiagnostic:
    code: str
    message: str
    dt: datetime | None = None


@dataclass(frozen=True, slots=True)
class CentralZoneDiagnostic:
    code: str
    message: str
    dt: datetime | None = None


@dataclass(frozen=True, slots=True)
class SegmentDiagnostic:
    code: str
    message: str
    dt: datetime | None = None


@dataclass(frozen=True, slots=True)
class FractalDiagnostic:
    code: str
    message: str
    dt: datetime | None = None


@dataclass(frozen=True, slots=True)
class StrokeDiagnostic:
    code: str
    message: str
    dt: datetime | None = None


def unique_elements(elements: Iterable[RawBar]) -> tuple[RawBar, ...]:
    """按开盘时间去重并保持时间顺序。"""
    by_dt = {x.open_time: x for x in elements}
    return tuple(by_dt[dt] for dt in sorted(by_dt))


def _hours(value: int):
    from datetime import timedelta

    return timedelta(hours=value)
