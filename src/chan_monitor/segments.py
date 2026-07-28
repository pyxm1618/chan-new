from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from .models import (
    FeatureBreakStatus,
    FeatureElement,
    FeatureFractal,
    Fractal,
    FractalMark,
    MergedBar,
    Segment,
    SegmentDiagnostic,
    SegmentEvidence,
    Stroke,
    StrokeDirection,
)

_EPS = 1e-12


class SegmentMode(str, Enum):
    """线段识别口径。

    v0.6 起仅保留缠论原文的标准特征序列算法。历史 ``strict`` / ``loose``
    配置仍可读取，但都会映射到同一算法，避免旧配置直接报错。
    """

    FEATURE_SEQUENCE = "feature_sequence"
    STRICT = "feature_sequence"
    LOOSE = "feature_sequence"

    @classmethod
    def _missing_(cls, value):
        if value in {"strict", "loose", "chan", "feature"}:
            return cls.FEATURE_SEQUENCE
        return None

    @property
    def label(self) -> str:
        return "标准特征序列"


class _Relation(str, Enum):
    COMBINE = "combine"
    INCLUDED = "included"
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class SegmentDetectionResult:
    segments: tuple[Segment, ...]
    markers: tuple[Fractal, ...]
    candidates: tuple[Fractal, ...]
    unfinished_strokes: tuple[Stroke, ...]
    unresolved_prefix_strokes: tuple[Stroke, ...]
    feature_elements: tuple[FeatureElement, ...]
    feature_fractals: tuple[FeatureFractal, ...]
    evidence: tuple[SegmentEvidence, ...]
    diagnostics: tuple[SegmentDiagnostic, ...]
    mode: SegmentMode


@dataclass(slots=True)
class _ScanOutcome:
    start_position: int
    end_position: int | None
    primary: FeatureFractal | None
    reverse: FeatureFractal | None
    confirmation: str | None
    confirmed_at_position: int | None
    elements: list[FeatureElement]
    fractals: list[FeatureFractal]
    diagnostics: list[SegmentDiagnostic]


