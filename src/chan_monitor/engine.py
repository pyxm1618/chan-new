from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

from .central_zones import detect_central_zones
from .segment_central_zones import detect_segment_central_zones
from .trading_points import detect_trading_points
from .fractals import detect_fractals, remove_inclusions
from .metadata import AnalysisMetadata
from .models import (
    Fractal,
    FractalDiagnostic,
    MergedBar,
    RawBar,
    Stroke,
    StrokeDiagnostic,
    Segment,
    SegmentDiagnostic,
    FeatureElement,
    FeatureFractal,
    SegmentEvidence,
    CentralZone,
    CentralZoneDiagnostic,
    SegmentCentralZone,
    SegmentCentralZoneDiagnostic,
    TradingPoint,
    TradingPointCandidate,
    TrendDivergence,
    TradingPointDiagnostic,
)
from .strokes import DEFAULT_MIN_BI_LEN, StrokeDetectionResult, _StrokeState
from .segments import (
    SegmentMode,
    SegmentDetectionResult,
    detect_segments,
    detect_segments_from_anchor,
)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    raw_bars: tuple[RawBar, ...]
    merged_bars: tuple[MergedBar, ...]
    fractals: tuple[Fractal, ...]
    # 兼容旧 API：完整规范笔链 = stable_strokes + provisional_strokes。
    strokes: tuple[Stroke, ...]
    # 无提交边界约束的原始笔状态机结果，仅用于审计级联回退。
    detected_strokes: tuple[Stroke, ...]
    # 由结构确认事件封存、只增不减的笔前缀。
    stable_strokes: tuple[Stroke, ...]
    # 仍可能迁移或撤销的连续尾部。
    provisional_strokes: tuple[Stroke, ...]
    unfinished_bars: tuple[MergedBar, ...]
    # 正式线段：下一条线段已经出现后才提交，append-only。
    segments: tuple[Segment, ...]
    # 当前完整笔链上的直接识别结果，允许尾部变化，仅用于候选与算法审计。
    detected_segments: tuple[Segment, ...]
    detected_segment_evidence: tuple[SegmentEvidence, ...]
    # 当前完整笔链上已经识别、但尚未达到提交条件的尾部线段。
    provisional_segments: tuple[Segment, ...]
    segment_markers: tuple[Fractal, ...]
    segment_candidates: tuple[Fractal, ...]
    unfinished_segment_strokes: tuple[Stroke, ...]
    detected_unfinished_segment_strokes: tuple[Stroke, ...]
    unresolved_segment_prefix_strokes: tuple[Stroke, ...]
    feature_elements: tuple[FeatureElement, ...]
    feature_fractals: tuple[FeatureFractal, ...]
    segment_evidence: tuple[SegmentEvidence, ...]
    central_zones: tuple[CentralZone, ...]
    central_zone_groups: tuple[CentralZone, ...]
    # 全部当前笔形成的中枢仅作为候选，不能冒充正式中枢。
    central_zone_candidates: tuple[CentralZone, ...]
    central_zone_candidate_groups: tuple[CentralZone, ...]
    segment_central_zones: tuple[SegmentCentralZone, ...]
    detected_segment_central_zones: tuple[SegmentCentralZone, ...]
    segment_central_zone_candidates: tuple[SegmentCentralZone, ...]
    trading_points: tuple[TradingPoint, ...]
    trading_point_candidates: tuple[TradingPointCandidate, ...]
    trend_divergences: tuple[TrendDivergence, ...]
    diagnostics: tuple[FractalDiagnostic, ...]
    stroke_diagnostics: tuple[StrokeDiagnostic, ...]
    segment_diagnostics: tuple[SegmentDiagnostic, ...]
    central_zone_diagnostics: tuple[CentralZoneDiagnostic, ...]
    segment_central_zone_diagnostics: tuple[SegmentCentralZoneDiagnostic, ...]
    trading_point_diagnostics: tuple[TradingPointDiagnostic, ...]
    merge_count: int
    min_bi_len: int
    segment_mode: SegmentMode
    metadata: AnalysisMetadata

    @property
    def all_strokes(self) -> tuple[Stroke, ...]:
        return self.strokes


