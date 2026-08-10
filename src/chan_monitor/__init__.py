"""CZSC-compatible K-line, fractal, stroke, segment and central-zone foundation."""

from .central_zone_reference import compare_central_zones_with_czsc
from .central_zones import detect_central_zones, validate_central_zones
from .segment_central_zone_reference import compare_segment_central_zones_with_reference
from .segment_central_zones import detect_segment_central_zones, validate_segment_central_zones
from .trading_point_reference import compare_trading_points_with_reference
from .trading_points import build_macd_anchor
from .formal_single_level_trading_points import detect_trading_points, validate_trading_points
from .engine import AnalysisResult, FractalEngine, StructureAnchor, StructureState, analyze_bars
from . import engine as _engine_module
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
    MacdAnchor,
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
    SegmentValidationTarget,
    detect_segments,
    detect_segments_from_anchor,
    validate_feature_sequence_coverage,
    validate_segment_chain,
)
from .strokes import check_bi, detect_strokes, validate_stroke_chain

# `engine.py` historically imported the legacy detector directly. Keep that module
# available for its independent regression suite, while binding the runtime engine
# to the public production detector selected by this package. A later recursive
# implementation can be introduced as a separate explicit mode instead of silently
# treating same-interval strokes as a lower timeframe.
_engine_module.detect_trading_points = detect_trading_points

__all__ = [
    "AnalysisMetadata",
    "AnalysisResult",
    "CentralZone",
    "CentralZoneDiagnostic",
    "Fractal",
    "FractalEngine",
    "StructureState",
    "StructureAnchor",
    "FractalMark",
    "MergedBar",
    "MacdAnchor",
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
    "SegmentValidationTarget",
    "Stroke",
    "StrokeDirection",
    "TradingPoint",
    "TradingPointCandidate",
    "TradingPointDiagnostic",
    "TradingPointStatus",
    "TradingPointType",
    "TrendDivergence",
    "analyze_bars",
    "build_macd_anchor",
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
