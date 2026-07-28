from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .models import (
    Fractal,
    FractalMark,
    MergedBar,
    Segment,
    SegmentDiagnostic,
    Stroke,
    StrokeDirection,
)


class SegmentMode(str, Enum):
    """CZSC 0.3.9 线段确认模式。"""

    STRICT = "strict"
    LOOSE = "loose"

    @property
    def label(self) -> str:
        return "严格" if self is SegmentMode.STRICT else "宽松"


@dataclass(frozen=True, slots=True)
class SegmentDetectionResult:
    segments: tuple[Segment, ...]
    markers: tuple[Fractal, ...]
    candidates: tuple[Fractal, ...]
    unfinished_strokes: tuple[Stroke, ...]
    diagnostics: tuple[SegmentDiagnostic, ...]
    mode: SegmentMode


def stroke_endpoints(strokes: Sequence[Stroke]) -> tuple[Fractal, ...]:
    """把连续笔链转换为端点序列；N 笔对应 N+1 个端点。"""
    if not strokes:
        return ()
    points = [strokes[0].fx_a]
    for i, stroke in enumerate(strokes):
        if i and (
            strokes[i - 1].end_dt != stroke.start_dt
            or strokes[i - 1].end_value != stroke.start_value
            or strokes[i - 1].fx_b.mark is not stroke.fx_a.mark
        ):
            raise ValueError(f"第 {i - 1}、{i} 笔没有共享同一端点，不能识别线段")
        points.append(stroke.fx_b)
    return tuple(points)


def detect_segments(
    strokes: Sequence[Stroke],
    *,
    latest_bar: MergedBar | None = None,
    mode: SegmentMode | str = SegmentMode.STRICT,
    handle_last: bool = True,
) -> SegmentDetectionResult:
    """从已确认笔端点识别线段。

    规则复刻 CZSC 0.3.9 ``KlineAnalyze._find_xd``：

    1. 顶端点与底端点分别按同类序列做三点滑窗；中间顶为局部最高、
       中间底为局部最低时，成为潜在线段端点；
    2. 潜在端点按时间合并；连续同类端点只保留更高顶或更低底；
    3. 相反端点之间至少包含 3 笔；
    4. 恰好 3 笔时，宽松模式只要求终点突破同类前高/前低；严格模式还要求
       终点后一笔提供反向确认；
    5. 最新无包含 K 若突破最后线段端点，则撤销该端点。

    这里使用本项目已校正的笔链作为输入，从而把“找笔”和“找线段”两层验证隔离。
    """
    mode = SegmentMode(mode)
    endpoints = stroke_endpoints(strokes)
    if len(endpoints) < 3:
        return SegmentDetectionResult((), (), (), tuple(strokes), (), mode)

    candidates = sorted(
        [*_extract_potential(endpoints, FractalMark.BOTTOM), *_extract_potential(endpoints, FractalMark.TOP)],
        key=lambda x: x.dt,
    )
    markers: list[Fractal] = []
    diagnostics: list[SegmentDiagnostic] = []
    endpoint_index = {point.dt: i for i, point in enumerate(endpoints)}

    for point in candidates:
        if not markers:
            markers.append(point)
            continue

        previous = markers[-1]
        if previous.mark is point.mark:
            if _is_more_extreme(point, previous):
                diagnostics.append(
                    SegmentDiagnostic(
                        code="SAME_MARK_REPLACED",
                        message=(
                            f"连续{point.label}候选只保留更极端端点："
                            f"{previous.value:.12g} ({previous.dt.isoformat()}) -> "
                            f"{point.value:.12g} ({point.dt.isoformat()})"
                        ),
                        dt=point.dt,
                    )
                )
                markers[-1] = point
            continue

        # 相邻顶底必须保持顶价高于底价；不满足时，旧候选端点失效。
        if (previous.mark is FractalMark.TOP and point.value >= previous.value) or (
            previous.mark is FractalMark.BOTTOM and point.value <= previous.value
        ):
            removed = markers.pop()
            diagnostics.append(
                SegmentDiagnostic(
                    code="PRICE_ORDER_INVALIDATED",
                    message=(
                        f"{removed.label} {removed.value:.12g} 与后续{point.label} "
                        f"{point.value:.12g} 价格次序无效，撤销旧候选"
                    ),
                    dt=point.dt,
                )
            )
            continue

        start_index = endpoint_index[previous.dt]
        end_index = endpoint_index[point.dt]
        segment_points = endpoints[start_index : end_index + 1]
        right_points = endpoints[end_index:]
        # 4 个笔端点即 3 笔。
        if len(segment_points) < 4:
            continue

        if len(segment_points) == 4:
            if mode is SegmentMode.LOOSE:
                confirmed = _three_stroke_breakout(point, segment_points)
            else:
                confirmed = _strict_three_stroke_confirmation(point, segment_points, right_points)
            if not confirmed:
                continue

        markers.append(point)

    if handle_last and markers and latest_bar is not None:
        last = markers[-1]
        broken = (
            last.mark is FractalMark.BOTTOM and latest_bar.low < last.value
        ) or (
            last.mark is FractalMark.TOP and latest_bar.high > last.value
        )
        if broken:
            markers.pop()
            diagnostics.append(
                SegmentDiagnostic(
                    code="LAST_SEGMENT_MARKER_INVALIDATED",
                    message=(
                        f"最新无包含 K ({latest_bar.dt.isoformat()}) 突破最后{last.label} "
                        f"{last.value:.12g}，撤销该线段端点"
                    ),
                    dt=latest_bar.dt,
                )
            )

    segments = _build_segments(strokes, endpoints, markers)
    if segments:
        last_end_index = endpoint_index[segments[-1].fx_b.dt]
        unfinished = tuple(strokes[last_end_index:])
    else:
        unfinished = tuple(strokes)

    return SegmentDetectionResult(
        segments=tuple(segments),
        markers=tuple(markers),
        candidates=tuple(candidates),
        unfinished_strokes=unfinished,
        diagnostics=tuple(diagnostics),
        mode=mode,
    )


