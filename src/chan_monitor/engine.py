from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

from .central_zones import CentralZoneDetectionResult, detect_central_zones
from .segment_central_zones import (
    SegmentCentralZoneDetectionResult,
    detect_segment_central_zones,
)
from .trading_points import detect_trading_points
from .fractals import detect_fractals, remove_inclusions
from .metadata import AnalysisMetadata
from .models import (
    Fractal,
    FractalMark,
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
class StructureAnchor:
    """调用方从持久化历史中提供的可信结构端点。

    有限窗口本身无法证明第一条线段的真实相位。只有输入从真实历史起点开始，
    或窗口内包含一个此前已经持久化确认的线段端点时，正式结构才允许输出。
    """

    dt: datetime
    value: float
    mark: FractalMark | None = None


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
    # 同时通过右侧稳定性和左侧历史边界解析的笔。正式中枢只消费该序列。
    resolved_strokes: tuple[Stroke, ...]
    # 仍可能迁移或撤销的连续尾部。
    provisional_strokes: tuple[Stroke, ...]
    unfinished_bars: tuple[MergedBar, ...]
    # 正式线段：左边界可信且下一条线段已经出现后才提交，append-only。
    segments: tuple[Segment, ...]
    # 当前完整笔链上的直接识别结果，允许尾部变化，仅用于候选与算法审计。
    detected_segments: tuple[Segment, ...]
    detected_segment_evidence: tuple[SegmentEvidence, ...]
    # 当前完整笔链上已经识别、但尚未达到提交条件的尾部线段。
    provisional_segments: tuple[Segment, ...]
    # 左边界未解析时，当前窗口中的全部检测线段；只能作为候选展示。
    unresolved_prefix_segments: tuple[Segment, ...]
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
    unresolved_central_zones: tuple[CentralZone, ...]
    unresolved_central_zone_groups: tuple[CentralZone, ...]
    # 全部当前笔形成的中枢仅作为候选，不能冒充正式中枢。
    central_zone_candidates: tuple[CentralZone, ...]
    central_zone_candidate_groups: tuple[CentralZone, ...]
    segment_central_zones: tuple[SegmentCentralZone, ...]
    unresolved_segment_central_zones: tuple[SegmentCentralZone, ...]
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
    left_boundary_resolved: bool
    left_boundary_anchored: bool
    left_anchor: StructureAnchor | None
    metadata: AnalysisMetadata

    @property
    def all_strokes(self) -> tuple[Stroke, ...]:
        return self.strokes


@dataclass(slots=True)
class StructureState:
    """增量维护“稳定前缀 + 可回撤尾部”。

    结构稳定性同时有两条边界：右侧新 K 会使候选笔回撤，左侧有限窗口又
    无法证明首条线段的绝对相位。因此正式结构必须同时满足：

    1. 左侧由真实历史起点或持久化线段端点锚定；
    2. 右侧已经出现下一条线段，使当前线段从 DETECTED 推进到 COMMITTED。

    没有左锚点时，全部线段只进入候选层；有锚点后仍保留最后一条候选线段。
    因而既不使用 ``strokes[:-N]`` 经验裁尾，也不会把任意截断窗口的首段
    当成正式结构。
    """

    min_bi_len: int
    segment_mode: SegmentMode
    # 只有调用方能证明输入从真实历史起点或已持久化结构锚点开始时才可设为 True。
    # 普通有限窗口必须保持 False，首条线段不会进入正式结构。
    left_boundary_anchored: bool = False
    left_anchor: StructureAnchor | None = None
    stroke_state: _StrokeState = field(init=False)
    stable_strokes: tuple[Stroke, ...] = ()
    segments: tuple[Segment, ...] = ()
    evidence: tuple[SegmentEvidence, ...] = ()
    provisional_segments: tuple[Segment, ...] = ()
    unresolved_prefix_segments: tuple[Segment, ...] = ()
    # 真实历史起点为 0；持久化端点锚定时为该端点在当前笔链中的位置。
    resolved_stroke_start_position: int | None = None
    diagnostics: list[SegmentDiagnostic] = field(default_factory=list)
    _last_scan_key: tuple = ()

    def __post_init__(self) -> None:
        if self.left_boundary_anchored and self.left_anchor is not None:
            raise ValueError("left_boundary_anchored 与 left_anchor 不能同时设置")
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
    def resolved_stable_strokes(self) -> tuple[Stroke, ...]:
        """既不会从右侧回撤，也不依赖未知左侧历史的笔序列。"""
        if self.resolved_stroke_start_position is None:
            return ()
        return self.stable_strokes[self.resolved_stroke_start_position :]

    @property
    def unresolved_prefix_strokes(self) -> tuple[Stroke, ...]:
        """当前窗口中位于已恢复左侧锚点之前的笔。"""
        if self.resolved_stroke_start_position is None:
            return self.canonical_strokes
        return self.canonical_strokes[: self.resolved_stroke_start_position]

    @property
    def left_boundary_is_resolved(self) -> bool:
        return self.left_boundary_anchored or self.resolved_stroke_start_position is not None

    @property
    def stroke_result(self) -> StrokeDetectionResult:
        return StrokeDetectionResult(
            strokes=self.canonical_strokes,
            unfinished_bars=tuple(self.stroke_state.bars_ubi),
            diagnostics=tuple(self.stroke_state.diagnostics),
        )

    def _advance_commits(self, canonical: tuple[Stroke, ...]) -> None:
        if not canonical:
            if not self.evidence and self.left_anchor is not None:
                self.resolved_stroke_start_position = None
            self.provisional_segments = ()
            return

        if self.evidence:
            detected = detect_segments_from_anchor(
                canonical,
                start_position=self.evidence[-1].end_position,
                mode=self.segment_mode,
                exclude_last_stroke_confirmation=True,
            )
        elif self.left_boundary_anchored:
            detected = detect_segments(
                canonical,
                mode=self.segment_mode,
                exclude_last_stroke_confirmation=True,
            )
        elif self.left_anchor is not None:
            anchor_position = _find_anchor_position(canonical, self.left_anchor)
            if anchor_position is None:
                # 锚点在首个正式提交前仍可能暂时出现在候选笔链中又消失；
                # 每次都重新匹配，找不到时必须撤销“左边界已解析”状态。
                self.resolved_stroke_start_position = None
                # 候选结构由 AnalysisResult 构建阶段按当前完整笔链计算；状态机
                # 在锚点尚未进入窗口前不做重复全链扫描。
                self.unresolved_prefix_segments = ()
                self.provisional_segments = ()
                return
            self.resolved_stroke_start_position = anchor_position
            detected = detect_segments_from_anchor(
                canonical,
                start_position=anchor_position,
                mode=self.segment_mode,
                exclude_last_stroke_confirmation=True,
            )
        else:
            # 没有真实历史起点，也没有持久化锚点时，有限窗口无法证明任何
            # 一条线段的绝对相位。全部检测结果只进入候选层，绝不提交正式结构。
            self.unresolved_prefix_segments = ()
            self.provisional_segments = ()
            return

        if not detected.segments:
            self.provisional_segments = ()
            return

        # 右边界：最后一条始终是 DETECTED，只有下一条出现后才能提交。
        left_skip = 0
        commit_stop = max(0, len(detected.segments) - 1)
        commit_count = max(0, commit_stop - left_skip)
        provisional_start = max(left_skip, commit_stop)
        provisional = detected.segments[provisional_start:]
        self.provisional_segments = tuple(
            _reindex_segment(item, len(self.segments) + i)
            for i, item in enumerate(provisional)
        )
        if commit_count == 0:
            return

        new_segments: list[Segment] = []
        new_evidence: list[SegmentEvidence] = []
        for i in range(left_skip, commit_stop):
            segment = _reindex_segment(
                detected.segments[i],
                len(self.segments) + len(new_segments),
            )
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

        if self.resolved_stroke_start_position is None:
            self.resolved_stroke_start_position = (
                0
                if self.left_boundary_anchored
                else new_evidence[0].start_position
            )

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
    left_boundary_anchored: bool = False,
    left_anchor: StructureAnchor | None = None,
) -> AnalysisResult:
    bars = tuple(raw_bars)
    resolved_mode = SegmentMode(segment_mode)
    state = StructureState(
        min_bi_len=min_bi_len,
        segment_mode=resolved_mode,
        left_boundary_anchored=left_boundary_anchored,
        left_anchor=left_anchor,
    )
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
    resolved_strokes = state.resolved_stable_strokes
    provisional_strokes = state.provisional_strokes

    live_segment_result = detect_segments(
        all_strokes,
        mode=segment_mode,
        exclude_last_stroke_confirmation=True,
    )
    formal_cz, unresolved_cz = _detect_formal_central_zones(
        resolved_strokes,
        left_boundary_anchored=state.left_boundary_anchored,
    )
    candidate_cz = detect_central_zones(all_strokes)
    segment_cz, unresolved_segment_cz = _detect_formal_segment_central_zones(
        state.segments,
        left_boundary_anchored=state.left_boundary_anchored,
    )
    detected_segment_cz = detect_segment_central_zones(live_segment_result.segments)
    unresolved_prefix_segments, provisional_segments = _partition_detected_segments(
        live_segment_result.segments,
        state.segments,
        left_boundary_resolved=state.left_boundary_is_resolved,
        fallback_unresolved=state.unresolved_prefix_segments,
        fallback_provisional=state.provisional_segments,
    )
    trading = detect_trading_points(
        state.segments,
        segment_cz.zones,
        raw_bars=bars,
        segment_evidence=state.evidence,
        strokes=resolved_strokes,
    )
    left_segment_diagnostics: tuple[SegmentDiagnostic, ...] = ()
    if unresolved_prefix_segments:
        left_segment_diagnostics = (
            SegmentDiagnostic(
                code="UNRESOLVED_LEFT_BOUNDARY_SEGMENT",
                message=(
                    "当前窗口缺少真实历史起点或持久化线段端点锚点；"
                    "全部检测线段仅作为候选，正式线段、中枢和买卖点停止输出"
                ),
                dt=unresolved_prefix_segments[0].start_dt,
            ),
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
        resolved_strokes=resolved_strokes,
        provisional_strokes=provisional_strokes,
        unfinished_bars=stroke_result.unfinished_bars,
        segments=state.segments,
        detected_segments=live_segment_result.segments,
        detected_segment_evidence=live_segment_result.evidence,
        provisional_segments=tuple(provisional_segments),
        unresolved_prefix_segments=tuple(unresolved_prefix_segments),
        segment_markers=_segment_markers(state.segments),
        segment_candidates=live_segment_result.candidates,
        unfinished_segment_strokes=tuple(unfinished),
        detected_unfinished_segment_strokes=live_segment_result.unfinished_strokes,
        unresolved_segment_prefix_strokes=state.unresolved_prefix_strokes,
        feature_elements=live_segment_result.feature_elements,
        feature_fractals=live_segment_result.feature_fractals,
        segment_evidence=state.evidence,
        central_zones=formal_cz.zones,
        central_zone_groups=formal_cz.groups,
        unresolved_central_zones=unresolved_cz.zones,
        unresolved_central_zone_groups=unresolved_cz.groups,
        central_zone_candidates=candidate_cz.zones,
        central_zone_candidate_groups=candidate_cz.groups,
        segment_central_zones=segment_cz.zones,
        unresolved_segment_central_zones=unresolved_segment_cz.zones,
        detected_segment_central_zones=detected_segment_cz.zones,
        segment_central_zone_candidates=_segment_zone_candidates(
            detected_segment_cz,
            segment_cz,
        ),
        trading_points=trading.points,
        trading_point_candidates=trading.candidates,
        trend_divergences=trading.trend_divergences,
        diagnostics=tuple(diagnostics),
        stroke_diagnostics=stroke_result.diagnostics,
        segment_diagnostics=(
            tuple(live_segment_result.diagnostics)
            + left_segment_diagnostics
            + tuple(state.diagnostics)
        ),
        central_zone_diagnostics=formal_cz.diagnostics,
        segment_central_zone_diagnostics=segment_cz.diagnostics,
        trading_point_diagnostics=trading.diagnostics,
        merge_count=merge_count,
        min_bi_len=min_bi_len,
        segment_mode=segment_mode,
        left_boundary_resolved=state.left_boundary_is_resolved,
        left_boundary_anchored=state.left_boundary_anchored,
        left_anchor=state.left_anchor,
        metadata=metadata,
    )