class _FeatureDetector:
    """标准特征序列分型状态机。

    这里刻意保留假设线段端点两侧的特殊包含规则：第一元素包含第二元素时
    可以合并；第一元素被第二元素包含时不能合并。第三元素开始恢复普通包含
    处理。这一细节对应原文“假设转折点前后两元素不作包含处理”的要求。
    """

    def __init__(
        self,
        strokes: Sequence[Stroke],
        *,
        segment_direction: StrokeDirection,
        sequence_start_position: int,
        require_actual_break: bool = True,
    ) -> None:
        self.strokes = strokes
        self.segment_direction = segment_direction
        self.sequence_start_position = sequence_start_position
        self.require_actual_break = require_actual_break
        self.feature_direction = _opposite(segment_direction)
        self.raw_positions: list[int] = []
        self.elements: list[FeatureElement] = []
        self.audit_elements: list[FeatureElement] = []
        self.audit_fractals: list[FeatureFractal] = []
        self._next_element_index = 0

    def add_position(self, position: int) -> FeatureFractal | None:
        stroke = self.strokes[position]
        if stroke.direction is not self.feature_direction:
            return None
        self.raw_positions.append(position)
        return self._consume(position)

    def _consume(self, position: int) -> FeatureFractal | None:
        stroke = self.strokes[position]
        if not self.elements:
            self.elements.append(self._new_element(position, self.segment_direction))
            return None

        if len(self.elements) == 1:
            first = self.elements[0]
            relation = _relation(first.high, first.low, stroke.high, stroke.low, exclude_included=True)
            if relation is _Relation.COMBINE:
                self.elements[0] = self._merge(first, position)
                return None

            # INCLUDED 表示第一元素被新元素包含。跨越假设分界点时禁止合并，
            # 因而与普通 UP / DOWN 一样独立成为第二元素。
            second = self._new_element(position, self.segment_direction)
            self.elements.append(second)
            if (
                self.segment_direction is StrokeDirection.UP
                and second.high < first.high - _EPS
            ) or (
                self.segment_direction is StrokeDirection.DOWN
                and second.low > first.low + _EPS
            ):
                return self._reset_and_replay()
            return None

        if len(self.elements) != 2:  # pragma: no cover - 状态机防御
            raise RuntimeError("标准特征序列状态异常：元素数量超过 2 后仍继续追加")

        middle = self.elements[1]
        allow_equal = 1 if self.feature_direction is StrokeDirection.DOWN else -1
        relation = _relation(
            middle.high,
            middle.low,
            stroke.high,
            stroke.low,
            exclude_included=False,
            allow_top_equal=allow_equal,
        )
        if relation is _Relation.COMBINE:
            self.elements[1] = self._merge(middle, position)
            return None
        if relation is _Relation.INCLUDED:  # exclude_included=False 不会出现
            relation = self.segment_direction

        right = self._new_element(position, _relation_direction(relation))
        self.elements.append(right)
        fractal = self._build_target_fractal()
        if fractal is not None:
            self.audit_fractals.append(fractal)
            return fractal
        return self._reset_and_replay()

    def _reset_and_replay(self) -> FeatureFractal | None:
        remaining = list(self.raw_positions[1:])
        self.raw_positions = []
        self.elements = []
        for position in remaining:
            self.raw_positions.append(position)
            value = self._consume(position)
            if value is not None:
                return value
        return None

    def _new_element(
        self, position: int, merge_direction: StrokeDirection
    ) -> FeatureElement:
        stroke = self.strokes[position]
        value = FeatureElement(
            symbol=stroke.symbol,
            segment_direction=self.segment_direction,
            merge_direction=merge_direction,
            strokes=(stroke,),
            stroke_positions=(position,),
            high=stroke.high,
            low=stroke.low,
            sequence_start_position=self.sequence_start_position,
            element_index=self._next_element_index,
        )
        self._next_element_index += 1
        self.audit_elements.append(value)
        return value

    def _merge(self, element: FeatureElement, position: int) -> FeatureElement:
        stroke = self.strokes[position]
        if element.merge_direction is StrokeDirection.UP:
            high = max(element.high, stroke.high)
            low = max(element.low, stroke.low)
        else:
            high = min(element.high, stroke.high)
            low = min(element.low, stroke.low)
        value = FeatureElement(
            symbol=element.symbol,
            segment_direction=element.segment_direction,
            merge_direction=element.merge_direction,
            strokes=(*element.strokes, stroke),
            stroke_positions=(*element.stroke_positions, position),
            high=high,
            low=low,
            sequence_start_position=element.sequence_start_position,
            element_index=element.element_index,
        )
        self.audit_elements.append(value)
        return value

    def _build_target_fractal(self) -> FeatureFractal | None:
        left, middle, right = self.elements
        allow_equal = 1 if self.feature_direction is StrokeDirection.DOWN else -1

        if self.segment_direction is StrokeDirection.UP:
            is_target = (
                left.high < middle.high - _EPS
                and right.high <= middle.high + _EPS
                and right.low < middle.low - _EPS
                and (allow_equal == 1 or right.high < middle.high - _EPS)
            )
            if not is_target:
                return None
            mark = FractalMark.TOP
            endpoint_stroke, endpoint_position = max(
                zip(middle.strokes, middle.stroke_positions),
                key=lambda item: (item[0].high, item[1]),
            )
            break_status, detected_at = self._actual_break_up(middle, right)
            gap = left.high < middle.low - _EPS
        else:
            is_target = (
                left.low > middle.low + _EPS
                and right.low >= middle.low - _EPS
                and right.high > middle.high + _EPS
                and (allow_equal == -1 or right.low > middle.low + _EPS)
            )
            if not is_target:
                return None
            mark = FractalMark.BOTTOM
            endpoint_stroke, endpoint_position = min(
                zip(middle.strokes, middle.stroke_positions),
                key=lambda item: (item[0].low, -item[1]),
            )
            break_status, detected_at = self._actual_break_down(middle, right)
            gap = left.low > middle.high + _EPS

        endpoint = endpoint_stroke.fx_a
        if endpoint.mark is not mark:  # pragma: no cover - 笔方向不变量
            return None
        if not self.require_actual_break:
            break_status = FeatureBreakStatus.CONFIRMED
        return FeatureFractal(
            symbol=endpoint.symbol,
            segment_direction=self.segment_direction,
            mark=mark,
            left=left,
            middle=middle,
            right=right,
            endpoint=endpoint,
            endpoint_position=endpoint_position,
            gap=gap,
            break_status=break_status,
            detected_at_position=detected_at,
        )

    def _actual_break_up(
        self, middle: FeatureElement, right: FeatureElement
    ) -> tuple[FeatureBreakStatus, int]:
        """判断向上线段顶分型后，下降特征笔是否真实向下突破。

        状态严格区分三类：已经突破、尾部证据不足、以及已有充分后续数据
        但仍未突破。最后一类必须重置特征序列继续扫描，不能终止整个线段识别。
        """
        right_position = right.last_stroke_position
        if right.low < middle.strokes[-1].low - _EPS:
            return FeatureBreakStatus.CONFIRMED, right_position

        next_same = right_position + 2
        if next_same < len(self.strokes):
            if self.strokes[next_same].low < right.strokes[-1].low - _EPS:
                return FeatureBreakStatus.CONFIRMED, next_same
            # 同向验证笔已有，但它仍处在数据尾部，尚缺下一根反向笔来证明
            # 该结构已经失败；这对应实时数据中的未确认状态。
            if next_same + 1 >= len(self.strokes):
                return FeatureBreakStatus.PENDING, next_same
            return FeatureBreakStatus.REJECTED, next_same

        next_opposite = right_position + 1
        if next_opposite < len(self.strokes):
            # 只有一根反向笔时，若它已越过中间特征元素的高点，则当前顶分型
            # 不可能再成为该线段终点；否则仍需等待下一根同向特征笔。
            if self.strokes[next_opposite].high > middle.high + _EPS:
                return FeatureBreakStatus.REJECTED, next_opposite
            return FeatureBreakStatus.PENDING, next_opposite
        return FeatureBreakStatus.PENDING, right_position

    def _actual_break_down(
        self, middle: FeatureElement, right: FeatureElement
    ) -> tuple[FeatureBreakStatus, int]:
        """判断向下线段底分型后，上升特征笔是否真实向上突破。"""
        right_position = right.last_stroke_position
        if right.high > middle.strokes[-1].high + _EPS:
            return FeatureBreakStatus.CONFIRMED, right_position

        next_same = right_position + 2
        if next_same < len(self.strokes):
            if self.strokes[next_same].high > right.strokes[-1].high + _EPS:
                return FeatureBreakStatus.CONFIRMED, next_same
            if next_same + 1 >= len(self.strokes):
                return FeatureBreakStatus.PENDING, next_same
            return FeatureBreakStatus.REJECTED, next_same

        next_opposite = right_position + 1
        if next_opposite < len(self.strokes):
            if self.strokes[next_opposite].low < middle.low - _EPS:
                return FeatureBreakStatus.REJECTED, next_opposite
            return FeatureBreakStatus.PENDING, next_opposite
        return FeatureBreakStatus.PENDING, right_position