def validate_segment_chain(
    segments: Sequence[Segment],
    strokes: Sequence[Stroke],
    *,
    mode: SegmentMode | str = SegmentMode.STRICT,
) -> tuple[SegmentDiagnostic, ...]:
    """验证线段的方向、共享端点、笔数与严格三笔确认条件。"""
    mode = SegmentMode(mode)
    issues: list[SegmentDiagnostic] = []
    if not segments:
        return ()

    endpoints = stroke_endpoints(strokes)
    endpoint_index = {point.dt: i for i, point in enumerate(endpoints)}
    stroke_by_span = {(x.start_dt, x.end_dt): x for x in strokes}

    for i, segment in enumerate(segments):
        expected_marks = (
            (FractalMark.BOTTOM, FractalMark.TOP)
            if segment.direction is StrokeDirection.UP
            else (FractalMark.TOP, FractalMark.BOTTOM)
        )
        if (segment.fx_a.mark, segment.fx_b.mark) != expected_marks:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_DIRECTION_MARK_MISMATCH",
                    message=f"第 {i} 线段方向与起止端点类型不一致",
                    dt=segment.start_dt,
                )
            )

        if segment.stroke_count < 3 or segment.stroke_count % 2 == 0:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_STROKE_COUNT_INVALID",
                    message=f"第 {i} 线段包含 {segment.stroke_count} 笔，必须是大于等于 3 的奇数",
                    dt=segment.start_dt,
                )
            )

        start_index = endpoint_index.get(segment.start_dt)
        end_index = endpoint_index.get(segment.end_dt)
        if start_index is None or end_index is None or end_index <= start_index:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_ENDPOINT_NOT_IN_CHAIN",
                    message=f"第 {i} 线段端点不在笔端点序列中",
                    dt=segment.start_dt,
                )
            )
            continue

        expected_strokes = tuple(strokes[start_index:end_index])
        if tuple((x.start_dt, x.end_dt) for x in segment.strokes) != tuple(
            (x.start_dt, x.end_dt) for x in expected_strokes
        ):
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_STROKES_NOT_CONTIGUOUS",
                    message=f"第 {i} 线段内部笔不是原笔链的连续切片",
                    dt=segment.start_dt,
                )
            )

        if segment.strokes:
            first = stroke_by_span.get((segment.strokes[0].start_dt, segment.strokes[0].end_dt))
            last = stroke_by_span.get((segment.strokes[-1].start_dt, segment.strokes[-1].end_dt))
            if (
                first is None
                or last is None
                or not _same_endpoint(first.fx_a, segment.fx_a)
                or not _same_endpoint(last.fx_b, segment.fx_b)
            ):
                issues.append(
                    SegmentDiagnostic(
                        code="SEGMENT_ENDPOINT_STROKE_MISMATCH",
                        message=f"第 {i} 线段端点与首末笔不一致",
                        dt=segment.start_dt,
                    )
                )

        if mode is SegmentMode.STRICT and segment.stroke_count == 3:
            points = endpoints[start_index : end_index + 1]
            right = endpoints[end_index:]
            if not _strict_three_stroke_confirmation(segment.fx_b, points, right):
                issues.append(
                    SegmentDiagnostic(
                        code="STRICT_CONFIRMATION_MISSING",
                        message=f"第 {i} 三笔线段缺少严格模式所需的后一笔确认",
                        dt=segment.end_dt,
                    )
                )

        if i:
            previous = segments[i - 1]
            if previous.direction is segment.direction:
                issues.append(
                    SegmentDiagnostic(
                        code="SEGMENT_DIRECTION_NOT_ALTERNATING",
                        message=f"第 {i - 1}、{i} 线段方向未交替",
                        dt=segment.start_dt,
                    )
                )
            if (
                previous.end_dt != segment.start_dt
                or previous.end_value != segment.start_value
                or previous.fx_b.mark is not segment.fx_a.mark
            ):
                issues.append(
                    SegmentDiagnostic(
                        code="SEGMENT_ENDPOINT_NOT_SHARED",
                        message=f"第 {i - 1}、{i} 线段没有共享同一笔端点",
                        dt=segment.start_dt,
                    )
                )

    return tuple(issues)