def _detect_formal_central_zones(
    strokes: Sequence[Stroke],
    *,
    left_boundary_anchored: bool,
) -> tuple[CentralZoneDetectionResult, CentralZoneDetectionResult]:
    """把左边界未解析的首个笔中枢分组隔离到候选层。

    有限窗口可能从一个既有中枢分组内部开始。首个分组因此无法证明其真实
    起点和 ``ZD/ZG``；只有方向分离事件开启第二个分组后，后续分组才具备
    窗口内可验证的左边界。
    """
    values = tuple(strokes)
    detected = detect_central_zones(values)
    empty = CentralZoneDetectionResult((), (), ())
    if left_boundary_anchored or not detected.groups:
        return detected, empty

    first_group = detected.groups[0]
    unresolved_zones = tuple(
        zone for zone in detected.zones if zone.group_index == first_group.group_index
    )
    unresolved = CentralZoneDetectionResult(
        zones=unresolved_zones,
        groups=(first_group,),
        diagnostics=(
            CentralZoneDiagnostic(
                code="UNRESOLVED_LEFT_BOUNDARY_CENTRAL_ZONE",
                message=(
                    "当前窗口首个笔中枢分组可能从历史中枢内部开始，"
                    "仅作为候选；等待下一次分组切换或载入历史锚点"
                ),
                dt=first_group.sdt,
            ),
        ),
    )

    split = len(first_group.strokes)
    if split >= len(values):
        formal = CentralZoneDetectionResult(
            zones=(),
            groups=(),
            diagnostics=unresolved.diagnostics,
        )
        return formal, unresolved

    tail = detect_central_zones(values[split:])
    formal = CentralZoneDetectionResult(
        zones=tail.zones,
        groups=tail.groups,
        diagnostics=unresolved.diagnostics + tail.diagnostics,
    )
    return formal, unresolved