@dataclass(slots=True)
class StructureState:
    """增量维护“稳定前缀 + 可回撤尾部”。

    笔本身没有一个仅靠固定尾部长度即可证明永久稳定的条件。这里采用分层
    提交：当前尾部识别出连续两条线段后，只提交倒数第二条及更早线段；最后
    一条始终留在 provisional 区。提交线段所依赖的确认笔前缀同时被封存。

    这等价于明确的两阶段状态机：

    ``DETECTED -> (next segment detected) -> COMMITTED``

    因而不会再使用 ``strokes[:-1]`` / ``strokes[:-N]`` 这种经验窗口。
    """

    min_bi_len: int
    segment_mode: SegmentMode
    stroke_state: _StrokeState = field(init=False)
    stable_strokes: tuple[Stroke, ...] = ()
    segments: tuple[Segment, ...] = ()
    evidence: tuple[SegmentEvidence, ...] = ()
    provisional_segments: tuple[Segment, ...] = ()
    diagnostics: list[SegmentDiagnostic] = field(default_factory=list)
    _last_scan_key: tuple = ()

    def __post_init__(self) -> None:
        self.stroke_state = _StrokeState(min_bi_len=self.min_bi_len)

    def update(self, bar: RawBar) -> None:
        self.stroke_state.update(bar)
        canonical = self.canonical_strokes
        scan_key = tuple(_stroke_key(x) for x in canonical)
        if scan_key == self._last_scan_key:
            return
        self._last_scan_key = scan_key
        self._advance_commits(canonical)

    @property
    def detected_strokes(self) -> tuple[Stroke, ...]:
        return tuple(self.stroke_state.strokes)

    @property
    def canonical_strokes(self) -> tuple[Stroke, ...]:
        return self._compose_canonical_strokes(self.detected_strokes)

    @property
    def provisional_strokes(self) -> tuple[Stroke, ...]:
        return self.canonical_strokes[len(self.stable_strokes):]

    @property
    def stroke_result(self) -> StrokeDetectionResult:
        return StrokeDetectionResult(
            strokes=self.canonical_strokes,
            unfinished_bars=tuple(self.stroke_state.bars_ubi),
            diagnostics=tuple(self.stroke_state.diagnostics),
        )

    def _advance_commits(self, canonical: tuple[Stroke, ...]) -> None:
        if not canonical:
            self.provisional_segments = ()
            return

        if self.evidence:
            detected = detect_segments_from_anchor(
                canonical,
                start_position=self.evidence[-1].end_position,
                mode=self.segment_mode,
                exclude_last_stroke_confirmation=True,
            )
        else:
            detected = detect_segments(
                canonical,
                mode=self.segment_mode,
                exclude_last_stroke_confirmation=True,
            )

        if not detected.segments:
            self.provisional_segments = ()
            return

        # 当前识别出的最后一条仍是 DETECTED。只有后续又形成一条线段，
        # 前面的线段才由结构事件推进为 COMMITTED。
        commit_count = max(0, len(detected.segments) - 1)
        provisional = detected.segments[commit_count:]
        self.provisional_segments = tuple(
            _reindex_segment(item, len(self.segments) + i)
            for i, item in enumerate(provisional)
        )
        if commit_count == 0:
            return

        new_segments: list[Segment] = []
        new_evidence: list[SegmentEvidence] = []
        for i in range(commit_count):
            segment = _reindex_segment(detected.segments[i], len(self.segments) + i)
            evidence = detected.evidence[i]
            evidence = SegmentEvidence(
                segment_index=segment.index,
                start_position=evidence.start_position,
                end_position=evidence.end_position,
                confirmation=evidence.confirmation,
                primary_fractal=evidence.primary_fractal,
                reverse_fractal=evidence.reverse_fractal,
                gap_origin_fractal=evidence.gap_origin_fractal,
                final_endpoint=evidence.final_endpoint,
            )
            new_segments.append(segment)
            new_evidence.append(evidence)

        if self.segments and new_segments[0].start_dt != self.segments[-1].end_dt:
            self.diagnostics.append(SegmentDiagnostic(
                code="CONFIRMED_SEGMENT_DIVERGENCE_IGNORED",
                message="临时线段不能与已确认线段端点连续，拒绝提交并保留历史前缀",
                dt=new_segments[0].start_dt,
            ))
            return

        self.segments = self.segments + tuple(new_segments)
        self.evidence = self.evidence + tuple(new_evidence)

        target_count = max(x.confirmed_at_position for x in new_evidence) + 1
        if target_count > len(canonical):
            raise RuntimeError("线段确认位置超出当前笔链")
        candidate_prefix = canonical[:target_count]
        if self.stable_strokes and not _stroke_prefix_equal(
            self.stable_strokes,
            candidate_prefix[: len(self.stable_strokes)],
        ):
            raise RuntimeError("新确认线段试图改写已稳定笔前缀")
        self.stable_strokes = tuple(candidate_prefix)

        self.provisional_segments = tuple(
            _reindex_segment(item, len(self.segments) + i)
            for i, item in enumerate(provisional)
        )

    def _compose_canonical_strokes(
        self,
        detected: tuple[Stroke, ...],
    ) -> tuple[Stroke, ...]:
        if not self.stable_strokes:
            return _reindex_strokes(detected)

        stable = self.stable_strokes
        common = _common_stroke_prefix_length(stable, detected)
        if common == len(stable):
            return _reindex_strokes(stable + detected[len(stable):])

        # 原始检测链若试图穿过提交点，稳定前缀保持原值；临时尾部只能从最后
        # 稳定共享端点重新接入。找不到时宁可暂时不输出 provisional tail。
        endpoint_key = _fractal_key(stable[-1].fx_b)
        reconnect_at = next(
            (
                i for i, stroke in enumerate(detected)
                if _fractal_key(stroke.fx_a) == endpoint_key
            ),
            None,
        )
        tail = detected[reconnect_at:] if reconnect_at is not None else ()
        return _reindex_strokes(stable + tuple(tail))


