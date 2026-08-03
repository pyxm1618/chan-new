from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .binance import BinanceKlineSnapshot
from .engine import AnalysisResult, StructureAnchor, analyze_bars
from .metadata import AnalysisMetadata
from .models import FractalMark, RawBar, Segment, Stroke, StrokeDirection
from .segments import SegmentMode


_REFRESH_SECONDS = {
    "1m": 10,
    "3m": 20,
    "5m": 30,
    "15m": 60,
    "30m": 90,
    "1h": 120,
    "2h": 180,
    "4h": 300,
    "6h": 300,
    "8h": 300,
    "12h": 300,
    "1d": 600,
    "3d": 900,
    "1w": 1800,
    "1M": 1800,
}


def recommended_refresh_seconds(interval: str) -> int:
    """返回 UI 重绘频率，而不是 Binance 推送频率。

    低周期保证每根 K 至少有多次可见更新；高周期降低无意义重算和 API 请求。
    """
    if interval not in _REFRESH_SECONDS:
        raise ValueError(f"不支持的刷新周期：{interval}")
    return _REFRESH_SECONDS[interval]


@dataclass(frozen=True, slots=True)
class ProvisionalLine:
    structure: str
    direction: StrokeDirection
    start_dt: datetime
    start_value: float
    end_dt: datetime
    end_value: float
    reason: str
    source_indexes: tuple[int, ...] = ()

    @property
    def label(self) -> str:
        return "未确认笔" if self.structure == "stroke" else "未确认线段"


@dataclass(frozen=True, slots=True)
class LiveStructureOverlay:
    snapshot: BinanceKlineSnapshot | None
    live_result: AnalysisResult
    provisional_strokes: tuple[ProvisionalLine, ...]
    provisional_segments: tuple[ProvisionalLine, ...]
    stroke_common_prefix: int
    segment_common_prefix: int
    computed_at: datetime

    @property
    def current_bar(self) -> RawBar | None:
        return self.snapshot.current_bar if self.snapshot else None

    @property
    def display_raw_bars(self) -> tuple[RawBar, ...]:
        if self.snapshot is None:
            return self.live_result.raw_bars
        return self.snapshot.all_bars


@dataclass(frozen=True, slots=True)
class LiveAnalysisBundle:
    confirmed: AnalysisResult
    overlay: LiveStructureOverlay

    @property
    def snapshot(self) -> BinanceKlineSnapshot | None:
        return self.overlay.snapshot


def analyze_snapshot(
    snapshot: BinanceKlineSnapshot,
    *,
    czsc_compatibility: bool,
    min_bi_len: int,
    metadata: AnalysisMetadata,
    segment_mode: SegmentMode,
    left_boundary_anchored: bool = False,
    left_anchor: StructureAnchor | None = None,
    previous: LiveAnalysisBundle | None = None,
) -> LiveAnalysisBundle:
    """已收盘数据与实时数据分层计算，杜绝当前 K 污染已确认结构。"""
    if (
        previous
        and previous.snapshot
        and previous.snapshot.closed_signature == snapshot.closed_signature
        and previous.confirmed.left_boundary_anchored == left_boundary_anchored
        and previous.confirmed.left_anchor == left_anchor
    ):
        confirmed = previous.confirmed
    else:
        confirmed = analyze_bars(
            snapshot.closed_bars,
            czsc_compatibility=czsc_compatibility,
            min_bi_len=min_bi_len,
            metadata=metadata,
            segment_mode=segment_mode,
            left_boundary_anchored=left_boundary_anchored,
            left_anchor=left_anchor,
        )
    live_result = analyze_bars(
        snapshot.all_bars,
        czsc_compatibility=czsc_compatibility,
        min_bi_len=min_bi_len,
        metadata=metadata,
        segment_mode=segment_mode,
        left_boundary_anchored=left_boundary_anchored,
        left_anchor=left_anchor,
    )
    overlay = build_live_overlay(confirmed, live_result, snapshot=snapshot)
    return LiveAnalysisBundle(confirmed=confirmed, overlay=overlay)


def analyze_static(
    bars: Sequence[RawBar],
    *,
    czsc_compatibility: bool,
    min_bi_len: int,
    metadata: AnalysisMetadata,
    segment_mode: SegmentMode,
    left_boundary_anchored: bool = False,
    left_anchor: StructureAnchor | None = None,
) -> LiveAnalysisBundle:
    result = analyze_bars(
        bars,
        czsc_compatibility=czsc_compatibility,
        min_bi_len=min_bi_len,
        metadata=metadata,
        segment_mode=segment_mode,
        left_boundary_anchored=left_boundary_anchored,
        left_anchor=left_anchor,
    )
    return LiveAnalysisBundle(
        confirmed=result,
        overlay=build_live_overlay(result, result, snapshot=None),
    )


