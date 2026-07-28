from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

from chan_monitor.binance import BinanceKlineSnapshot, BinanceMarket
from chan_monitor.central_zones import validate_central_zones
from chan_monitor.chart import (
    build_merged_chart,
    build_raw_chart,
    feature_elements_frame,
    feature_fractals_frame,
    segment_evidence_frame,
    segments_frame,
    strokes_frame,
    unfinished_segment_frame,
)
from chan_monitor.data import demo_bars, save_bars_csv
from chan_monitor.feature_sequence_reference import compare_feature_sequence_reference
from chan_monitor.live import analyze_snapshot
from chan_monitor.metadata import AnalysisMetadata
from chan_monitor.models import RawBar
from chan_monitor.segment_central_zones import validate_segment_central_zones
from chan_monitor.segments import SegmentMode, validate_segment_chain
from chan_monitor.strokes import validate_stroke_chain
from chan_monitor.trading_points import validate_trading_points


def _line_frame(values) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "结构": x.label,
                "方向": x.direction.label,
                "起点时间": x.start_dt,
                "起点价格": x.start_value,
                "终点时间": x.end_dt,
                "终点价格": x.end_value,
                "原因": x.reason,
                "来源序号": " | ".join(str(i) for i in x.source_indexes),
            }
            for x in values
        ]
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "regression"
    output.mkdir(parents=True, exist_ok=True)

    closed = demo_bars(5000, symbol="BTCUSDT", interval="5m")
    last = closed[-1]
    current = RawBar(
        symbol=last.symbol,
        interval=last.interval,
        open_time=last.open_time + timedelta(minutes=5),
        close_time=last.close_time + timedelta(minutes=5),
        open=last.close,
        high=last.close + 8,
        low=last.close - 3,
        close=last.close + 6,
        volume=last.volume * 1.4,
        quote_volume=last.quote_volume * 1.4,
        trade_count=last.trade_count + 10,
    )
    snapshot = BinanceKlineSnapshot(
        symbol="BTCUSDT",
        interval="5m",
        market=BinanceMarket.SPOT,
        history_limit=5000,
        closed_bars=tuple(closed),
        current_bar=current,
        fetched_at=current.open_time + timedelta(minutes=2),
    )

    started = time.perf_counter()
    bundle = analyze_snapshot(
        snapshot,
        czsc_compatibility=True,
        min_bi_len=6,
        metadata=AnalysisMetadata.demo(),
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
    )
    elapsed = time.perf_counter() - started
    result = bundle.confirmed

    stroke_issues = validate_stroke_chain(result.strokes, min_bi_len=result.min_bi_len)
    segment_issues = validate_segment_chain(
        result.segments,
        result.strokes,
        mode=result.segment_mode,
        evidence=result.segment_evidence,
    )
    central_zone_issues = validate_central_zones(result.central_zones, result.strokes)
    segment_zone_issues = validate_segment_central_zones(result.segment_central_zones, result.segments)
    trading_point_issues = validate_trading_points(
        result.trading_points,
        result.segments,
        result.segment_central_zones,
        raw_bars=result.raw_bars,
    )
    feature_comparison = compare_feature_sequence_reference(
        result.segments,
        result.segment_evidence,
        result.strokes,
    )

    prefix = "live_5000_5m_demo"
    build_raw_chart(result, live_overlay=bundle.overlay).write_html(
        output / f"{prefix}_raw.html", include_plotlyjs=True
    )
    build_merged_chart(result, live_overlay=bundle.overlay).write_html(
        output / f"{prefix}_merged.html", include_plotlyjs=True
    )
    save_bars_csv(closed, output / f"{prefix}_closed_bars.csv")
    pd.DataFrame(
        [
            {
                "open_time": current.open_time,
                "close_time": current.close_time,
                "symbol": current.symbol,
                "interval": current.interval,
                "open": current.open,
                "high": current.high,
                "low": current.low,
                "close": current.close,
                "volume": current.volume,
                "quote_volume": current.quote_volume,
                "trade_count": current.trade_count,
            }
        ]
    ).to_csv(output / f"{prefix}_current_bar.csv", index=False)
    strokes_frame(result).to_csv(output / f"{prefix}_confirmed_strokes.csv", index=False)
    segments_frame(result).to_csv(output / f"{prefix}_confirmed_segments.csv", index=False)
    segment_evidence_frame(result).to_csv(
        output / f"{prefix}_segment_evidence.csv", index=False
    )
    feature_elements_frame(result).to_csv(
        output / f"{prefix}_feature_elements.csv", index=False
    )
    feature_fractals_frame(result).to_csv(
        output / f"{prefix}_feature_fractals.csv", index=False
    )
    unfinished_segment_frame(result).to_csv(
        output / f"{prefix}_unfinished_segment_strokes.csv", index=False
    )
    _line_frame(bundle.overlay.provisional_strokes).to_csv(
        output / f"{prefix}_provisional_strokes.csv", index=False
    )
    _line_frame(bundle.overlay.provisional_segments).to_csv(
        output / f"{prefix}_provisional_segments.csv", index=False
    )
    feature_comparison.segment_frame().to_csv(
        output / f"{prefix}_feature_sequence_segment_comparison.csv", index=False
    )
    feature_comparison.evidence_frame().to_csv(
        output / f"{prefix}_feature_sequence_evidence_comparison.csv", index=False
    )

    feature_tail_position = max(
        (position for element in result.feature_elements for position in element.stroke_positions),
        default=-1,
    )
    last_stroke_position = len(result.strokes) - 1

    summary = {
        "dataset": "DEMO / deterministic 5m regression; not real market data",
        "closed_raw_bars": len(result.raw_bars),
        "current_raw_bars": 1,
        "merged_bars": len(result.merged_bars),
        "fractals": len(result.fractals),
        "confirmed_strokes": len(result.strokes),
        "provisional_strokes": len(bundle.overlay.provisional_strokes),
        "confirmed_segments": len(result.segments),
        "provisional_segments": len(bundle.overlay.provisional_segments),
        "feature_elements": len(result.feature_elements),
        "feature_fractals": len(result.feature_fractals),
        "feature_tail_position": feature_tail_position,
        "last_stroke_position": last_stroke_position,
        "feature_tail_gap": last_stroke_position - feature_tail_position,
        "unfinished_segment_strokes": len(result.unfinished_segment_strokes),
        "central_zones": len(result.central_zones),
        "segment_central_zones": len(result.segment_central_zones),
        "trading_points": len(result.trading_points),
        "gap_count": snapshot.gap_count,
        "analysis_seconds": round(elapsed, 6),
        "stroke_validation_issues": len(stroke_issues),
        "segment_validation_issues": len(segment_issues),
        "central_zone_validation_issues": len(central_zone_issues),
        "segment_central_zone_validation_issues": len(segment_zone_issues),
        "trading_point_validation_issues": len(trading_point_issues),
        **feature_comparison.summary(),
    }
    (output / f"{prefix}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    bug_regression = {
        "dataset": summary["dataset"],
        "root_cause": "first non-actual-break feature fractal stopped the whole scan instead of resetting and continuing",
        "v0.10.4_legacy": {
            "confirmed_strokes": 338,
            "confirmed_segments": 3,
            "feature_elements": 35,
            "feature_fractals": 5,
            "unfinished_segment_strokes": 317,
            "feature_tail_position": 36,
            "last_stroke_position": 337,
            "feature_tail_gap": 301,
        },
        "v0.10.5_fixed": {
            "confirmed_strokes": len(result.strokes),
            "confirmed_segments": len(result.segments),
            "feature_elements": len(result.feature_elements),
            "feature_fractals": len(result.feature_fractals),
            "unfinished_segment_strokes": len(result.unfinished_segment_strokes),
            "feature_tail_position": feature_tail_position,
            "last_stroke_position": last_stroke_position,
            "feature_tail_gap": last_stroke_position - feature_tail_position,
        },
        "validation": {
            "segment_validation_issues": len(segment_issues),
            "reference_all_match": feature_comparison.all_match,
            "reference_segment_match_count": feature_comparison.segment_match_count,
            "reference_evidence_match_count": feature_comparison.evidence_match_count,
        },
    }
    (output / "feature_sequence_stop_bug_summary.json").write_text(
        json.dumps(bug_regression, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