def stroke_endpoints(strokes: Sequence[Stroke]) -> tuple[Fractal, ...]:
    """把连续笔链转换为端点序列；N 笔对应 N+1 个端点。"""
    if not strokes:
        return ()
    points = [strokes[0].fx_a]
    for i, stroke in enumerate(strokes):
        if i and not _same_endpoint(strokes[i - 1].fx_b, stroke.fx_a):
            raise ValueError(f"第 {i - 1}、{i} 笔没有共享同一端点，不能识别线段")
        points.append(stroke.fx_b)
    return tuple(points)


def detect_segments(
    strokes: Sequence[Stroke],
    *,
    latest_bar: MergedBar | None = None,
    mode: SegmentMode | str = SegmentMode.FEATURE_SEQUENCE,
    handle_last: bool = True,
) -> SegmentDetectionResult:
    """从最终笔链识别已确认线段。

    向上线段取向下笔组成特征序列并找顶分型；向下线段取向上笔组成特征
    序列并找底分型。第一、二特征元素无缺口时直接确认；有缺口时必须由
    从候选端点开始的反向标准特征序列分型确认。未满足确认条件的尾部不会
    被强行画成线段。
    """
    del latest_bar, handle_last  # 旧接口兼容；最终结果由完整笔链重算决定。
    resolved_mode = SegmentMode(mode)
    values = tuple(strokes)
    endpoints = stroke_endpoints(values)
    if len(values) < 3:
        return SegmentDetectionResult(
            segments=(),
            markers=(),
            candidates=(),
            unfinished_strokes=values,
            unresolved_prefix_strokes=(),
            feature_elements=(),
            feature_fractals=(),
            evidence=(),
            diagnostics=(),
            mode=resolved_mode,
        )

    first = _choose_first_segment(values, endpoints)
    all_elements = list(first.elements)
    all_fractals = list(first.fractals)
    diagnostics = list(first.diagnostics)

    if first.end_position is None or first.primary is None:
        return SegmentDetectionResult(
            segments=(),
            markers=(),
            candidates=tuple(_dedupe_fractals(x.endpoint for x in all_fractals)),
            unfinished_strokes=values[first.start_position :],
            unresolved_prefix_strokes=values[: first.start_position],
            feature_elements=_unique_feature_elements(all_elements),
            feature_fractals=_unique_feature_fractals(all_fractals),
            evidence=(),
            diagnostics=tuple(diagnostics),
            mode=resolved_mode,
        )

    start = first.start_position
    unresolved_prefix = values[:start]
    if unresolved_prefix:
        diagnostics.append(
            SegmentDiagnostic(
                code="UNRESOLVED_PREFIX",
                message=(
                    f"窗口开头 {len(unresolved_prefix)} 笔缺少更早历史，"
                    "不强行归入首条已确认线段"
                ),
                dt=unresolved_prefix[0].start_dt,
            )
        )

    segments: list[Segment] = []
    markers: list[Fractal] = []
    evidence: list[SegmentEvidence] = []
    current = first
    last_scan_start = start

    while current.end_position is not None and current.primary is not None:
        end = current.end_position
        if not _candidate_can_end(values, start, end):
            diagnostics.append(
                SegmentDiagnostic(
                    code="SEGMENT_CANDIDATE_INVALID",
                    message=f"候选端点 {end} 未满足至少三笔、奇数笔与首三笔重叠条件",
                    dt=endpoints[end].dt,
                )
            )
            break

        segment = _make_segment(values, endpoints, start, end, len(segments))
        segments.append(segment)
        if not markers:
            markers.append(endpoints[start])
        markers.append(endpoints[end])
        evidence.append(
            SegmentEvidence(
                segment_index=segment.index,
                start_position=start,
                end_position=end,
                confirmation=current.confirmation or "UNKNOWN",
                primary_fractal=current.primary,
                reverse_fractal=current.reverse,
            )
        )

        start = end
        last_scan_start = start
        if len(values) - start < 3:
            break
        current = _scan_segment(values, endpoints, start)
        all_elements.extend(current.elements)
        all_fractals.extend(current.fractals)
        diagnostics.extend(current.diagnostics)

    unfinished = values[last_scan_start:]
    return SegmentDetectionResult(
        segments=tuple(segments),
        markers=tuple(markers),
        candidates=tuple(_dedupe_fractals(x.endpoint for x in all_fractals)),
        unfinished_strokes=tuple(unfinished),
        unresolved_prefix_strokes=tuple(unresolved_prefix),
        feature_elements=_unique_feature_elements(all_elements),
        feature_fractals=_unique_feature_fractals(all_fractals),
        evidence=tuple(evidence),
        diagnostics=tuple(diagnostics),
        mode=resolved_mode,
    )


