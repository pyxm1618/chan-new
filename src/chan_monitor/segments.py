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
    stroke_fingerprint,
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


class SegmentValidationTarget(str, Enum):
    """线段校验对象的语义。

    ``DETECTED`` 表示直接检测结果，必须与同一批笔全量重算完全一致；
    ``COMMITTED`` 表示增量状态机的正式提交账本，只要求是从其锚点重算结果
    的连续前缀，不能拿裁到稳定边界的笔链要求完全重算一致。
    """

    DETECTED = "detected"
    COMMITTED = "committed"


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
    gap_origin: FeatureFractal | None = None
    final_endpoint: Fractal | None = None


@dataclass(slots=True)
class _DetectorTrace:
    candidates: list[FeatureFractal]
    elements: list[FeatureElement]
    fractals: list[FeatureFractal]


@dataclass(slots=True)
class _ReverseAttempt:
    endpoint_position: int
    endpoint: Fractal
    trace: _DetectorTrace
    confirmed: FeatureFractal | None
    active_from: int
    active_until: int | None = None


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
    exclude_last_stroke_confirmation: bool = False,
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

    first = _choose_first_segment(
        values,
        endpoints,
        exclude_last_stroke_confirmation=exclude_last_stroke_confirmation,
    )
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
        if (
            exclude_last_stroke_confirmation
            and _confirmation_uses_reversible_last_stroke(current, len(values))
        ):
            diagnostics.append(
                SegmentDiagnostic(
                    code="SEGMENT_CONFIRMATION_USES_REVERSIBLE_LAST_STROKE",
                    message=(
                        f"候选线段 {start}→{end} 的确认发生在当前最后一笔 "
                        f"{current.confirmed_at_position}；最后一笔仍可能被后续 K 线撤销，"
                        "该线段暂保留为未确认候选"
                    ),
                    dt=endpoints[end].dt,
                )
            )
            last_scan_start = start
            break
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
                gap_origin_fractal=current.gap_origin,
                final_endpoint=current.final_endpoint or endpoints[end],
                segment_symbol=segment.symbol,
                segment_interval=segment.interval,
                segment_fingerprint=segment.fingerprint,
                confirmation_available_at=_stroke_available_at(
                    values[current.confirmed_at_position]
                ),
                confirmation_stroke_fingerprint=stroke_fingerprint(
                    values[current.confirmed_at_position]
                ),
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


def _confirmation_uses_reversible_last_stroke(
    outcome: _ScanOutcome, stroke_count: int
) -> bool:
    """最后一笔可能被新 K 线同向延伸撤销，不能作为实线段确认依据。"""
    if stroke_count <= 0 or outcome.confirmed_at_position is None:
        return True
    return outcome.confirmed_at_position >= stroke_count - 1