def analyze_bars(
    raw_bars: Iterable[RawBar],
    *,
    czsc_compatibility: bool = True,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
    metadata: AnalysisMetadata | None = None,
    segment_mode: SegmentMode | str = SegmentMode.FEATURE_SEQUENCE,
) -> AnalysisResult:
    bars = tuple(raw_bars)
    resolved_mode = SegmentMode(segment_mode)
    state = StructureState(min_bi_len=min_bi_len, segment_mode=resolved_mode)
    for bar in bars:
        state.update(bar)
    return _build_analysis_result(
        bars,
        state,
        czsc_compatibility=czsc_compatibility,
        min_bi_len=min_bi_len,
        metadata=metadata or AnalysisMetadata(),
        segment_mode=resolved_mode,
    )


def _build_analysis_result(
    bars: tuple[RawBar, ...],
    state: StructureState,
    *,
    czsc_compatibility: bool,
    min_bi_len: int,
    metadata: AnalysisMetadata,
    segment_mode: SegmentMode,
) -> AnalysisResult:
    merged, merge_count = remove_inclusions(bars)
    fractals, diagnostics = detect_fractals(merged, czsc_compatibility=czsc_compatibility)
    stroke_result = state.stroke_result
    all_strokes = stroke_result.strokes
    stable_strokes = state.stable_strokes
    provisional_strokes = state.provisional_strokes

    live_segment_result = detect_segments(
        all_strokes,
        mode=segment_mode,
        exclude_last_stroke_confirmation=True,
    )
    formal_cz = detect_central_zones(stable_strokes)
    candidate_cz = detect_central_zones(all_strokes)
    segment_cz = detect_segment_central_zones(state.segments)
    detected_segment_cz = detect_segment_central_zones(live_segment_result.segments)
    formal_segment_keys = tuple(_segment_key(x) for x in state.segments)
    detected_segment_keys = tuple(_segment_key(x) for x in live_segment_result.segments)
    if detected_segment_keys[: len(formal_segment_keys)] == formal_segment_keys:
        provisional_segments = live_segment_result.segments[len(formal_segment_keys):]
    else:
        provisional_segments = state.provisional_segments
    trading = detect_trading_points(
        state.segments,
        segment_cz.zones,
        raw_bars=bars,
        segment_evidence=state.evidence,
        strokes=stable_strokes,
    )

    last_end = state.evidence[-1].end_position if state.evidence else 0
    unfinished = all_strokes[last_end:] if all_strokes else ()

    return AnalysisResult(
        raw_bars=bars,
        merged_bars=tuple(merged),
        fractals=tuple(fractals),
        strokes=all_strokes,
        detected_strokes=state.detected_strokes,
        stable_strokes=stable_strokes,
        provisional_strokes=provisional_strokes,
        unfinished_bars=stroke_result.unfinished_bars,
        segments=state.segments,
        detected_segments=live_segment_result.segments,
        detected_segment_evidence=live_segment_result.evidence,
        provisional_segments=tuple(provisional_segments),
        segment_markers=_segment_markers(state.segments),
        segment_candidates=live_segment_result.candidates,
        unfinished_segment_strokes=tuple(unfinished),
        detected_unfinished_segment_strokes=live_segment_result.unfinished_strokes,
        unresolved_segment_prefix_strokes=live_segment_result.unresolved_prefix_strokes,
        feature_elements=live_segment_result.feature_elements,
        feature_fractals=live_segment_result.feature_fractals,
        segment_evidence=state.evidence,
        central_zones=formal_cz.zones,
        central_zone_groups=formal_cz.groups,
        central_zone_candidates=candidate_cz.zones,
        central_zone_candidate_groups=candidate_cz.groups,
        segment_central_zones=segment_cz.zones,
        detected_segment_central_zones=detected_segment_cz.zones,
        segment_central_zone_candidates=tuple(
            list(detected_segment_cz.zones[len(segment_cz.zones):])
            + list(detected_segment_cz.candidates)
        ),
        trading_points=trading.points,
        trading_point_candidates=trading.candidates,
        trend_divergences=trading.trend_divergences,
        diagnostics=tuple(diagnostics),
        stroke_diagnostics=stroke_result.diagnostics,
        segment_diagnostics=tuple(live_segment_result.diagnostics) + tuple(state.diagnostics),
        central_zone_diagnostics=formal_cz.diagnostics,
        segment_central_zone_diagnostics=segment_cz.diagnostics,
        trading_point_diagnostics=trading.diagnostics,
        merge_count=merge_count,
        min_bi_len=min_bi_len,
        segment_mode=segment_mode,
        metadata=metadata,
    )