def validate_feature_sequence_coverage(
    feature_elements: Sequence[FeatureElement],
    strokes: Sequence[Stroke],
    *,
    max_tail_gap: int = 2,
) -> tuple[SegmentDiagnostic, ...]:
    """验证特征序列是否持续扫描到笔链尾部附近。

    标准特征序列只取隔笔，因此正常情况下末端最多可能剩余两笔尚未进入完整
    特征元素。超过这个范围通常意味着状态机在中途候选处错误停止。
    """
    values = tuple(strokes)
    elements = tuple(feature_elements)
    if len(values) < 6:
        return ()
    if not elements:
        return (
            SegmentDiagnostic(
                code="FEATURE_SEQUENCE_EMPTY_FOR_LONG_CHAIN",
                message=f"笔链已有 {len(values)} 笔，但特征序列为空",
                dt=values[0].start_dt,
            ),
        )
    scanned_to = max(
        position for element in elements for position in element.stroke_positions
    )
    tail_gap = len(values) - 1 - scanned_to
    if tail_gap <= max_tail_gap:
        return ()
    return (
        SegmentDiagnostic(
            code="FEATURE_SEQUENCE_TAIL_NOT_SCANNED",
            message=(
                f"标准特征序列只扫描到第 {scanned_to} 笔，"
                f"距离笔链末尾仍有 {tail_gap} 笔，疑似状态机提前停止"
            ),
            dt=values[scanned_to].end_dt,
        ),
    )


