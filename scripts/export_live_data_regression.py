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
    unresolved_segment_prefix_frame,
)
from chan_monitor.data import demo_bars, save_bars_csv
from chan_monitor.feature_sequence_reference import compare_feature_sequence_reference
from chan_monitor.live import analyze_snapshot
from chan_monitor.metadata import AnalysisMetadata
from chan_monitor.models import FeatureBreakStatus, RawBar
from chan_monitor.segment_central_zones import validate_segment_central_zones
from chan_monitor.segments import (
    SegmentMode,
    _scan_segment,
    _trace_feature_detector,
    detect_segments,
    stroke_endpoints,
    validate_segment_chain,
)
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
        exclude_last_stroke_confirmation=True,
    )
    central_zone_issues = validate_central_zones(result.central_zones, result.strokes)
    segment_zone_issues = validate_segment_central_zones(result.segment_central_zones, result.segments)
    trading_point_issues = validate_trading_points(
        result.trading_points,
        result.segments,
        result.segment_central_zones,
        raw_bars=result.raw_bars,
        segment_evidence=result.segment_evidence,
        strokes=result.resolved_strokes,
        macd_history_anchored=result.left_boundary_anchored,
        macd_anchor=result.macd_anchor,
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
    unresolved_segment_prefix_frame(result).to_csv(
        output / f"{prefix}_unresolved_segment_prefix_strokes.csv", index=False
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

    def segment_signature(values):
        return tuple(
            (x.direction.value, x.start_dt, x.end_dt, x.stroke_count)
            for x in values
        )

    full_signature = segment_signature(result.segments)
    end_to_index = {
        segment.fx_b.dt: index for index, segment in enumerate(result.segments)
    }
    truncation_rows = []
    for offset in range(min(40, max(0, len(result.strokes) - 3))):
        truncated = detect_segments(
            result.strokes[offset:],
            exclude_last_stroke_confirmation=True,
        )
        if not truncated.segments:
            truncation_rows.append(
                {"offset": offset, "first_end_in_full_chain": False, "tail_match": False}
            )
            continue
        first_end = truncated.segments[0].fx_b.dt
        full_index = end_to_index.get(first_end)
        actual_tail = segment_signature(truncated.segments)[1:]
        expected_tail = (
            full_signature[full_index + 1 : full_index + 1 + len(actual_tail)]
            if full_index is not None
            else ()
        )
        truncation_rows.append(
            {
                "offset": offset,
                "first_end_in_full_chain": full_index is not None,
                "tail_match": full_index is not None and actual_tail == expected_tail,
            }
        )

    first_evidence = result.segment_evidence[0] if result.segment_evidence else None
    first_segment = result.segments[0] if result.segments else None
    extreme_violation_count = sum(
        item.code == "FIRST_SEGMENT_EXTREME_VIOLATION"
        for item in result.segment_diagnostics
    )

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
        "unresolved_segment_prefix_strokes": len(result.unresolved_segment_prefix_strokes),
        "first_segment_start_position": first_evidence.start_position if first_evidence else None,
        "first_segment_end_position": first_evidence.end_position if first_evidence else None,
        "first_segment_direction": first_segment.direction.value if first_segment else None,
        "first_segment_start_value": first_segment.start_value if first_segment else None,
        "first_segment_end_value": first_segment.end_value if first_segment else None,
        "first_segment_extreme_violation_candidates": extreme_violation_count,
        "truncation_tail_checks": len(truncation_rows),
        "truncation_tail_match_count": sum(bool(x["tail_match"]) for x in truncation_rows),
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
        "v0.10.5_continuous_scan_only": {
            "confirmed_strokes": 338,
            "confirmed_segments": 61,
            "feature_elements": 307,
            "feature_fractals": 63,
            "unfinished_segment_strokes": 3,
            "feature_tail_position": 337,
            "last_stroke_position": 337,
            "feature_tail_gap": 0,
        },
        "v0.10.8_primary_reverse_confirmation_competition": {
            "confirmed_strokes": len(result.strokes),
            "confirmed_segments": len(result.segments),
            "feature_elements": len(result.feature_elements),
            "feature_fractals": len(result.feature_fractals),
            "unfinished_segment_strokes": len(result.unfinished_segment_strokes),
            "feature_tail_position": feature_tail_position,
            "last_stroke_position": last_stroke_position,
            "feature_tail_gap": last_stroke_position - feature_tail_position,
            "endpoint_replacements": sum(
                x.code == "GAP_PRIMARY_ENDPOINT_REPLACED"
                for x in result.segment_diagnostics
            ),
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
    migrated = [
        {
            "segment_index": item.segment_index,
            "start_position": item.start_position,
            "gap_origin_position": (
                item.gap_origin_fractal.endpoint_position
                if item.gap_origin_fractal else None
            ),
            "final_endpoint_position": item.end_position,
            "confirmed_at_position": item.confirmed_at_position,
            "gap_origin_price": (
                item.gap_origin_fractal.value if item.gap_origin_fractal else None
            ),
            "final_endpoint_price": (
                item.final_endpoint.value if item.final_endpoint else None
            ),
        }
        for item in result.segment_evidence
        if item.gap_origin_fractal is not None
        and item.end_position != item.gap_origin_fractal.endpoint_position
    ]
    pd.DataFrame(migrated).to_csv(
        output / "gap_endpoint_migrations.csv", index=False
    )

    trace_start = 303
    trace_outcome = _scan_segment(result.strokes, stroke_endpoints(result.strokes), trace_start)
    trace_rows = []
    if trace_outcome.gap_origin is not None:
        trace_rows.append({
            "event": "gap_origin",
            "stroke_position": trace_outcome.gap_origin.endpoint_position,
            "detected_at_position": trace_outcome.gap_origin.detected_at_position,
            "endpoint_time": trace_outcome.gap_origin.dt,
            "endpoint_price": trace_outcome.gap_origin.value,
            "confirmation": None,
        })
    for item in trace_outcome.diagnostics:
        if item.code == "GAP_PRIMARY_ENDPOINT_REPLACED":
            trace_rows.append({
                "event": "endpoint_replaced",
                "stroke_position": None,
                "detected_at_position": None,
                "endpoint_time": item.dt,
                "endpoint_price": None,
                "confirmation": item.message,
            })
    trace_rows.append({
        "event": "final_confirmation",
        "stroke_position": trace_outcome.end_position,
        "detected_at_position": trace_outcome.confirmed_at_position,
        "endpoint_time": trace_outcome.final_endpoint.dt if trace_outcome.final_endpoint else None,
        "endpoint_price": trace_outcome.final_endpoint.value if trace_outcome.final_endpoint else None,
        "confirmation": trace_outcome.confirmation,
    })
    pd.DataFrame(trace_rows).to_csv(
        output / "gap_endpoint_303_migration_trace.csv", index=False
    )

    competition_start = 18
    competition_trace = _trace_feature_detector(
        result.strokes,
        segment_direction=result.strokes[competition_start].direction,
        sequence_start_position=competition_start,
        feed_start=competition_start + 1,
    )
    competition_candidates = [
        fx for fx in sorted(
            competition_trace.candidates,
            key=lambda x: (x.detected_at_position, x.endpoint_position),
        )
        if fx.break_status is FeatureBreakStatus.CONFIRMED
        and fx.endpoint_position <= 31
    ]
    competition_outcome = _scan_segment(
        result.strokes, stroke_endpoints(result.strokes), competition_start
    )
    competition_rows = [
        {
            "event": "primary_candidate",
            "endpoint_position": fx.endpoint_position,
            "endpoint_price": fx.value,
            "detected_at_position": fx.detected_at_position,
            "gap": fx.gap,
            "selected_result": (
                competition_outcome.end_position == fx.endpoint_position
                and competition_outcome.confirmed_at_position == fx.detected_at_position
            ),
        }
        for fx in competition_candidates
    ]
    pd.DataFrame(competition_rows).to_csv(
        output / "gap_no_gap_competition_trace.csv", index=False
    )
    competition_summary = {
        "dataset": summary["dataset"],
        "root_cause": (
            "after entering a gapped-primary wait state, the implementation kept "
            "migrating raw extremes and checking reverse confirmation but ignored "
            "later confirmed no-gap primary fractals"
        ),
        "regression_start_position": competition_start,
        "old_result": {
            "start_position": 18,
            "end_position": 31,
            "confirmation": "GAP_REVERSE_FRACTAL",
            "confirmed_at_position": 36,
        },
        "fixed_result": {
            "start_position": competition_outcome.start_position,
            "end_position": competition_outcome.end_position,
            "confirmation": competition_outcome.confirmation,
            "confirmed_at_position": competition_outcome.confirmed_at_position,
        },
        "primary_candidates": competition_rows,
        "validation": {
            "segment_validation_issues": len(segment_issues),
            "reference_all_match": feature_comparison.all_match,
            "skipped_no_gap_guard_issues": sum(
                x.code == "GAP_CONFIRMATION_SKIPPED_EARLIER_NO_GAP_PRIMARY"
                for x in segment_issues
            ),
        },
    }
    (output / "gap_no_gap_competition_bug_summary.json").write_text(
        json.dumps(competition_summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    endpoint_lock_summary = {
        "dataset": summary["dataset"],
        "root_cause": (
            "after a gapped primary feature fractal, the old implementation froze "
            "the endpoint and fed only the reverse detector"
        ),
        "old_confirmed_segments": 61,
        "fixed_confirmed_segments": len(result.segments),
        "migrated_segment_count": len(migrated),
        "migrations": migrated,
        "validation": {
            "segment_validation_issues": len(segment_issues),
            "reference_all_match": feature_comparison.all_match,
            "gap_endpoint_invariant_issues": sum(
                x.code == "GAP_ENDPOINT_SUPERSEDED_BEFORE_CONFIRMATION"
                for x in segment_issues
            ),
        },
    }
    (output / "gap_endpoint_lock_bug_summary.json").write_text(
        json.dumps(endpoint_lock_summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    boundary_regression = {
        "dataset": summary["dataset"],
        "rule": {
            "up": "start is lowest bottom and end is highest top inside candidate",
            "down": "start is highest top and end is lowest bottom inside candidate",
            "selection": "earliest complete end; same end uses more extreme start; same price uses later start",
        },
        "legacy_invalid_first_segment": {
            "start_position": 0,
            "end_position": 7,
            "direction": "down",
            "start_value": 109.0806836428213,
            "end_value": 90.02383139102206,
            "problem": "internal top 110.1655985483843 exceeded the candidate start top",
        },
        "merged_first_segment": {
            "start_position": first_evidence.start_position if first_evidence else None,
            "end_position": first_evidence.end_position if first_evidence else None,
            "direction": first_segment.direction.value if first_segment else None,
            "start_value": first_segment.start_value if first_segment else None,
            "end_value": first_segment.end_value if first_segment else None,
            "unresolved_prefix_strokes": len(result.unresolved_segment_prefix_strokes),
        },
        "candidate_extreme_violations": extreme_violation_count,
        "truncation_checks": truncation_rows,
        "validation": {
            "segment_validation_issues": len(segment_issues),
            "reference_all_match": feature_comparison.all_match,
            "reference_segment_match_count": feature_comparison.segment_match_count,
            "reference_evidence_match_count": feature_comparison.evidence_match_count,
            "all_truncation_tails_match": all(x["tail_match"] for x in truncation_rows),
        },
    }
    (output / "first_segment_boundary_regression.json").write_text(
        json.dumps(boundary_regression, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