def _detect_formal_segment_central_zones(
    segments: Sequence[Segment],
    *,
    left_boundary_anchored: bool,
) -> tuple[SegmentCentralZoneDetectionResult, SegmentCentralZoneDetectionResult]:
    """隔离有限窗口中无法证明起点正确的首个线段中枢。"""
    values = tuple(segments)
    detected = detect_segment_central_zones(values)
    empty = SegmentCentralZoneDetectionResult((), (), ())
    if left_boundary_anchored or not detected.zones:
        return detected, empty

    first_zone = detected.zones[0]
    unresolved_candidates = tuple(
        item
        for item in detected.candidates
        if item.start_position <= first_zone.end_position
    )
    unresolved = SegmentCentralZoneDetectionResult(
        zones=(first_zone,),
        candidates=unresolved_candidates,
        diagnostics=(
            SegmentCentralZoneDiagnostic(
                code="UNRESOLVED_LEFT_BOUNDARY_SEGMENT_CENTRAL_ZONE",
                message=(
                    "当前窗口首个线段中枢可能继承窗口之前的线段，"
                    "仅作为候选；等待该中枢结束或载入历史锚点"
                ),
                dt=first_zone.sdt,
            ),
        ),
    )

    split = first_zone.end_position + 1
    if split >= len(values):
        formal = SegmentCentralZoneDetectionResult(
            zones=(),
            candidates=(),
            diagnostics=unresolved.diagnostics,
        )
        return formal, unresolved

    tail = detect_segment_central_zones(values[split:])
    formal = SegmentCentralZoneDetectionResult(
        zones=tuple(
            _offset_segment_central_zone(item, split, index=i)
            for i, item in enumerate(tail.zones)
        ),
        candidates=tuple(
            _offset_segment_central_zone(item, split, index=item.index)
            for item in tail.candidates
        ),
        diagnostics=unresolved.diagnostics + tail.diagnostics,
    )
    return formal, unresolved