def validate_segment_chain(
    segments: Sequence[Segment],
    strokes: Sequence[Stroke],
    *,
    mode: SegmentMode | str = SegmentMode.FEATURE_SEQUENCE,
    evidence: Sequence[SegmentEvidence] | None = None,
) -> tuple[SegmentDiagnostic, ...]:
    """检查线段链和标准特征序列确认依据。"""
    SegmentMode(mode)
    values = tuple(strokes)
    endpoints = stroke_endpoints(values)
    expected = detect_segments(values)
    issues: list[SegmentDiagnostic] = []

    if _segment_signature(segments) != _segment_signature(expected.segments):
        issues.append(
            SegmentDiagnostic(
                code="SEGMENT_FEATURE_SEQUENCE_MISMATCH",
                message="传入线段链与同一批笔重算的标准特征序列结果不一致",
                dt=segments[0].start_dt if segments else None,
            )
        )

    issues.extend(validate_feature_sequence_coverage(expected.feature_elements, values))

    evidence_values = tuple(evidence) if evidence is not None else expected.evidence
    if len(evidence_values) != len(segments):
        issues.append(
            SegmentDiagnostic(
                code="SEGMENT_EVIDENCE_COUNT_MISMATCH",
                message=f"线段 {len(segments)} 条，确认依据 {len(evidence_values)} 条",
            )
        )

    endpoint_positions = {
        (x.dt, x.mark, round(x.value, 12)): i for i, x in enumerate(endpoints)
    }
    for i, segment in enumerate(segments):
        start = endpoint_positions.get(_endpoint_key(segment.fx_a))
        end = endpoint_positions.get(_endpoint_key(segment.fx_b))
        expected_marks = (
            (FractalMark.BOTTOM, FractalMark.TOP)
            if segment.direction is StrokeDirection.UP
            else (FractalMark.TOP, FractalMark.BOTTOM)
        )
        if (segment.fx_a.mark, segment.fx_b.mark) != expected_marks:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_DIRECTION_MARK_MISMATCH",
                    message=f"第 {i} 线段方向与端点类型不一致",
                    dt=segment.start_dt,
                )
            )
        if segment.stroke_count < 3 or segment.stroke_count % 2 == 0:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_STROKE_COUNT_INVALID",
                    message=f"第 {i} 线段含 {segment.stroke_count} 笔，必须是至少 3 的奇数",
                    dt=segment.start_dt,
                )
            )
        if start is None or end is None or end <= start:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_ENDPOINT_NOT_IN_CHAIN",
                    message=f"第 {i} 线段端点不在原笔端点序列中",
                    dt=segment.start_dt,
                )
            )
            continue
        if tuple(values[start:end]) != segment.strokes:
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_STROKES_NOT_CONTIGUOUS",
                    message=f"第 {i} 线段不是原笔链的连续切片",
                    dt=segment.start_dt,
                )
            )
        if not _first_three_overlap(values, start):
            issues.append(
                SegmentDiagnostic(
                    code="SEGMENT_FIRST_THREE_NO_OVERLAP",
                    message=f"第 {i} 线段首三笔没有共同重叠区间",
                    dt=segment.start_dt,
                )
            )

        if i < len(evidence_values):
            item = evidence_values[i]
            if (item.start_position, item.end_position) != (start, end):
                issues.append(
                    SegmentDiagnostic(
                        code="SEGMENT_EVIDENCE_ENDPOINT_MISMATCH",
                        message=f"第 {i} 线段与确认依据端点不一致",
                        dt=segment.end_dt,
                    )
                )
            if not item.primary_fractal.actual_break:
                issues.append(
                    SegmentDiagnostic(
                        code="PRIMARY_FEATURE_NO_ACTUAL_BREAK",
                        message=f"第 {i} 线段的主特征分型没有真实突破",
                        dt=segment.end_dt,
                    )
                )
            if item.confirmation == "NO_GAP" and item.primary_fractal.gap:
                issues.append(
                    SegmentDiagnostic(
                        code="NO_GAP_EVIDENCE_HAS_GAP",
                        message=f"第 {i} 线段标为无缺口确认，但主分型存在缺口",
                        dt=segment.end_dt,
                    )
                )
            if item.confirmation == "GAP_REVERSE_FRACTAL" and (
                not item.primary_fractal.gap or item.reverse_fractal is None
            ):
                issues.append(
                    SegmentDiagnostic(
                        code="GAP_CONFIRMATION_EVIDENCE_MISSING",
                        message=f"第 {i} 线段缺口确认缺少反向特征分型",
                        dt=segment.end_dt,
                    )
                )

        if i:
            previous = segments[i - 1]
            if previous.direction is segment.direction:
                issues.append(
                    SegmentDiagnostic(
                        code="SEGMENT_DIRECTION_NOT_ALTERNATING",
                        message=f"第 {i - 1}、{i} 线段方向没有交替",
                        dt=segment.start_dt,
                    )
                )
            if not _same_endpoint(previous.fx_b, segment.fx_a):
                issues.append(
                    SegmentDiagnostic(
                        code="SEGMENT_ENDPOINT_NOT_SHARED",
                        message=f"第 {i - 1}、{i} 线段没有共享端点",
                        dt=segment.start_dt,
                    )
                )
    return tuple(issues)


