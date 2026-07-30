"""CZSC-compatible K-line, fractal, stroke, segment and central-zone foundation."""

from .central_zone_reference import compare_central_zones_with_czsc
from .central_zones import detect_central_zones, validate_central_zones
from .segment_central_zone_reference import compare_segment_central_zones_with_reference
from .segment_central_zones import detect_segment_central_zones, validate_segment_central_zones
from .trading_point_reference import compare_trading_points_with_reference
from .trading_points import detect_trading_points, validate_trading_points
from .engine import AnalysisResult, FractalEngine, StructureState, analyze_bars
from .fractals import check_fractal, detect_fractals, remove_inclusions
from .feature_sequence_reference import compare_feature_sequence_reference
from .metadata import AnalysisMetadata
from .models import (
    CentralZone,
    CentralZoneDiagnostic,
    FeatureBreakStatus,
    FeatureElement,
    FeatureFractal,
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Segment,
    SegmentCentralZone,
    SegmentCentralZoneDiagnostic,
    SegmentDiagnostic,
    SegmentEvidence,
    Stroke,
    StrokeDirection,
    TradingPoint,
    TradingPointCandidate,
    TradingPointDiagnostic,
    TradingPointStatus,
    TradingPointType,
    TrendDivergence,
)
from .reference import ReferenceComparison, compare_with_czsc_reference
from .segments import (
    SegmentMode,
    detect_segments,
    detect_segments_from_anchor,
    validate_feature_sequence_coverage,
    validate_segment_chain,
)
from .strokes import check_bi, detect_strokes, validate_stroke_chain

__all__ = [
    "AnalysisMetadata",
    "AnalysisResult",
    "CentralZone",
    "CentralZoneDiagnostic",
    "Fractal",
    "FractalEngine",
    "StructureState",
    "FractalMark",
    "MergedBar",
    "RawBar",
    "ReferenceComparison",
    "Segment",
    "SegmentCentralZone",
    "SegmentCentralZoneDiagnostic",
    "SegmentDiagnostic",
    "FeatureBreakStatus",
    "FeatureElement",
    "FeatureFractal",
    "SegmentEvidence",
    "SegmentMode",
    "Stroke",
    "StrokeDirection",
    "TradingPoint",
    "TradingPointCandidate",
    "TradingPointDiagnostic",
    "TradingPointStatus",
    "TradingPointType",
    "TrendDivergence",
    "analyze_bars",
    "check_bi",
    "check_fractal",
    "compare_central_zones_with_czsc",
    "compare_feature_sequence_reference",
    "compare_segment_central_zones_with_reference",
    "compare_with_czsc_reference",
    "detect_central_zones",
    "detect_fractals",
    "detect_segments",
    "detect_segments_from_anchor",
    "detect_segment_central_zones",
    "detect_strokes",
    "detect_trading_points",
    "remove_inclusions",
    "validate_central_zones",
    "validate_feature_sequence_coverage",
    "validate_segment_chain",
    "validate_segment_central_zones",
    "validate_stroke_chain",
    "validate_trading_points",
    "compare_trading_points_with_reference",
]