def _partition_detected_segments(
    detected: Sequence[Segment],
    formal: Sequence[Segment],
    *,
    left_boundary_resolved: bool,
    fallback_unresolved: Sequence[Segment],
    fallback_provisional: Sequence[Segment],
) -> tuple[tuple[Segment, ...], tuple[Segment, ...]]:
    """在完整检测链中定位正式线段区间，分离左前缀和右尾部。"""
    detected_values = tuple(detected)
    formal_values = tuple(formal)
    if not detected_values:
        return tuple(fallback_unresolved), tuple(fallback_provisional)
    if not formal_values:
        if left_boundary_resolved:
            return (), detected_values
        return detected_values, ()

    formal_keys = tuple(_segment_key(x) for x in formal_values)
    detected_keys = tuple(_segment_key(x) for x in detected_values)
    width = len(formal_keys)
    for start in range(len(detected_keys) - width + 1):
        if detected_keys[start : start + width] == formal_keys:
            return detected_values[:start], detected_values[start + width :]
    return tuple(fallback_unresolved), tuple(fallback_provisional)


def _segment_zone_candidates(
    detected: SegmentCentralZoneDetectionResult,
    formal: SegmentCentralZoneDetectionResult,
) -> tuple[SegmentCentralZone, ...]:
    formal_keys = {_segment_central_zone_key(x) for x in formal.zones}
    values: list[SegmentCentralZone] = []
    seen: set[tuple] = set()
    for item in tuple(detected.zones) + tuple(detected.candidates):
        key = _segment_central_zone_key(item)
        if key in formal_keys or key in seen:
            continue
        seen.add(key)
        values.append(item)
    return tuple(values)


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
    left_boundary_anchored: bool = False
    left_anchor: StructureAnchor | None = None
    _bars: list[RawBar] = field(default_factory=list)
    _result: AnalysisResult | None = None
    _structure_state: StructureState | None = None

    def _new_state(self) -> StructureState:
        return StructureState(
            min_bi_len=self.min_bi_len,
            segment_mode=SegmentMode(self.segment_mode),
            left_boundary_anchored=self.left_boundary_anchored,
            left_anchor=self.left_anchor,
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


def _find_anchor_position(
    strokes: Sequence[Stroke],
    anchor: StructureAnchor,
    *,
    tolerance: float = 1e-9,
) -> int | None:
    if not strokes:
        return None
    endpoints = (strokes[0].fx_a,) + tuple(x.fx_b for x in strokes)
    for position, endpoint in enumerate(endpoints):
        if endpoint.dt != anchor.dt:
            continue
        if abs(endpoint.value - anchor.value) > tolerance:
            continue
        if anchor.mark is not None and endpoint.mark is not anchor.mark:
            continue
        if position < len(strokes):
            return position
    return None


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


def _offset_segment_central_zone(
    zone: SegmentCentralZone,
    offset: int,
    *,
    index: int,
) -> SegmentCentralZone:
    return SegmentCentralZone(
        symbol=zone.symbol,
        segments=zone.segments,
        index=index,
        start_position=zone.start_position + offset,
        end_position=zone.end_position + offset,
    )


def _segment_central_zone_key(zone: SegmentCentralZone) -> tuple:
    return (
        tuple(_segment_key(x) for x in zone.segments[:3]),
        zone.zd,
        zone.zg,
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