def _choose_first_segment(
    strokes: Sequence[Stroke], endpoints: Sequence[Fractal]
) -> _ScanOutcome:
    attempts: list[_ScanOutcome] = []
    # 有限窗口可能从一条既有线段中部开始；依次尝试每个笔端点，并优先采用
    # 最靠前、能够被完整确认的起点。此前的笔明确标记为“窗口前缀未解析”。
    for start in range(max(0, len(strokes) - 2)):
        if not _first_three_overlap(strokes, start):
            continue
        outcome = _scan_segment(strokes, endpoints, start)
        attempts.append(outcome)
        if outcome.end_position is not None:
            return outcome
    if not attempts:
        return _ScanOutcome(0, None, None, None, None, None, [], [], [])
    return max(
        attempts,
        key=lambda x: (len(x.fractals), len(x.elements), -x.start_position),
    )


def _scan_segment(
    strokes: Sequence[Stroke], endpoints: Sequence[Fractal], start_position: int
) -> _ScanOutcome:
    del endpoints
    direction = strokes[start_position].direction
    primary_detector = _FeatureDetector(
        strokes,
        segment_direction=direction,
        sequence_start_position=start_position,
        require_actual_break=True,
    )
    diagnostics: list[SegmentDiagnostic] = []
    primary_candidate: FeatureFractal | None = None

    position = start_position + 1
    pending_primary: FeatureFractal | None = None
    while position < len(strokes) or pending_primary is not None:
        if pending_primary is not None:
            fractal = pending_primary
            pending_primary = None
        else:
            fractal = primary_detector.add_position(position)
            position += 1
        if fractal is None:
            continue
        primary_candidate = fractal
        if fractal.break_status is FeatureBreakStatus.PENDING:
            diagnostics.append(
                SegmentDiagnostic(
                    code="FEATURE_FRACTAL_WAIT_ACTUAL_BREAK",
                    message=(
                        f"{fractal.dt.isoformat()} 已形成特征分型形态，"
                        "但当前位于数据尾部，真实突破证据尚不完整，暂不确认线段"
                    ),
                    dt=fractal.dt,
                )
            )
            break
        if fractal.break_status is FeatureBreakStatus.REJECTED:
            diagnostics.append(
                SegmentDiagnostic(
                    code="FEATURE_FRACTAL_REJECTED_NO_ACTUAL_BREAK",
                    message=(
                        f"{fractal.dt.isoformat()} 的特征分型已被充分后续数据否定："
                        "没有形成真实突破，重置标准特征序列并继续扫描"
                    ),
                    dt=fractal.dt,
                )
            )
            pending_primary = primary_detector._reset_and_replay()
            primary_candidate = None
            continue
        if not _candidate_can_end(strokes, start_position, fractal.endpoint_position):
            diagnostics.append(
                SegmentDiagnostic(
                    code="FEATURE_FRACTAL_TOO_EARLY",
                    message="特征分型对应端点尚不满足线段至少三笔与首三笔重叠",
                    dt=fractal.dt,
                )
            )
            # 该分型不能作为线段终点。重放时可能立即得到下一个分型，
            # 必须在追加新笔前先处理它，否则检测器会停留在三个元素状态。
            pending_primary = primary_detector._reset_and_replay()
            primary_candidate = None
            continue

        if not fractal.gap:
            return _ScanOutcome(
                start_position=start_position,
                end_position=fractal.endpoint_position,
                primary=fractal,
                reverse=None,
                confirmation="NO_GAP",
                confirmed_at_position=fractal.detected_at_position,
                elements=list(primary_detector.audit_elements),
                fractals=list(primary_detector.audit_fractals),
                diagnostics=diagnostics,
            )

        diagnostics.append(
            SegmentDiagnostic(
                code="FEATURE_GAP_WAIT_REVERSE",
                message=(
                    f"{fractal.dt.isoformat()} 的主特征分型第一、二元素有缺口，"
                    "等待反向标准特征序列出现分型"
                ),
                dt=fractal.dt,
            )
        )
        reverse_detector = _FeatureDetector(
            strokes,
            segment_direction=_opposite(direction),
            sequence_start_position=fractal.endpoint_position,
            require_actual_break=True,
        )
        reverse_position = fractal.endpoint_position + 1
        pending_reverse: FeatureFractal | None = None
        while reverse_position < len(strokes) or pending_reverse is not None:
            if pending_reverse is not None:
                reverse = pending_reverse
                pending_reverse = None
            else:
                reverse = reverse_detector.add_position(reverse_position)
                reverse_position += 1
            if reverse is None:
                continue
            if reverse.break_status is FeatureBreakStatus.PENDING:
                diagnostics.append(
                    SegmentDiagnostic(
                        code="REVERSE_FEATURE_WAIT_ACTUAL_BREAK",
                        message=(
                            f"{reverse.dt.isoformat()} 的反向特征分型位于数据尾部，"
                            "真实突破证据尚不完整"
                        ),
                        dt=reverse.dt,
                    )
                )
                break
            if reverse.break_status is FeatureBreakStatus.REJECTED:
                diagnostics.append(
                    SegmentDiagnostic(
                        code="REVERSE_FEATURE_REJECTED_NO_ACTUAL_BREAK",
                        message=(
                            f"{reverse.dt.isoformat()} 的反向特征分型已被充分后续数据否定，"
                            "重置反向标准特征序列并继续扫描"
                        ),
                        dt=reverse.dt,
                    )
                )
                pending_reverse = reverse_detector._reset_and_replay()
                continue
            return _ScanOutcome(
                start_position=start_position,
                end_position=fractal.endpoint_position,
                primary=fractal,
                reverse=reverse,
                confirmation="GAP_REVERSE_FRACTAL",
                confirmed_at_position=reverse.detected_at_position,
                elements=[
                    *primary_detector.audit_elements,
                    *reverse_detector.audit_elements,
                ],
                fractals=[
                    *primary_detector.audit_fractals,
                    *reverse_detector.audit_fractals,
                ],
                diagnostics=diagnostics,
            )
        return _ScanOutcome(
            start_position=start_position,
            end_position=None,
            primary=fractal,
            reverse=None,
            confirmation=None,
            confirmed_at_position=None,
            elements=list(primary_detector.audit_elements),
            fractals=list(primary_detector.audit_fractals),
            diagnostics=diagnostics,
        )

    return _ScanOutcome(
        start_position=start_position,
        end_position=None,
        primary=primary_candidate,
        reverse=None,
        confirmation=None,
        confirmed_at_position=None,
        elements=list(primary_detector.audit_elements),
        fractals=list(primary_detector.audit_fractals),
        diagnostics=diagnostics,
    )

