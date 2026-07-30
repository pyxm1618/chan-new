from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

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
from .strokes import DEFAULT_MIN_BI_LEN, detect_strokes
from .segments import SegmentMode, detect_segments


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    raw_bars: tuple[RawBar, ...]
    merged_bars: tuple[MergedBar, ...]
    fractals: tuple[Fractal, ...]
    strokes: tuple[Stroke, ...]
    unfinished_bars: tuple[MergedBar, ...]
    segments: tuple[Segment, ...]
    segment_markers: tuple[Fractal, ...]
    segment_candidates: tuple[Fractal, ...]
    unfinished_segment_strokes: tuple[Stroke, ...]
    unresolved_segment_prefix_strokes: tuple[Stroke, ...]
    feature_elements: tuple[FeatureElement, ...]
    feature_fractals: tuple[FeatureFractal, ...]
    segment_evidence: tuple[SegmentEvidence, ...]
    central_zones: tuple[CentralZone, ...]
    central_zone_groups: tuple[CentralZone, ...]
    segment_central_zones: tuple[SegmentCentralZone, ...]
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



def _stable_stroke_prefix(strokes: tuple[Stroke, ...]) -> tuple[Stroke, ...]:
    """返回不会因为下一根K线导致结构级联回撤的笔前缀。

    CZSC实时分析中，最后一笔始终处于确认窗口：
    - 它可能因为新的分型替换而撤销；
    - 任何依赖它的线段/中枢都不能成为正式结构。

    因此：
    - strokes 保留完整链，用于UI显示和诊断；
    - stable_strokes 只用于线段、中枢、交易点等正式结构。
    """
    if len(strokes) <= 1:
        return ()
    return tuple(strokes[:-1])


def analyze_bars(
    raw_bars: Iterable[RawBar],
    *,
    czsc_compatibility: bool = True,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
    metadata: AnalysisMetadata | None = None,
    segment_mode: SegmentMode | str = SegmentMode.FEATURE_SEQUENCE,
) -> AnalysisResult:
    bars = tuple(raw_bars)
    merged, merge_count = remove_inclusions(bars)
    fractals, diagnostics = detect_fractals(merged, czsc_compatibility=czsc_compatibility)
    stroke_result = detect_strokes(bars, min_bi_len=min_bi_len)

    # 结构稳定性边界：最新一笔属于可回撤尾部。
    # 任何需要“正式结构”的模块都不能消费它，否则会出现：
    # 1. 已确认线段下一根K线消失；
    # 2. 笔中枢由末笔构成后整体撤销；
    # 3. 线段中枢右边界回缩。
    # 保留全部 strokes 供诊断和展示，稳定结构只使用 stable_strokes。
    stable_strokes = _stable_stroke_prefix(stroke_result.strokes)

    segment_result = detect_segments(
        stable_strokes,
        latest_bar=merged[-1] if merged else None,
        mode=segment_mode,
        exclude_last_stroke_confirmation=True,
    )
    central_zone_result = detect_central_zones(stable_strokes)
    segment_central_zone_result = detect_segment_central_zones(segment_result.segments)
    trading_point_result = detect_trading_points(
        segment_result.segments,
        segment_central_zone_result.zones,
        raw_bars=bars,
        segment_evidence=segment_result.evidence,
        strokes=stable_strokes,
    )
    return AnalysisResult(
        raw_bars=bars,
        merged_bars=tuple(merged),
        fractals=tuple(fractals),
        strokes=stable_strokes,
        unfinished_bars=stroke_result.unfinished_bars,
        segments=segment_result.segments,
        segment_markers=segment_result.markers,
        segment_candidates=segment_result.candidates,
        unfinished_segment_strokes=segment_result.unfinished_strokes,
        unresolved_segment_prefix_strokes=segment_result.unresolved_prefix_strokes,
        feature_elements=segment_result.feature_elements,
        feature_fractals=segment_result.feature_fractals,
        segment_evidence=segment_result.evidence,
        central_zones=central_zone_result.zones,
        central_zone_groups=central_zone_result.groups,
        segment_central_zones=segment_central_zone_result.zones,
        segment_central_zone_candidates=segment_central_zone_result.candidates,
        trading_points=trading_point_result.points,
        trading_point_candidates=trading_point_result.candidates,
        trend_divergences=trading_point_result.trend_divergences,
        diagnostics=tuple(diagnostics),
        stroke_diagnostics=stroke_result.diagnostics,
        segment_diagnostics=segment_result.diagnostics,
        central_zone_diagnostics=central_zone_result.diagnostics,
        segment_central_zone_diagnostics=segment_central_zone_result.diagnostics,
        trading_point_diagnostics=trading_point_result.diagnostics,
        merge_count=merge_count,
        min_bi_len=min_bi_len,
        segment_mode=segment_result.mode,
        metadata=metadata or AnalysisMetadata(),
    )


@dataclass(slots=True)
class FractalEngine:
    """适合后续后台行情流的增量外壳。

    每次追加或修订最后一根 K 线后从现有原始 K 序列重算结构，优先保证结果确定性。
    后续进入多币种后台阶段时再针对性能做局部增量优化。
    """

    czsc_compatibility: bool = True
    min_bi_len: int = DEFAULT_MIN_BI_LEN
    metadata: AnalysisMetadata = field(default_factory=AnalysisMetadata)
    segment_mode: SegmentMode = SegmentMode.FEATURE_SEQUENCE
    _bars: list[RawBar] = field(default_factory=list)
    _result: AnalysisResult | None = None

    @property
    def result(self) -> AnalysisResult:
        if self._result is None:
            self._result = analyze_bars(
                self._bars,
                czsc_compatibility=self.czsc_compatibility,
                min_bi_len=self.min_bi_len,
                metadata=self.metadata,
                segment_mode=self.segment_mode,
            )
        return self._result

    @property
    def last_open_time(self) -> datetime | None:
        return self._bars[-1].open_time if self._bars else None

    def update(self, bar: RawBar) -> AnalysisResult:
        if not self._bars:
            self._bars.append(bar)
        elif bar.open_time > self._bars[-1].open_time:
            self._bars.append(bar)
        elif bar.open_time == self._bars[-1].open_time:
            self._bars[-1] = bar
        else:
            raise ValueError("只允许追加新 K 线或修订最后一根 K 线")
        self._result = analyze_bars(
            self._bars,
            czsc_compatibility=self.czsc_compatibility,
            min_bi_len=self.min_bi_len,
            metadata=self.metadata,
            segment_mode=self.segment_mode,
        )
        return self._result

    def extend(self, bars: Iterable[RawBar]) -> AnalysisResult:
        for bar in bars:
            self.update(bar)
        return self.result