def _extract_potential(endpoints: Sequence[Fractal], mark: FractalMark) -> list[Fractal]:
    same_mark = [point for point in endpoints if point.mark is mark]
    potentials: list[Fractal] = []
    for i in range(len(same_mark) - 2):
        left, middle, right = same_mark[i : i + 3]
        if mark is FractalMark.BOTTOM and left.value >= middle.value <= right.value:
            potentials.append(middle)
        elif mark is FractalMark.TOP and left.value <= middle.value >= right.value:
            potentials.append(middle)
    return potentials


def _is_more_extreme(current: Fractal, previous: Fractal) -> bool:
    if current.mark is FractalMark.TOP:
        return current.value > previous.value
    return current.value < previous.value


def _three_stroke_breakout(point: Fractal, segment_points: Sequence[Fractal]) -> bool:
    same_type_previous = segment_points[-3]
    if point.mark is FractalMark.TOP:
        return point.value > same_type_previous.value
    return point.value < same_type_previous.value


def _strict_three_stroke_confirmation(
    point: Fractal,
    segment_points: Sequence[Fractal],
    right_points: Sequence[Fractal],
) -> bool:
    if len(segment_points) != 4 or len(right_points) <= 1:
        return False
    left_opposite = segment_points[-2]
    right_opposite = right_points[1]
    if point.mark is FractalMark.TOP:
        return (
            left_opposite.value < right_opposite.value
            and point.value > segment_points[-3].value
        )
    return (
        left_opposite.value > right_opposite.value
        and point.value < segment_points[-3].value
    )


def _same_endpoint(a: Fractal, b: Fractal) -> bool:
    return (
        a.dt == b.dt
        and a.mark is b.mark
        and abs(a.value - b.value) <= 1e-9
    )


def _build_segments(
    strokes: Sequence[Stroke],
    endpoints: Sequence[Fractal],
    markers: Sequence[Fractal],
) -> list[Segment]:
    if len(markers) < 2:
        return []
    endpoint_index = {point.dt: i for i, point in enumerate(endpoints)}
    values: list[Segment] = []
    for index, (fx_a, fx_b) in enumerate(zip(markers, markers[1:])):
        start_index = endpoint_index[fx_a.dt]
        end_index = endpoint_index[fx_b.dt]
        segment_strokes = tuple(strokes[start_index:end_index])
        direction = (
            StrokeDirection.UP if fx_a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN
        )
        values.append(
            Segment(
                symbol=fx_a.symbol,
                fx_a=fx_a,
                fx_b=fx_b,
                direction=direction,
                strokes=segment_strokes,
                index=index,
            )
        )
    return values