def _relation(
    high1: float,
    low1: float,
    high2: float,
    low2: float,
    *,
    exclude_included: bool,
    allow_top_equal: int | None = None,
) -> _Relation:
    if high1 >= high2 - _EPS and low1 <= low2 + _EPS:
        return _Relation.COMBINE
    if high1 <= high2 + _EPS and low1 >= low2 - _EPS:
        if allow_top_equal == 1 and abs(high1 - high2) <= _EPS and low1 > low2 + _EPS:
            return _Relation.DOWN
        if allow_top_equal == -1 and abs(low1 - low2) <= _EPS and high1 < high2 - _EPS:
            return _Relation.UP
        return _Relation.INCLUDED if exclude_included else _Relation.COMBINE
    if high1 > high2 + _EPS and low1 > low2 + _EPS:
        return _Relation.DOWN
    if high1 < high2 - _EPS and low1 < low2 - _EPS:
        return _Relation.UP
    # 浮点边界落在等价关系时按包含处理，保证顺序稳定。
    if abs(high1 - high2) <= _EPS or abs(low1 - low2) <= _EPS:
        return _Relation.COMBINE
    raise ValueError(f"无法判断特征元素关系：[{low1}, {high1}] vs [{low2}, {high2}]")


def _relation_direction(relation: _Relation) -> StrokeDirection:
    if relation is _Relation.UP:
        return StrokeDirection.UP
    if relation is _Relation.DOWN:
        return StrokeDirection.DOWN
    raise ValueError(f"关系 {relation} 不能作为特征元素合并方向")