def validate_feature_sequence_coverage(
    feature_elements: Sequence[FeatureElement],
    strokes: Sequence[Stroke],
    *,
    max_tail_gap: int = 2,
    scan_start_position: int = 0,
) -> tuple[SegmentDiagnostic, ...]:
    """验证特征序列是否持续扫描到笔链尾部附近。

    标准特征序列只取隔笔，因此正常情况下末端最多可能剩余两笔尚未进入完整
    特征元素。超过这个范围通常意味着状态机在中途候选处错误停止。
    """
    values = tuple(strokes)
    elements = tuple(feature_elements)
    if not 0 <= scan_start_position <= len(values):
        raise ValueError("scan_start_position 必须位于 [0, len(strokes)]")
    # 锚点后只剩 1～2 笔时，标准特征序列尚没有可形成的完整元素；这是正常
    # 未完成尾部，不得按整条笔链长度误报“特征序列为空”。
    if len(values) - scan_start_position <= max_tail_gap:
        return ()
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
    exclude_last_stroke_confirmation: bool = False,
    validation_target: SegmentValidationTarget | str = SegmentValidationTarget.DETECTED,
    stable_stroke_count: int | None = None,
) -> tuple[SegmentDiagnostic, ...]:
    """检查线段链和标准特征序列确认依据。

    ``DETECTED`` 用于校验一次性检测结果，要求与同一批笔重算完全一致。
    ``COMMITTED`` 用于校验增量正式账本：正式线段只需是从其真实锚点重算
    结果的前缀，并且每条确认依据必须带真实提交时间。

    ``stable_stroke_count`` 明确指出 ``strokes`` 中不可回撤的前缀长度。它比
    “最后一笔必然可回撤”的旧假设更准确；未提供时仍兼容旧参数
    ``exclude_last_stroke_confirmation``。
    """
    resolved_mode = SegmentMode(mode)
    resolved_target = SegmentValidationTarget(validation_target)
    values = tuple(strokes)
    endpoints = stroke_endpoints(values)
    evidence_values = tuple(evidence) if evidence is not None else ()
    anchor_position = 0

    if stable_stroke_count is not None and not 0 <= stable_stroke_count <= len(values):
        raise ValueError("stable_stroke_count 必须位于 [0, len(strokes)]")

    if resolved_target is SegmentValidationTarget.COMMITTED and segments:
        if evidence_values:
            anchor_position = evidence_values[0].start_position
        else:
            first_key = _endpoint_key(segments[0].fx_a)
            endpoint_positions = {
                _endpoint_key(endpoint): i for i, endpoint in enumerate(endpoints)
            }
            anchor_position = endpoint_positions.get(first_key, 0)
        expected = detect_segments_from_anchor(
            values,
            start_position=anchor_position,
            mode=resolved_mode,
            # 正式账本本身已由 stable_stroke_count 约束，不能再把稳定前缀
            # 的最后一笔机械视为可回撤笔。
            exclude_last_stroke_confirmation=False,
        )
    else:
        expected = detect_segments(
            values,
            mode=resolved_mode,
            exclude_last_stroke_confirmation=exclude_last_stroke_confirmation,
        )
    issues: list[SegmentDiagnostic] = []

    actual_signature = _segment_signature(segments)
    expected_signature = _segment_signature(expected.segments)
    if resolved_target is SegmentValidationTarget.COMMITTED:
        structure_matches = actual_signature == expected_signature[: len(actual_signature)]
        mismatch_message = "正式线段账本不是从其锚点重算结果的连续前缀"
    else:
        structure_matches = actual_signature == expected_signature
        mismatch_message = "传入线段链与同一批笔重算的标准特征序列结果不一致"

    if not structure_matches:
        issues.append(
            SegmentDiagnostic(
                code="SEGMENT_FEATURE_SEQUENCE_MISMATCH",
                message=mismatch_message,
                dt=segments[0].start_dt if segments else None,
            )
        )

    issues.extend(validate_feature_sequence_coverage(
        expected.feature_elements,
        values,
        scan_start_position=anchor_position
        if resolved_target is SegmentValidationTarget.COMMITTED
        else 0,
    ))

    if evidence is None:
        evidence_values = expected.evidence
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
    reversible_from: int | None = None
    if stable_stroke_count is not None:
        reversible_from = stable_stroke_count
    elif exclude_last_stroke_confirmation and values:
        reversible_from = len(values) - 1

    previous_committed_at = None
    previous_committed_position = None
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
        if i == 0 and not _first_segment_extremes_valid(values, endpoints, start, end):
            issues.append(
                SegmentDiagnostic(
                    code="FIRST_SEGMENT_EXTREME_VIOLATION",
                    message="首条线段的起点或终点不是段内同类端点极值",
                    dt=segment.start_dt,
                )
            )

        if i < len(evidence_values):
            item = evidence_values[i]
            if reversible_from is not None:
                if resolved_target is SegmentValidationTarget.COMMITTED:
                    if item.end_position >= reversible_from:
                        issues.append(
                            SegmentDiagnostic(
                                code="SEGMENT_GEOMETRY_OUTSIDE_STABLE_PREFIX",
                                message=(
                                    f"第 {i} 线段终点笔位置 {item.end_position} 不在稳定几何前缀 "
                                    f"长度 {reversible_from} 内"
                                ),
                                dt=segment.end_dt,
                            )
                        )
                elif item.confirmed_at_position >= reversible_from:
                    issues.append(
                        SegmentDiagnostic(
                            code="SEGMENT_CONFIRMATION_USES_REVERSIBLE_LAST_STROKE",
                            message=(
                                f"第 {i} 线段的确认依据位于可回撤笔区间 "
                                f"{item.confirmed_at_position}；稳定笔前缀长度为 "
                                f"{reversible_from}"
                            ),
                            dt=segment.end_dt,
                        )
                    )

            if resolved_target is SegmentValidationTarget.COMMITTED:
                if not item.matches_segment(segment):
                    issues.append(
                        SegmentDiagnostic(
                            code="SEGMENT_EVIDENCE_IDENTITY_MISMATCH",
                            message=f"第 {i} 条正式线段的提交证据与线段身份不匹配",
                            dt=segment.end_dt,
                        )
                    )
                if item.committed_at is None or item.committed_at_bar_position is None:
                    issues.append(
                        SegmentDiagnostic(
                            code="SEGMENT_COMMIT_TIME_MISSING",
                            message=f"第 {i} 条正式线段缺少 committed_at 或原始 K 位置",
                            dt=segment.end_dt,
                        )
                    )
                else:
                    if previous_committed_at is not None and item.committed_at < previous_committed_at:
                        issues.append(
                            SegmentDiagnostic(
                                code="SEGMENT_COMMIT_TIME_NOT_MONOTONIC",
                                message=f"第 {i} 条线段的正式提交时间早于前一条线段",
                                dt=item.committed_at,
                            )
                        )
                    if (
                        previous_committed_position is not None
                        and item.committed_at_bar_position < previous_committed_position
                    ):
                        issues.append(
                            SegmentDiagnostic(
                                code="SEGMENT_COMMIT_POSITION_NOT_MONOTONIC",
                                message=f"第 {i} 条线段的正式提交 K 位置早于前一条线段",
                                dt=item.committed_at,
                            )
                        )
                    available_at = item.confirmation_available_at
                    if available_at is None:
                        issues.append(
                            SegmentDiagnostic(
                                code="SEGMENT_CONFIRMATION_SNAPSHOT_MISSING",
                                message=f"第 {i} 条正式线段缺少不可变确认时间快照",
                                dt=segment.end_dt,
                            )
                        )
                    elif item.committed_at < available_at:
                        issues.append(
                            SegmentDiagnostic(
                                code="SEGMENT_COMMIT_TIME_BEFORE_EVIDENCE",
                                message=(
                                    f"第 {i} 条线段在确认依据可用之前就被标记为提交："
                                    f"{item.committed_at.isoformat()} < {available_at.isoformat()}"
                                ),
                                dt=item.committed_at,
                            )
                        )
                    if (
                        item.confirmation_stroke_fingerprint is not None
                        and 0 <= item.confirmed_at_position < len(values)
                    ):
                        current_fingerprint = stroke_fingerprint(
                            values[item.confirmed_at_position]
                        )
                        # 位置上的尾笔已经迁移时，只说明当前笔链发生了合法演化；
                        # 正式提交时间必须按历史快照审计，不能拿新笔覆盖旧证据。
                        if current_fingerprint == item.confirmation_stroke_fingerprint:
                            current_available_at = _stroke_available_at(
                                values[item.confirmed_at_position]
                            )
                            if (
                                item.confirmation_available_at is not None
                                and current_available_at != item.confirmation_available_at
                            ):
                                issues.append(
                                    SegmentDiagnostic(
                                        code="SEGMENT_CONFIRMATION_SNAPSHOT_INCONSISTENT",
                                        message=f"第 {i} 条线段的确认时间快照与同一确认笔不一致",
                                        dt=segment.end_dt,
                                    )
                                )
                    previous_committed_at = item.committed_at
                    previous_committed_position = item.committed_at_bar_position
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
            if item.confirmation == "GAP_REVERSE_FRACTAL":
                origin = item.gap_origin_fractal or item.primary_fractal
                if not origin.gap or item.reverse_fractal is None:
                    issues.append(
                        SegmentDiagnostic(
                            code="GAP_CONFIRMATION_EVIDENCE_MISSING",
                            message=f"第 {i} 线段缺口确认缺少起始缺口分型或反向分型",
                            dt=segment.end_dt,
                        )
                    )
                issues.extend(
                    _validate_gap_endpoint_not_superseded(
                        strokes=values,
                        evidence=item,
                        segment_index=i,
                    )
                )
                issues.extend(
                    _validate_gap_wait_did_not_skip_no_gap_primary(
                        strokes=values,
                        evidence=item,
                        segment_index=i,
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


def _stroke_available_at(stroke: Stroke):
    """返回该笔所包含原始 K 全部收盘后的最早可用时间。"""
    return max(
        raw.close_time
        for merged in stroke.bars
        for raw in merged.elements
    )




def _validate_gap_wait_did_not_skip_no_gap_primary(
    *,
    strokes: Sequence[Stroke],
    evidence: SegmentEvidence,
    segment_index: int,
) -> tuple[SegmentDiagnostic, ...]:
    """缺口反向确认前不得存在更早生效的无缺口主分型。"""
    if evidence.confirmation != "GAP_REVERSE_FRACTAL":
        return ()
    origin = evidence.gap_origin_fractal or evidence.primary_fractal
    direction = strokes[evidence.start_position].direction
    trace = _trace_feature_detector(
        strokes,
        segment_direction=direction,
        sequence_start_position=evidence.start_position,
        feed_start=evidence.start_position + 1,
    )
    active_position = origin.endpoint_position
    active_endpoint = strokes[active_position].fx_a
    feature_direction = _opposite(direction)

    for position in range(origin.endpoint_position + 1, evidence.confirmed_at_position + 1):
        if position >= len(strokes):
            break
        stroke = strokes[position]
        if stroke.direction is feature_direction and stroke.fx_a.mark is origin.mark:
            if _is_more_extreme_endpoint(
                stroke.fx_a,
                active_endpoint,
                direction,
                position=position,
                current_position=active_position,
            ):
                active_position = position
                active_endpoint = stroke.fx_a

        candidates = [
            fx
            for fx in trace.candidates
            if fx.break_status is FeatureBreakStatus.CONFIRMED
            and not fx.gap
            and fx.detected_at_position == position
            and fx.detected_at_position > origin.detected_at_position
            and _candidate_can_end(strokes, evidence.start_position, fx.endpoint_position)
        ]
        if not candidates:
            continue
        candidate = _most_extreme_candidate(candidates, direction)
        if candidate.endpoint_position == active_position or _is_more_extreme_endpoint(
            candidate.endpoint,
            active_endpoint,
            direction,
            position=candidate.endpoint_position,
            current_position=active_position,
        ):
            return (
                SegmentDiagnostic(
                    code="GAP_CONFIRMATION_SKIPPED_EARLIER_NO_GAP_PRIMARY",
                    message=(
                        f"第 {segment_index} 线段在第 {evidence.confirmed_at_position} 笔"
                        f"按缺口反向分型确认，但第 {candidate.endpoint_position} 笔已在第 "
                        f"{candidate.detected_at_position} 笔形成更早生效的无缺口主分型"
                    ),
                    dt=candidate.dt,
                ),
            )
    return ()

def _validate_gap_endpoint_not_superseded(
    *,
    strokes: Sequence[Stroke],
    evidence: SegmentEvidence,
    segment_index: int,
) -> tuple[SegmentDiagnostic, ...]:
    """确认前最终端点必须是等待区间内的同类极值。"""
    if evidence.confirmation != "GAP_REVERSE_FRACTAL":
        return ()
    direction = strokes[evidence.start_position].direction
    origin = evidence.gap_origin_fractal or evidence.primary_fractal
    final_position = evidence.end_position
    final_endpoint = evidence.final_endpoint or strokes[final_position].fx_a
    feature_direction = _opposite(direction)
    for position in range(origin.endpoint_position + 1, len(strokes)):
        if position > evidence.confirmed_at_position:
            break
        stroke = strokes[position]
        if stroke.direction is not feature_direction:
            continue
        endpoint = stroke.fx_a
        if endpoint.mark is not origin.mark:
            continue
        if _is_more_extreme_endpoint(
            endpoint,
            final_endpoint,
            direction,
            position=position,
            current_position=final_position,
        ):
            return (
                SegmentDiagnostic(
                    code="GAP_ENDPOINT_SUPERSEDED_BEFORE_CONFIRMATION",
                    message=(
                        f"第 {segment_index} 线段在确认前仍存在未迁移的更极端端点："
                        f"当前第 {final_position} 笔 {final_endpoint.value:.12g}，"
                        f"候选第 {position} 笔 {endpoint.value:.12g}"
                    ),
                    dt=endpoint.dt,
                ),
            )
    return ()

def _first_segment_extremes_valid(
    strokes: Sequence[Stroke],
    endpoints: Sequence[Fractal],
    start_position: int,
    end_position: int,
) -> bool:
    """校验有限窗口首段候选的段内同类端点极值。

    该规则不能凭空恢复窗口之前的完整历史，但可以排除一种确定错误：
    候选首段内部已经出现比起点更极端的同类起点，或比终点更极端的
    同类终点。这样的候选不可能是当前窗口内自洽的首段。
    """
    if (
        start_position < 0
        or start_position >= len(strokes)
        or end_position <= start_position
        or end_position >= len(endpoints)
    ):
        return False
    if not _candidate_can_end(strokes, start_position, end_position):
        return False

    direction = strokes[start_position].direction
    start_side = endpoints[start_position : end_position + 1 : 2]
    end_side = endpoints[start_position + 1 : end_position + 1 : 2]
    if not start_side or not end_side:
        return False

    start_value = endpoints[start_position].value
    end_value = endpoints[end_position].value
    if direction is StrokeDirection.UP:
        return (
            start_value <= min(x.value for x in start_side) + _EPS
            and end_value >= max(x.value for x in end_side) - _EPS
        )
    return (
        start_value >= max(x.value for x in start_side) - _EPS
        and end_value <= min(x.value for x in end_side) + _EPS
    )


def _choose_first_segment(
    strokes: Sequence[Stroke],
    endpoints: Sequence[Fractal],
    *,
    exclude_last_stroke_confirmation: bool = False,
) -> _ScanOutcome:
    """从所有可能起点中选择最早完成且段内边界合法的首段。

    各起点独立扫描。只有同时通过标准特征序列确认和段内同类端点
    极值检查的候选，才允许成为首条已确认线段。被明确排除的完整候选
    不得通过“未完成候选”回退分支重新进入结果。
    """
    confirmed: list[_ScanOutcome] = []
    incomplete: list[_ScanOutcome] = []
    diagnostics: list[SegmentDiagnostic] = []

    for start_position in range(max(0, len(strokes) - 2)):
        if not _first_three_overlap(strokes, start_position):
            continue
        outcome = _scan_segment(strokes, endpoints, start_position)
        diagnostics.extend(outcome.diagnostics)
        if outcome.end_position is None:
            incomplete.append(outcome)
            continue

        if not _first_segment_extremes_valid(
            strokes,
            endpoints,
            start_position,
            outcome.end_position,
        ):
            diagnostics.append(
                SegmentDiagnostic(
                    code="FIRST_SEGMENT_EXTREME_VIOLATION",
                    message=(
                        f"首段候选 {start_position}→{outcome.end_position} "
                        "内部出现了比起点或终点更极端的同类端点，候选已排除"
                    ),
                    dt=endpoints[start_position].dt,
                )
            )
            continue
        confirmed.append(outcome)

    if confirmed:
        stable_confirmed = [
            item
            for item in confirmed
            if not _confirmation_uses_reversible_last_stroke(item, len(strokes))
        ]
        selectable = (
            stable_confirmed
            if exclude_last_stroke_confirmation and stable_confirmed
            else confirmed
        )

        def confirmed_key(outcome: _ScanOutcome) -> tuple[int, float, int, int]:
            start_position = outcome.start_position
            direction = strokes[start_position].direction
            start_value = endpoints[start_position].value
            extreme_key = (
                start_value
                if direction is StrokeDirection.UP
                else -start_value
            )
            confirmed_at = (
                outcome.confirmed_at_position
                if outcome.confirmed_at_position is not None
                else len(strokes)
            )
            return (
                outcome.end_position
                if outcome.end_position is not None
                else len(strokes),
                extreme_key,
                -start_position,
                confirmed_at,
            )

        selected = min(selectable, key=confirmed_key)
        selected.diagnostics = _dedupe_diagnostics(diagnostics)
        return selected

    if incomplete:
        selected = max(
            incomplete,
            key=lambda x: (len(x.fractals), len(x.elements), -x.start_position),
        )
        selected.diagnostics = _dedupe_diagnostics(diagnostics)
        return selected

    return _ScanOutcome(
        start_position=0,
        end_position=None,
        primary=None,
        reverse=None,
        confirmation=None,
        confirmed_at_position=None,
        elements=[],
        fractals=[],
        diagnostics=_dedupe_diagnostics(diagnostics),
    )


def _scan_segment(
    strokes: Sequence[Stroke], endpoints: Sequence[Fractal], start_position: int
) -> _ScanOutcome:
    """扫描一条线段，并让主确认与反向确认在缺口等待期持续竞争。

    第一种情况（主特征分型无缺口）直接确认。第二种情况由有缺口主分型
    启动后，不能把流程永久锁进反向分支：

    * 后续同类极值端点继续迁移，并从新端点重启反向特征序列；
    * 主特征序列继续运行；若更早出现有效无缺口主分型，立即按 ``NO_GAP``
      确认，不再等待旧缺口候选的反向分型；
    * 只有反向分型先于任何有效无缺口主分型完成时，才按
      ``GAP_REVERSE_FRACTAL`` 确认。

    这使“缺口等待”成为两个确认事件的竞争状态，而不是固定分支。
    """
    del endpoints
    direction = strokes[start_position].direction
    primary_trace = _trace_feature_detector(
        strokes,
        segment_direction=direction,
        sequence_start_position=start_position,
        feed_start=start_position + 1,
    )
    diagnostics: list[SegmentDiagnostic] = []
    candidate_diagnostics: list[tuple[int, SegmentDiagnostic]] = []

    valid_confirmed: list[FeatureFractal] = []
    last_candidate: FeatureFractal | None = None
    for fractal in sorted(
        primary_trace.candidates,
        key=lambda x: (
            x.detected_at_position,
            x.endpoint_position,
            x.middle.last_stroke_position,
        ),
    ):
        last_candidate = fractal
        if fractal.break_status is FeatureBreakStatus.PENDING:
            candidate_diagnostics.append((
                fractal.detected_at_position,
                SegmentDiagnostic(
                    code="FEATURE_FRACTAL_WAIT_ACTUAL_BREAK",
                    message=(
                        f"{fractal.dt.isoformat()} 已形成特征分型形态，"
                        "但当前位于数据尾部，真实突破证据尚不完整，暂不确认线段"
                    ),
                    dt=fractal.dt,
                ),
            ))
            continue
        if fractal.break_status is FeatureBreakStatus.REJECTED:
            candidate_diagnostics.append((
                fractal.detected_at_position,
                SegmentDiagnostic(
                    code="FEATURE_FRACTAL_REJECTED_NO_ACTUAL_BREAK",
                    message=(
                        f"{fractal.dt.isoformat()} 的特征分型已被充分后续数据否定："
                        "没有形成真实突破，重置标准特征序列并继续扫描"
                    ),
                    dt=fractal.dt,
                ),
            ))
            continue
        if not _candidate_can_end(strokes, start_position, fractal.endpoint_position):
            candidate_diagnostics.append((
                fractal.detected_at_position,
                SegmentDiagnostic(
                    code="FEATURE_FRACTAL_TOO_EARLY",
                    message="特征分型对应端点尚不满足线段至少三笔与首三笔重叠",
                    dt=fractal.dt,
                ),
            ))
            continue
        valid_confirmed.append(fractal)

    if not valid_confirmed:
        cutoff = len(strokes) - 1
        return _ScanOutcome(
            start_position=start_position,
            end_position=None,
            primary=last_candidate,
            reverse=None,
            confirmation=None,
            confirmed_at_position=None,
            elements=_elements_through(primary_trace.elements, cutoff),
            fractals=_fractals_through(primary_trace.fractals, cutoff),
            diagnostics=_diagnostics_through(candidate_diagnostics, cutoff),
        )

    first_time = min(x.detected_at_position for x in valid_confirmed)
    first_group = [x for x in valid_confirmed if x.detected_at_position == first_time]
    first = _most_extreme_candidate(first_group, direction)
    if not first.gap:
        return _ScanOutcome(
            start_position=start_position,
            end_position=first.endpoint_position,
            primary=first,
            reverse=None,
            confirmation="NO_GAP",
            confirmed_at_position=first.detected_at_position,
            elements=_elements_through(primary_trace.elements, first.detected_at_position),
            fractals=_fractals_through(primary_trace.fractals, first.detected_at_position),
            diagnostics=_diagnostics_through(
                candidate_diagnostics, first.detected_at_position
            ),
            final_endpoint=strokes[first.endpoint_position].fx_a,
        )

    gap_origin = first
    active_position = first.endpoint_position
    active_endpoint = strokes[active_position].fx_a
    reverse_attempts: list[_ReverseAttempt] = []
    active_reverse = _start_reverse_attempt(
        strokes,
        direction,
        endpoint_position=active_position,
        active_from=first.detected_at_position,
    )
    reverse_attempts.append(active_reverse)
    diagnostics.append(
        SegmentDiagnostic(
            code="FEATURE_GAP_WAIT_REVERSE",
            message=(
                f"{first.dt.isoformat()} 的主特征分型第一、二元素有缺口，"
                "进入主特征确认与反向特征确认竞争状态；等待期间持续跟踪"
                "同类极值端点，并继续接收后续无缺口主分型"
            ),
            dt=first.dt,
        )
    )

    primary_events: dict[int, list[FeatureFractal]] = {}
    for candidate in valid_confirmed:
        if candidate.detected_at_position <= first.detected_at_position:
            continue
        primary_events.setdefault(candidate.detected_at_position, []).append(candidate)

    feature_direction = _opposite(direction)
    for position in range(first.endpoint_position + 1, len(strokes)):
        # 严格早于当前位置完成的反向确认已经生效。若确认与当前位置的主分型
        # 同时发生，则先处理主分型，使无缺口确认拥有同一时刻的优先权。
        if (
            active_reverse.confirmed is not None
            and active_reverse.confirmed.detected_at_position < position
        ):
            return _gap_outcome(
                strokes=strokes,
                start_position=start_position,
                end_position=active_position,
                gap_origin=gap_origin,
                primary_candidates=valid_confirmed,
                reverse_attempts=reverse_attempts,
                active_reverse=active_reverse,
                primary_trace=primary_trace,
                candidate_diagnostics=candidate_diagnostics,
                diagnostics=diagnostics,
            )

        stroke = strokes[position]
        if stroke.direction is feature_direction:
            endpoint = stroke.fx_a
            if endpoint.mark is gap_origin.mark and _is_more_extreme_endpoint(
                endpoint,
                active_endpoint,
                direction,
                position=position,
                current_position=active_position,
            ):
                active_reverse.active_until = position
                diagnostics.append(
                    SegmentDiagnostic(
                        code="GAP_PRIMARY_ENDPOINT_REPLACED",
                        message=(
                            f"有缺口候选等待确认期间，线段端点由第 "
                            f"{active_position} 笔 {active_endpoint.value:.12g} 迁移到第 "
                            f"{position} 笔 {endpoint.value:.12g}；旧反向序列作废，"
                            "并从新极值端点重新开始"
                        ),
                        dt=endpoint.dt,
                    )
                )
                active_position = position
                active_endpoint = endpoint
                active_reverse = _start_reverse_attempt(
                    strokes,
                    direction,
                    endpoint_position=active_position,
                    active_from=position,
                )
                reverse_attempts.append(active_reverse)

        # 主特征序列在缺口等待期间仍持续工作。有效无缺口候选是直接确认
        # 事件；若它在反向确认之前出现，必须立即结束当前线段。
        event_group = primary_events.get(position, ())
        if event_group:
            no_gap_group = [x for x in event_group if not x.gap]
            if no_gap_group:
                no_gap = _most_extreme_candidate(no_gap_group, direction)
                if no_gap.endpoint_position == active_position or _is_more_extreme_endpoint(
                    no_gap.endpoint,
                    active_endpoint,
                    direction,
                    position=no_gap.endpoint_position,
                    current_position=active_position,
                ):
                    return _no_gap_after_gap_outcome(
                        strokes=strokes,
                        start_position=start_position,
                        candidate=no_gap,
                        gap_origin=gap_origin,
                        reverse_attempts=reverse_attempts,
                        primary_trace=primary_trace,
                        candidate_diagnostics=candidate_diagnostics,
                        diagnostics=diagnostics,
                    )
                diagnostics.append(
                    SegmentDiagnostic(
                        code="NO_GAP_PRIMARY_SUPERSEDED_BEFORE_CONFIRMATION",
                        message=(
                            f"第 {no_gap.endpoint_position} 笔的无缺口主分型在第 "
                            f"{position} 笔确认时，已被第 {active_position} 笔的更极端"
                            "同类端点取代，因此不用于结束线段"
                        ),
                        dt=no_gap.dt,
                    )
                )

            # 后续有缺口主分型若对应当前或更极端端点，仍保留为可审计主
            # 候选。实际端点迁移通常已在其 endpoint_position 处完成。
            gap_group = [x for x in event_group if x.gap]
            if gap_group:
                gap_candidate = _most_extreme_candidate(gap_group, direction)
                if _is_more_extreme_endpoint(
                    gap_candidate.endpoint,
                    active_endpoint,
                    direction,
                    position=gap_candidate.endpoint_position,
                    current_position=active_position,
                ):
                    active_reverse.active_until = position
                    active_position = gap_candidate.endpoint_position
                    active_endpoint = gap_candidate.endpoint
                    active_reverse = _start_reverse_attempt(
                        strokes,
                        direction,
                        endpoint_position=active_position,
                        active_from=position,
                    )
                    reverse_attempts.append(active_reverse)

        if (
            active_reverse.confirmed is not None
            and active_reverse.confirmed.detected_at_position <= position
        ):
            return _gap_outcome(
                strokes=strokes,
                start_position=start_position,
                end_position=active_position,
                gap_origin=gap_origin,
                primary_candidates=valid_confirmed,
                reverse_attempts=reverse_attempts,
                active_reverse=active_reverse,
                primary_trace=primary_trace,
                candidate_diagnostics=candidate_diagnostics,
                diagnostics=diagnostics,
            )

    if active_reverse.confirmed is not None:
        return _gap_outcome(
            strokes=strokes,
            start_position=start_position,
            end_position=active_position,
            gap_origin=gap_origin,
            primary_candidates=valid_confirmed,
            reverse_attempts=reverse_attempts,
            active_reverse=active_reverse,
            primary_trace=primary_trace,
            candidate_diagnostics=candidate_diagnostics,
            diagnostics=diagnostics,
        )

    diagnostics.append(
        SegmentDiagnostic(
            code="REVERSE_FEATURE_WAIT_CONFIRMATION",
            message=(
                f"第 {active_position} 笔的最新极值端点尚未得到反向标准特征序列"
                "或后续无缺口主分型确认，保留为未完成线段"
            ),
            dt=active_endpoint.dt,
        )
    )
    cutoff = len(strokes) - 1
    elements = _elements_through(primary_trace.elements, cutoff)
    fractals = _fractals_through(primary_trace.fractals, cutoff)
    elements.extend(_reverse_elements_through((active_reverse,), cutoff))
    fractals.extend(_reverse_fractals_through((active_reverse,), cutoff))
    primary = _primary_for_endpoint(
        valid_confirmed, active_position, cutoff, fallback=gap_origin
    )
    return _ScanOutcome(
        start_position=start_position,
        end_position=None,
        primary=primary,
        reverse=None,
        confirmation=None,
        confirmed_at_position=None,
        elements=elements,
        fractals=fractals,
        diagnostics=[
            *_diagnostics_through(candidate_diagnostics, cutoff),
            *diagnostics,
        ],
        gap_origin=gap_origin,
        final_endpoint=active_endpoint,
    )

def _trace_feature_detector(
    strokes: Sequence[Stroke],
    *,
    segment_direction: StrokeDirection,
    sequence_start_position: int,
    feed_start: int,
) -> _DetectorTrace:
    """完整回放一个标准特征序列检测器并收集所有候选事件。"""
    detector = _FeatureDetector(
        strokes,
        segment_direction=segment_direction,
        sequence_start_position=sequence_start_position,
        require_actual_break=True,
    )
    candidates: list[FeatureFractal] = []
    seen: set[tuple] = set()
    position = feed_start
    pending: FeatureFractal | None = None
    guard = max(32, len(strokes) * 8)
    steps = 0
    while position < len(strokes) or pending is not None:
        steps += 1
        if steps > guard:  # pragma: no cover - 状态机死循环防御
            raise RuntimeError("标准特征序列回放超过安全步数")
        if pending is not None:
            fractal = pending
            pending = None
        else:
            fractal = detector.add_position(position)
            position += 1
        if fractal is None:
            continue
        signature = _feature_fractal_signature(fractal)
        if signature not in seen:
            seen.add(signature)
            candidates.append(fractal)
        pending = detector._reset_and_replay()

    return _DetectorTrace(
        candidates=candidates,
        elements=list(detector.audit_elements),
        fractals=list(detector.audit_fractals),
    )


def _start_reverse_attempt(
    strokes: Sequence[Stroke],
    direction: StrokeDirection,
    *,
    endpoint_position: int,
    active_from: int,
) -> _ReverseAttempt:
    trace = _trace_feature_detector(
        strokes,
        segment_direction=_opposite(direction),
        sequence_start_position=endpoint_position,
        feed_start=endpoint_position + 1,
    )
    confirmed = next(
        (
            fractal
            for fractal in sorted(
                trace.candidates,
                key=lambda x: (x.detected_at_position, x.endpoint_position),
            )
            if fractal.break_status is FeatureBreakStatus.CONFIRMED
            and fractal.detected_at_position >= active_from
        ),
        None,
    )
    return _ReverseAttempt(
        endpoint_position=endpoint_position,
        endpoint=strokes[endpoint_position].fx_a,
        trace=trace,
        confirmed=confirmed,
        active_from=active_from,
    )



def _no_gap_after_gap_outcome(
    *,
    strokes: Sequence[Stroke],
    start_position: int,
    candidate: FeatureFractal,
    gap_origin: FeatureFractal,
    reverse_attempts: Sequence[_ReverseAttempt],
    primary_trace: _DetectorTrace,
    candidate_diagnostics: Sequence[tuple[int, SegmentDiagnostic]],
    diagnostics: list[SegmentDiagnostic],
) -> _ScanOutcome:
    """缺口等待期间由后续无缺口主分型直接确认线段。"""
    cutoff = candidate.detected_at_position
    diagnostics = [
        *diagnostics,
        SegmentDiagnostic(
            code="GAP_WAIT_CONFIRMED_BY_LATER_NO_GAP_PRIMARY",
            message=(
                f"首个有缺口主分型端点第 {gap_origin.endpoint_position} 笔进入等待后，"
                f"第 {candidate.endpoint_position} 笔在第 {cutoff} 笔形成已确认无缺口"
                "主分型；无缺口确认先于反向确认，立即结束当前线段"
            ),
            dt=candidate.dt,
        ),
    ]
    elements = _elements_through(primary_trace.elements, cutoff)
    fractals = _fractals_through(primary_trace.fractals, cutoff)
    elements.extend(_reverse_elements_through(reverse_attempts, cutoff))
    fractals.extend(_reverse_fractals_through(reverse_attempts, cutoff))
    return _ScanOutcome(
        start_position=start_position,
        end_position=candidate.endpoint_position,
        primary=candidate,
        reverse=None,
        confirmation="NO_GAP",
        confirmed_at_position=cutoff,
        elements=elements,
        fractals=fractals,
        diagnostics=[
            *_diagnostics_through(candidate_diagnostics, cutoff),
            *diagnostics,
        ],
        gap_origin=gap_origin,
        final_endpoint=candidate.endpoint,
    )

def _gap_outcome(
    *,
    strokes: Sequence[Stroke],
    start_position: int,
    end_position: int,
    gap_origin: FeatureFractal,
    primary_candidates: Sequence[FeatureFractal],
    reverse_attempts: Sequence[_ReverseAttempt],
    active_reverse: _ReverseAttempt,
    primary_trace: _DetectorTrace,
    candidate_diagnostics: Sequence[tuple[int, SegmentDiagnostic]],
    diagnostics: list[SegmentDiagnostic],
) -> _ScanOutcome:
    reverse = active_reverse.confirmed
    if reverse is None:  # pragma: no cover - 调用方不变量
        raise RuntimeError("缺口确认结果缺少反向特征分型")
    cutoff = reverse.detected_at_position
    primary = _primary_for_endpoint(
        primary_candidates, end_position, cutoff, fallback=gap_origin
    )
    elements = _elements_through(primary_trace.elements, cutoff)
    fractals = _fractals_through(primary_trace.fractals, cutoff)
    elements.extend(_reverse_elements_through((active_reverse,), cutoff))
    fractals.extend(_reverse_fractals_through((active_reverse,), cutoff))
    return _ScanOutcome(
        start_position=start_position,
        end_position=end_position,
        primary=primary,
        reverse=reverse,
        confirmation="GAP_REVERSE_FRACTAL",
        confirmed_at_position=cutoff,
        elements=elements,
        fractals=fractals,
        diagnostics=[
            *_diagnostics_through(candidate_diagnostics, cutoff),
            *diagnostics,
        ],
        gap_origin=gap_origin,
        final_endpoint=strokes[end_position].fx_a,
    )


def _primary_for_endpoint(
    candidates: Sequence[FeatureFractal],
    endpoint_position: int,
    cutoff: int,
    *,
    fallback: FeatureFractal,
) -> FeatureFractal:
    matches = [
        x
        for x in candidates
        if x.endpoint_position == endpoint_position
        and x.detected_at_position <= cutoff
        and x.break_status is FeatureBreakStatus.CONFIRMED
    ]
    if not matches:
        return fallback
    return max(matches, key=lambda x: (x.detected_at_position, x.middle.last_stroke_position))


def _most_extreme_candidate(
    candidates: Sequence[FeatureFractal], direction: StrokeDirection
) -> FeatureFractal:
    if direction is StrokeDirection.UP:
        return max(
            candidates,
            key=lambda x: (x.value, x.endpoint_position, -x.detected_at_position),
        )
    return min(
        candidates,
        key=lambda x: (x.value, -x.endpoint_position, x.detected_at_position),
    )


def _is_more_extreme_endpoint(
    candidate: Fractal,
    current: Fractal,
    direction: StrokeDirection,
    *,
    position: int,
    current_position: int,
) -> bool:
    if direction is StrokeDirection.UP:
        return candidate.value > current.value + _EPS or (
            abs(candidate.value - current.value) <= _EPS and position > current_position
        )
    return candidate.value < current.value - _EPS or (
        abs(candidate.value - current.value) <= _EPS and position > current_position
    )



def _diagnostics_through(
    values: Sequence[tuple[int, SegmentDiagnostic]], cutoff: int
) -> list[SegmentDiagnostic]:
    return [diagnostic for detected_at, diagnostic in values if detected_at <= cutoff]

def _elements_through(
    elements: Sequence[FeatureElement], cutoff: int
) -> list[FeatureElement]:
    return [x for x in elements if x.last_stroke_position <= cutoff]


def _fractals_through(
    fractals: Sequence[FeatureFractal], cutoff: int
) -> list[FeatureFractal]:
    return [x for x in fractals if x.detected_at_position <= cutoff]


def _reverse_elements_through(
    attempts: Sequence[_ReverseAttempt], cutoff: int
) -> list[FeatureElement]:
    output: list[FeatureElement] = []
    for attempt in attempts:
        active_cutoff = min(cutoff, attempt.active_until if attempt.active_until is not None else cutoff)
        output.extend(_elements_through(attempt.trace.elements, active_cutoff))
    return output


def _reverse_fractals_through(
    attempts: Sequence[_ReverseAttempt], cutoff: int
) -> list[FeatureFractal]:
    output: list[FeatureFractal] = []
    for attempt in attempts:
        active_cutoff = min(cutoff, attempt.active_until if attempt.active_until is not None else cutoff)
        output.extend(_fractals_through(attempt.trace.fractals, active_cutoff))
    return output


def _feature_fractal_signature(fractal: FeatureFractal) -> tuple:
    return (
        fractal.segment_direction,
        fractal.mark,
        fractal.endpoint_position,
        fractal.detected_at_position,
        fractal.gap,
        fractal.break_status,
        fractal.left.stroke_positions,
        fractal.middle.stroke_positions,
        fractal.right.stroke_positions,
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


def _dedupe_diagnostics(values: Iterable[SegmentDiagnostic]) -> list[SegmentDiagnostic]:
    result: list[SegmentDiagnostic] = []
    seen: set[tuple] = set()
    for value in values:
        key = (value.code, value.dt, value.message)
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


def detect_segments_from_anchor(
    strokes: Sequence[Stroke],
    *,
    start_position: int,
    mode: SegmentMode | str = SegmentMode.FEATURE_SEQUENCE,
    exclude_last_stroke_confirmation: bool = True,
) -> SegmentDetectionResult:
    """从一个已经稳定的线段端点继续识别后续线段。

    与 :func:`detect_segments` 的区别是：这里不再重新猜测首段起点，而把
    ``start_position`` 当作已确认共享端点，直接运行标准特征序列状态机。
    该接口用于增量结构提交，避免截取尾部后因缺失前置上下文而改变首段。
    """
    resolved_mode = SegmentMode(mode)
    values = tuple(strokes)
    if start_position < 0 or start_position >= len(values):
        raise ValueError("start_position 超出笔链范围")
    endpoints = stroke_endpoints(values)
    segments: list[Segment] = []
    markers: list[Fractal] = [endpoints[start_position]]
    evidence: list[SegmentEvidence] = []
    all_elements: list[FeatureElement] = []
    all_fractals: list[FeatureFractal] = []
    diagnostics: list[SegmentDiagnostic] = []
    start = start_position
    last_scan_start = start
    current = _scan_segment(values, endpoints, start)

    while True:
        # 无论本轮是否形成完整线段，都必须保留扫描到的特征元素、特征分型和诊断。
        # 否则锚点模式会在最后一个“进行中的线段”处丢弃尾部扫描结果，进而让
        # validate_feature_sequence_coverage() 误报状态机提前停止。
        all_elements.extend(current.elements)
        all_fractals.extend(current.fractals)
        diagnostics.extend(current.diagnostics)

        if current.end_position is None or current.primary is None:
            break

        end = current.end_position
        if (
            exclude_last_stroke_confirmation
            and _confirmation_uses_reversible_last_stroke(current, len(values))
        ):
            diagnostics.append(SegmentDiagnostic(
                code="SEGMENT_CONFIRMATION_USES_REVERSIBLE_LAST_STROKE",
                message=(
                    f"候选线段 {start}→{end} 的确认发生在当前最后一笔 "
                    f"{current.confirmed_at_position}；暂保留为候选"
                ),
                dt=endpoints[end].dt,
            ))
            last_scan_start = start
            break
        if not _candidate_can_end(values, start, end):
            diagnostics.append(SegmentDiagnostic(
                code="SEGMENT_CANDIDATE_INVALID",
                message=f"候选端点 {end} 未满足线段几何条件",
                dt=endpoints[end].dt,
            ))
            break

        segment = _make_segment(values, endpoints, start, end, len(segments))
        segments.append(segment)
        markers.append(endpoints[end])
        evidence.append(SegmentEvidence(
            segment_index=segment.index,
            start_position=start,
            end_position=end,
            confirmation=current.confirmation or "UNKNOWN",
            primary_fractal=current.primary,
            reverse_fractal=current.reverse,
            gap_origin_fractal=current.gap_origin,
            final_endpoint=current.final_endpoint or endpoints[end],
            segment_symbol=segment.symbol,
            segment_interval=segment.interval,
            segment_fingerprint=segment.fingerprint,
            confirmation_available_at=_stroke_available_at(
                values[current.confirmed_at_position]
            ),
            confirmation_stroke_fingerprint=stroke_fingerprint(
                values[current.confirmed_at_position]
            ),
        ))
        start = end
        last_scan_start = start
        if len(values) - start < 3:
            break
        current = _scan_segment(values, endpoints, start)

    return SegmentDetectionResult(
        segments=tuple(segments),
        markers=tuple(markers),
        candidates=tuple(_dedupe_fractals(x.endpoint for x in all_fractals)),
        unfinished_strokes=tuple(values[last_scan_start:]),
        unresolved_prefix_strokes=(),
        feature_elements=_unique_feature_elements(all_elements),
        feature_fractals=_unique_feature_fractals(all_fractals),
        evidence=tuple(evidence),
        diagnostics=tuple(diagnostics),
        mode=resolved_mode,
    )