def build_live_overlay(
    confirmed: AnalysisResult,
    live: AnalysisResult,
    *,
    snapshot: BinanceKlineSnapshot | None,
) -> LiveStructureOverlay:
    """构造统一的候选尾部图层。

    ``confirmed`` 中的 ``resolved_strokes`` / ``segments`` 是正式账本。正式
    区间左侧可能存在冷启动未解析前缀，右侧可能存在可回撤尾部；两侧都必须
    画成候选虚线，不能假设正式结构一定从数组第 0 项开始。
    """
    if not confirmed.left_boundary_resolved:
        stroke_start = stroke_end = 0
        provisional_strokes: list[ProvisionalLine] = [
            _stroke_as_line(
                x,
                "窗口左边界缺少真实历史起点或持久化锚点，全部笔仅作候选",
            )
            for x in live.strokes
        ]
    else:
        stroke_block = _find_contiguous_block(
            confirmed.resolved_strokes,
            live.strokes,
            _stroke_signature,
        )
        if stroke_block is None:
            stroke_start = stroke_end = 0
        else:
            stroke_start, stroke_end = stroke_block
        provisional_strokes = [
            _stroke_as_line(x, "窗口左边界位于持久化锚点之前，尚不能作为正式结构")
            for x in live.strokes[:stroke_start]
        ]
        provisional_strokes.extend(
            _stroke_as_line(x, "尚未进入稳定提交区，后续 K 仍可能使其迁移或撤销")
            for x in live.strokes[stroke_end:]
        )
    projection = _project_next_stroke(live)
    if projection is not None and not _same_line_as_last(provisional_strokes, projection):
        provisional_strokes.append(projection)

    if not confirmed.left_boundary_resolved:
        segment_start = segment_end = 0
        provisional_segments: list[ProvisionalLine] = [
            _segment_as_line(
                x,
                "窗口左边界缺少真实历史起点或持久化锚点，全部线段仅作候选",
            )
            for x in live.detected_segments
        ]
    else:
        segment_block = _find_contiguous_block(
            confirmed.segments,
            live.detected_segments,
            _segment_signature,
        )
        if segment_block is None:
            segment_start = segment_end = 0
        else:
            segment_start, segment_end = segment_block
        provisional_segments = [
            _segment_as_line(x, "位于持久化锚点之前，无法作为本窗口正式线段")
            for x in live.detected_segments[:segment_start]
        ]
        provisional_segments.extend(
            _segment_as_line(x, "已检测但尚未由下一线段推进为 COMMITTED")
            for x in live.detected_segments[segment_end:]
        )
    segment_projection = _project_next_segment(live, provisional_strokes)
    if segment_projection is not None and not _same_line_as_last(provisional_segments, segment_projection):
        provisional_segments.append(segment_projection)

    return LiveStructureOverlay(
        snapshot=snapshot,
        live_result=live,
        provisional_strokes=tuple(provisional_strokes),
        provisional_segments=tuple(provisional_segments),
        stroke_common_prefix=(stroke_end - stroke_start),
        segment_common_prefix=(segment_end - segment_start),
        computed_at=(snapshot.fetched_at if snapshot else datetime.now(timezone.utc)),
    )


def _project_next_stroke(result: AnalysisResult) -> ProvisionalLine | None:
    if not result.strokes:
        return None
    last = result.strokes[-1]
    start_dt = last.end_dt
    start_value = last.end_value
    direction = _opposite(last.direction)
    bars = [x for x in result.merged_bars if x.dt > start_dt]
    if not bars:
        return None
    if direction is StrokeDirection.UP:
        target = max(bars, key=lambda x: (x.high, x.dt))
        end_value = target.high
    else:
        target = min(bars, key=lambda x: (x.low, -x.dt.timestamp()))
        end_value = target.low
    if target.dt <= start_dt or abs(end_value - start_value) <= 1e-12:
        return None
    return ProvisionalLine(
        structure="stroke",
        direction=direction,
        start_dt=start_dt,
        start_value=start_value,
        end_dt=target.dt,
        end_value=end_value,
        reason="尚未形成满足分型与最小笔长的终点，连接到当前未完成区的最极端价",
        source_indexes=tuple(x.index for x in result.strokes[-1:]),
    )