@dataclass(slots=True)
class FractalEngine:
    """真正的增量结构引擎。

    追加新 K 时直接推进笔状态与结构提交账本；只有修订最后一根 K 时才从头
    重放，避免逐根前缀验证退化为反复全量计算。
    """

    czsc_compatibility: bool = True
    min_bi_len: int = DEFAULT_MIN_BI_LEN
    metadata: AnalysisMetadata = field(default_factory=AnalysisMetadata)
    segment_mode: SegmentMode = SegmentMode.FEATURE_SEQUENCE
    _bars: list[RawBar] = field(default_factory=list)
    _result: AnalysisResult | None = None
    _structure_state: StructureState | None = None

    def _new_state(self) -> StructureState:
        return StructureState(
            min_bi_len=self.min_bi_len,
            segment_mode=SegmentMode(self.segment_mode),
        )

    def _replay(self) -> None:
        self._structure_state = self._new_state()
        for item in self._bars:
            self._structure_state.update(item)

    @property
    def result(self) -> AnalysisResult:
        if self._structure_state is None:
            self._replay()
        if self._result is None:
            self._result = _build_analysis_result(
                tuple(self._bars),
                self._structure_state,
                czsc_compatibility=self.czsc_compatibility,
                min_bi_len=self.min_bi_len,
                metadata=self.metadata,
                segment_mode=SegmentMode(self.segment_mode),
            )
        return self._result

    @property
    def last_open_time(self) -> datetime | None:
        return self._bars[-1].open_time if self._bars else None

    def update(self, bar: RawBar) -> AnalysisResult:
        if not self._bars:
            self._bars.append(bar)
            self._structure_state = self._new_state()
            self._structure_state.update(bar)
        elif bar.open_time > self._bars[-1].open_time:
            self._bars.append(bar)
            if self._structure_state is None:
                self._replay()
            else:
                self._structure_state.update(bar)
        elif bar.open_time == self._bars[-1].open_time:
            self._bars[-1] = bar
            self._replay()
        else:
            raise ValueError("只允许追加新 K 线或修订最后一根 K 线")

        self._result = _build_analysis_result(
            tuple(self._bars),
            self._structure_state,
            czsc_compatibility=self.czsc_compatibility,
            min_bi_len=self.min_bi_len,
            metadata=self.metadata,
            segment_mode=SegmentMode(self.segment_mode),
        )
        return self._result

    def extend(self, bars: Iterable[RawBar]) -> AnalysisResult:
        for bar in bars:
            self.update(bar)
        return self.result


