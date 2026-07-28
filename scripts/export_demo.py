from pathlib import Path

from chan_monitor.chart import (
    build_merged_chart,
    build_raw_chart,
    central_zone_groups_frame,
    central_zones_frame,
    segment_central_zone_candidates_frame,
    segment_central_zones_frame,
    trading_points_frame,
    segments_frame,
    segment_evidence_frame,
    feature_elements_frame,
    feature_fractals_frame,
    strokes_frame,
)
from chan_monitor.data import demo_bars, save_bars_csv
from chan_monitor.engine import analyze_bars
from chan_monitor.metadata import AnalysisMetadata


root = Path(__file__).resolve().parents[1]
result = analyze_bars(demo_bars(), metadata=AnalysisMetadata.demo())
(root / "artifacts").mkdir(exist_ok=True)
build_raw_chart(result).write_html(root / "artifacts" / "demo_raw.html", include_plotlyjs=True)
build_merged_chart(result).write_html(root / "artifacts" / "demo_merged.html", include_plotlyjs=True)
save_bars_csv(list(result.raw_bars), root / "artifacts" / "demo_bars.csv")
strokes_frame(result).to_csv(root / "artifacts" / "demo_strokes.csv", index=False)
segments_frame(result).to_csv(root / "artifacts" / "demo_segments.csv", index=False)
segment_evidence_frame(result).to_csv(root / "artifacts" / "demo_segment_evidence.csv", index=False)
feature_elements_frame(result).to_csv(root / "artifacts" / "demo_feature_elements.csv", index=False)
feature_fractals_frame(result).to_csv(root / "artifacts" / "demo_feature_fractals.csv", index=False)
central_zones_frame(result).to_csv(root / "artifacts" / "demo_central_zones.csv", index=False)
central_zone_groups_frame(result).to_csv(root / "artifacts" / "demo_central_zone_groups.csv", index=False)
segment_central_zones_frame(result).to_csv(
    root / "artifacts" / "demo_segment_central_zones.csv", index=False
)
segment_central_zone_candidates_frame(result).to_csv(
    root / "artifacts" / "demo_segment_central_zone_candidates.csv", index=False
)
trading_points_frame(result).to_csv(root / "artifacts" / "demo_trading_points.csv", index=False)
print(
    f"raw={len(result.raw_bars)} merged={len(result.merged_bars)} "
    f"fractals={len(result.fractals)} strokes={len(result.strokes)} segments={len(result.segments)} "
    f"central_zones={len(result.central_zones)} "
    f"segment_central_zones={len(result.segment_central_zones)} trading_points={len(result.trading_points)}"
)