def _project_next_segment(
    result: AnalysisResult,
    provisional_strokes: Sequence[ProvisionalLine],
) -> ProvisionalLine | None:
    if result.segments:
        last = result.segments[-1]
        start_dt = last.end_dt
        start_value = last.end_value
        direction = _opposite(last.direction)
        source_strokes = [x for x in result.strokes if x.end_dt > start_dt]
    elif result.unfinished_segment_strokes:
        first = result.unfinished_segment_strokes[0]
        start_dt = first.start_dt
        start_value = first.start_value
        direction = first.direction
        source_strokes = list(result.unfinished_segment_strokes)
    else:
        return None

    endpoint_mark = FractalMark.TOP if direction is StrokeDirection.UP else FractalMark.BOTTOM
    candidates = [x.fx_b for x in source_strokes if x.fx_b.mark is endpoint_mark and x.end_dt > start_dt]
    for item in provisional_strokes:
        if item.end_dt <= start_dt or item.direction is not direction:
            continue
        candidates.append(_LightEndpoint(item.end_dt, item.end_value, endpoint_mark))
    if not candidates:
        return None
    if direction is StrokeDirection.UP:
        target = max(candidates, key=lambda x: (x.value, x.dt))
    else:
        target = min(candidates, key=lambda x: (x.value, -x.dt.timestamp()))
    if target.dt <= start_dt or abs(target.value - start_value) <= 1e-12:
        return None
    return ProvisionalLine(
        structure="segment",
        direction=direction,
        start_dt=start_dt,
        start_value=start_value,
        end_dt=target.dt,
        end_value=target.value,
        reason=(
            f"标准特征序列尚未完成确认；当前未完成区包含 {len(source_strokes)} 笔，"
            "虚线仅表示候选方向与当前极值"
        ),
        source_indexes=tuple(x.index for x in source_strokes),
    )


@dataclass(frozen=True, slots=True)
class _LightEndpoint:
    dt: datetime
    value: float
    mark: FractalMark


def _common_prefix(a: Sequence, b: Sequence, signature) -> int:
    count = 0
    for left, right in zip(a, b):
        if signature(left) != signature(right):
            break
        count += 1
    return count


def _find_contiguous_block(
    needle: Sequence,
    haystack: Sequence,
    signature,
) -> tuple[int, int] | None:
    """在候选链中定位正式结构块；正式块可能位于左未解析前缀之后。"""
    left = tuple(signature(x) for x in needle)
    right = tuple(signature(x) for x in haystack)
    if not left:
        return (0, 0)
    width = len(left)
    for start in range(len(right) - width + 1):
        if right[start : start + width] == left:
            return start, start + width
    return None


def _stroke_signature(value: Stroke) -> tuple:
    return (
        value.direction,
        value.start_dt,
        round(value.start_value, 12),
        value.end_dt,
        round(value.end_value, 12),
    )


def _segment_signature(value: Segment) -> tuple:
    return (
        value.direction,
        value.start_dt,
        round(value.start_value, 12),
        value.end_dt,
        round(value.end_value, 12),
        value.stroke_count,
    )


def _stroke_as_line(value: Stroke, reason: str) -> ProvisionalLine:
    return ProvisionalLine(
        structure="stroke",
        direction=value.direction,
        start_dt=value.start_dt,
        start_value=value.start_value,
        end_dt=value.end_dt,
        end_value=value.end_value,
        reason=reason,
        source_indexes=(value.index,),
    )


def _segment_as_line(value: Segment, reason: str) -> ProvisionalLine:
    return ProvisionalLine(
        structure="segment",
        direction=value.direction,
        start_dt=value.start_dt,
        start_value=value.start_value,
        end_dt=value.end_dt,
        end_value=value.end_value,
        reason=reason,
        source_indexes=tuple(x.index for x in value.strokes),
    )


def _same_line_as_last(values: Sequence[ProvisionalLine], item: ProvisionalLine) -> bool:
    if not values:
        return False
    last = values[-1]
    return (
        last.direction is item.direction
        and last.start_dt == item.start_dt
        and last.end_dt == item.end_dt
        and abs(last.start_value - item.start_value) <= 1e-12
        and abs(last.end_value - item.end_value) <= 1e-12
    )


def _opposite(direction: StrokeDirection) -> StrokeDirection:
    return StrokeDirection.DOWN if direction is StrokeDirection.UP else StrokeDirection.UP