def _candidate_can_end(
    strokes: Sequence[Stroke], start_position: int, end_position: int
) -> bool:
    count = end_position - start_position
    return count >= 3 and count % 2 == 1 and _first_three_overlap(strokes, start_position)


def _first_three_overlap(strokes: Sequence[Stroke], start_position: int) -> bool:
    values = strokes[start_position : start_position + 3]
    if len(values) < 3:
        return False
    return max(x.low for x in values) <= min(x.high for x in values) + _EPS


def _make_segment(
    strokes: Sequence[Stroke],
    endpoints: Sequence[Fractal],
    start: int,
    end: int,
    index: int,
) -> Segment:
    return Segment(
        symbol=strokes[start].symbol,
        fx_a=endpoints[start],
        fx_b=endpoints[end],
        direction=strokes[start].direction,
        strokes=tuple(strokes[start:end]),
        index=index,
    )


def _opposite(direction: StrokeDirection) -> StrokeDirection:
    return StrokeDirection.DOWN if direction is StrokeDirection.UP else StrokeDirection.UP


def _same_endpoint(a: Fractal, b: Fractal) -> bool:
    return a.dt == b.dt and a.mark is b.mark and abs(a.value - b.value) <= 1e-9


def _endpoint_key(value: Fractal) -> tuple:
    return value.dt, value.mark, round(value.value, 12)


def _dedupe_fractals(values: Iterable[Fractal]) -> list[Fractal]:
    result: list[Fractal] = []
    seen: set[tuple] = set()
    for value in values:
        key = _endpoint_key(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _unique_feature_elements(values: Iterable[FeatureElement]) -> tuple[FeatureElement, ...]:
    latest: dict[tuple, FeatureElement] = {}
    for value in values:
        key = (
            value.sequence_start_position,
            value.segment_direction,
            value.element_index,
        )
        current = latest.get(key)
        if current is None or len(value.stroke_positions) >= len(current.stroke_positions):
            latest[key] = value
    return tuple(
        sorted(
            latest.values(),
            key=lambda x: (
                x.sequence_start_position,
                x.segment_direction.value,
                x.element_index,
            ),
        )
    )


def _unique_feature_fractals(values: Iterable[FeatureFractal]) -> tuple[FeatureFractal, ...]:
    result: list[FeatureFractal] = []
    seen: set[tuple] = set()
    for value in values:
        key = (
            value.segment_direction,
            value.mark,
            value.left.stroke_positions,
            value.middle.stroke_positions,
            value.right.stroke_positions,
            value.endpoint_position,
            value.break_status,
        )
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(
        sorted(
            result,
            key=lambda x: (
                x.detected_at_position,
                x.endpoint_position,
                x.segment_direction.value,
            ),
        )
    )


def _segment_signature(values: Sequence[Segment]) -> tuple:
    return tuple(
        (
            item.direction,
            item.start_dt,
            round(item.start_value, 12),
            item.end_dt,
            round(item.end_value, 12),
            tuple(x.index for x in item.strokes),
        )
        for item in values
    )