def _fractal_key(fractal: Fractal) -> tuple:
    return (fractal.dt, fractal.mark, fractal.value, fractal.high, fractal.low)


def _stroke_key(stroke: Stroke) -> tuple:
    return (_fractal_key(stroke.fx_a), _fractal_key(stroke.fx_b), stroke.direction)


def _segment_key(segment: Segment) -> tuple:
    return (
        segment.start_dt,
        segment.end_dt,
        segment.start_value,
        segment.end_value,
        segment.direction,
    )


def _common_stroke_prefix_length(left: Sequence[Stroke], right: Sequence[Stroke]) -> int:
    count = 0
    for a, b in zip(left, right):
        if _stroke_key(a) != _stroke_key(b):
            break
        count += 1
    return count


def _stroke_prefix_equal(left: Sequence[Stroke], right: Sequence[Stroke]) -> bool:
    return len(left) == len(right) and _common_stroke_prefix_length(left, right) == len(left)


def _reindex_strokes(strokes: Sequence[Stroke]) -> tuple[Stroke, ...]:
    values: list[Stroke] = []
    for index, stroke in enumerate(strokes):
        if stroke.index == index:
            values.append(stroke)
        else:
            values.append(Stroke(
                symbol=stroke.symbol,
                fx_a=stroke.fx_a,
                fx_b=stroke.fx_b,
                fractals=stroke.fractals,
                direction=stroke.direction,
                bars=stroke.bars,
                index=index,
            ))
    return tuple(values)


def _reindex_segment(segment: Segment, index: int) -> Segment:
    if segment.index == index:
        return segment
    return Segment(
        symbol=segment.symbol,
        fx_a=segment.fx_a,
        fx_b=segment.fx_b,
        direction=segment.direction,
        strokes=segment.strokes,
        index=index,
    )


def _offset_feature_element(item: FeatureElement, offset: int) -> FeatureElement:
    if offset == 0:
        return item
    return FeatureElement(
        symbol=item.symbol,
        segment_direction=item.segment_direction,
        merge_direction=item.merge_direction,
        strokes=item.strokes,
        stroke_positions=tuple(x + offset for x in item.stroke_positions),
        high=item.high,
        low=item.low,
        sequence_start_position=item.sequence_start_position + offset,
        element_index=item.element_index,
    )


def _offset_feature_fractal(item: FeatureFractal | None, offset: int) -> FeatureFractal | None:
    if item is None or offset == 0:
        return item
    return FeatureFractal(
        symbol=item.symbol,
        segment_direction=item.segment_direction,
        mark=item.mark,
        left=_offset_feature_element(item.left, offset),
        middle=_offset_feature_element(item.middle, offset),
        right=_offset_feature_element(item.right, offset),
        endpoint=item.endpoint,
        endpoint_position=item.endpoint_position + offset,
        gap=item.gap,
        break_status=item.break_status,
        detected_at_position=item.detected_at_position + offset,
    )


def _offset_evidence(
    item: SegmentEvidence,
    *,
    position_offset: int,
    segment_index: int,
) -> SegmentEvidence:
    return SegmentEvidence(
        segment_index=segment_index,
        start_position=item.start_position + position_offset,
        end_position=item.end_position + position_offset,
        confirmation=item.confirmation,
        primary_fractal=_offset_feature_fractal(item.primary_fractal, position_offset),
        reverse_fractal=_offset_feature_fractal(item.reverse_fractal, position_offset),
        gap_origin_fractal=_offset_feature_fractal(item.gap_origin_fractal, position_offset),
        final_endpoint=item.final_endpoint,
    )


def _segment_markers(segments: Sequence[Segment]) -> tuple[Fractal, ...]:
    if not segments:
        return ()
    return (segments[0].fx_a,) + tuple(x.fx_b for x in segments)
