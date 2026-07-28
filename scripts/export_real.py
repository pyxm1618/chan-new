from __future__ import annotations

import argparse
import json
from pathlib import Path

from chan_monitor.binance import BinanceKlineClient, BinanceMarket
from chan_monitor.central_zone_reference import compare_central_zones_with_czsc
from chan_monitor.segment_central_zone_reference import compare_segment_central_zones_with_reference
from chan_monitor.trading_point_reference import compare_trading_points_with_reference
from chan_monitor.chart import (
    build_merged_chart,
    build_raw_chart,
    central_zone_groups_frame,
    central_zones_frame,
    segment_central_zone_candidates_frame,
    segment_central_zones_frame,
    trading_points_frame,
    trading_point_candidates_frame,
    trend_divergences_frame,
    segments_frame,
    segment_evidence_frame,
    feature_elements_frame,
    feature_fractals_frame,
    unresolved_segment_prefix_frame,
    strokes_frame,
    unfinished_frame,
    unfinished_segment_frame,
)
from chan_monitor.data import bars_from_csv, save_bars_csv
from chan_monitor.engine import analyze_bars
from chan_monitor.metadata import AnalysisMetadata
from chan_monitor.reference import compare_with_czsc_reference
from chan_monitor.feature_sequence_reference import compare_feature_sequence_reference
from chan_monitor.segments import SegmentMode


MIRROR_URL = "https://github.com/cryptobigbro/binance-BTCUSDT/tree/master"


def main() -> None:
    parser = argparse.ArgumentParser(description="导出真实 Binance K 线、笔、线段、中枢及 CZSC 差分报告")
    parser.add_argument("--input", type=Path, help="可选：本地 Binance CSV；不传则调用 Binance REST API")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--market", choices=["spot", "usdm"], default="spot")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--min-bi-len", type=int, default=6)
    parser.add_argument("--segment-mode", choices=[SegmentMode.FEATURE_SEQUENCE.value], default=SegmentMode.FEATURE_SEQUENCE.value)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = args.output or root / "artifacts" / "real"
    output.mkdir(parents=True, exist_ok=True)

    if args.input:
        bars = bars_from_csv(args.input, symbol=args.symbol, interval=args.interval)[-args.limit :]
        metadata = AnalysisMetadata(
            source_name="Binance Spot 历史快照（cryptobigbro 镜像）",
            market="Binance 现货" if args.market == "spot" else "Binance U 本位合约",
            source_url=MIRROR_URL,
            note="真实历史行情静态快照；运行时界面默认直接调用 Binance REST API",
        )
    else:
        market = BinanceMarket.SPOT if args.market == "spot" else BinanceMarket.USD_M_FUTURES
        client = BinanceKlineClient()
        bars = client.fetch_klines(args.symbol, args.interval, args.limit, market=market, closed_only=True)
        metadata = AnalysisMetadata.binance_rest(
            market=f"Binance {market.label}",
            source_url=client.source_url(market),
        )

    result = analyze_bars(
        bars,
        min_bi_len=args.min_bi_len,
        metadata=metadata,
        segment_mode=SegmentMode(args.segment_mode),
    )
    comparison = compare_with_czsc_reference(result)
    central_comparison = compare_central_zones_with_czsc(
        result.central_zones,
        result.central_zone_groups,
        result.strokes,
    )
    segment_central_comparison = compare_segment_central_zones_with_reference(
        result.segment_central_zones,
        result.segment_central_zone_candidates,
        result.segments,
    )
    trading_point_comparison = compare_trading_points_with_reference(
        result.trading_points, result.segments, result.segment_central_zones, raw_bars=result.raw_bars
    )
    segment_comparison = compare_feature_sequence_reference(
        result.segments,
        result.segment_evidence,
        result.strokes,
    )
    first = result.raw_bars[0].open_time.strftime("%Y%m%d-%H%M")
    last = result.raw_bars[-1].open_time.strftime("%Y%m%d-%H%M")
    stem = f"{args.symbol}_{args.market}_{args.interval}_{first}_{last}"

    save_bars_csv(list(result.raw_bars), output / f"{stem}_bars.csv")
    build_raw_chart(result).write_html(output / f"{stem}_raw.html", include_plotlyjs=True)
    build_merged_chart(result).write_html(output / f"{stem}_merged.html", include_plotlyjs=True)
    strokes_frame(result).to_csv(output / f"{stem}_strokes.csv", index=False)
    segments_frame(result).to_csv(output / f"{stem}_segments.csv", index=False)
    segment_evidence_frame(result).to_csv(output / f"{stem}_segment_evidence.csv", index=False)
    feature_elements_frame(result).to_csv(output / f"{stem}_feature_elements.csv", index=False)
    feature_fractals_frame(result).to_csv(output / f"{stem}_feature_fractals.csv", index=False)
    unresolved_segment_prefix_frame(result).to_csv(
        output / f"{stem}_unresolved_segment_prefix.csv", index=False
    )
    central_zones_frame(result).to_csv(output / f"{stem}_central_zones.csv", index=False)
    central_zone_groups_frame(result).to_csv(output / f"{stem}_central_zone_groups.csv", index=False)
    segment_central_zones_frame(result).to_csv(
        output / f"{stem}_segment_central_zones.csv", index=False
    )
    segment_central_zone_candidates_frame(result).to_csv(
        output / f"{stem}_segment_central_zone_candidates.csv", index=False
    )
    trading_points_frame(result).to_csv(output / f"{stem}_trading_points.csv", index=False)
    trading_point_candidates_frame(result).to_csv(output / f"{stem}_trading_point_candidates.csv", index=False)
    trend_divergences_frame(result).to_csv(output / f"{stem}_trend_divergences.csv", index=False)
    unfinished_frame(result).to_csv(output / f"{stem}_unfinished_bars.csv", index=False)
    unfinished_segment_frame(result).to_csv(
        output / f"{stem}_unfinished_segment_strokes.csv", index=False
    )
    comparison.merged_frame().to_csv(output / f"{stem}_czsc_merged_comparison.csv", index=False)
    comparison.fractal_frame().to_csv(output / f"{stem}_czsc_fractal_comparison.csv", index=False)
    comparison.stroke_frame().to_csv(output / f"{stem}_czsc_stroke_comparison.csv", index=False)
    comparison.unfinished_frame().to_csv(output / f"{stem}_czsc_unfinished_comparison.csv", index=False)
    segment_comparison.segment_frame().to_csv(
        output / f"{stem}_feature_sequence_segment_comparison.csv", index=False
    )
    segment_comparison.evidence_frame().to_csv(
        output / f"{stem}_feature_sequence_evidence_comparison.csv", index=False
    )
    central_comparison.group_frame().to_csv(
        output / f"{stem}_czsc_central_zone_group_comparison.csv", index=False
    )
    central_comparison.zone_frame().to_csv(
        output / f"{stem}_czsc_central_zone_comparison.csv", index=False
    )
    segment_central_comparison.candidate_frame().to_csv(
        output / f"{stem}_segment_central_zone_candidate_comparison.csv", index=False
    )
    segment_central_comparison.zone_frame().to_csv(
        output / f"{stem}_segment_central_zone_comparison.csv", index=False
    )
    trading_point_comparison.frame().to_csv(
        output / f"{stem}_trading_point_comparison.csv", index=False
    )

    summary = (
        comparison.summary()
        | segment_comparison.summary()
        | central_comparison.summary()
        | segment_central_comparison.summary()
        | trading_point_comparison.summary()
        | {
        "market": metadata.market,
        "symbol": args.symbol,
        "interval": args.interval,
        "source": metadata.source_name,
        "source_url": metadata.source_url,
        "first_open_time": result.raw_bars[0].open_time.isoformat(),
        "last_open_time": result.raw_bars[-1].open_time.isoformat(),
        "raw_bars": len(result.raw_bars),
        "merged_bars": len(result.merged_bars),
        "fractals": len(result.fractals),
        "strokes": len(result.strokes),
        "segments": len(result.segments),
        "central_zone_groups": len(result.central_zone_groups),
        "central_zones": len(result.central_zones),
        "segment_markers": len(result.segment_markers),
        "segment_candidates": len(result.segment_candidates),
        "unfinished_segment_strokes": len(result.unfinished_segment_strokes),
        "unresolved_segment_prefix_strokes": len(result.unresolved_segment_prefix_strokes),
        "feature_elements": len(result.feature_elements),
        "feature_fractals": len(result.feature_fractals),
        "segment_evidence": len(result.segment_evidence),
        "segment_mode": result.segment_mode.value,
        "unfinished_bars": len(result.unfinished_bars),
        "trading_points": len(result.trading_points),
        "trading_point_candidates": len(result.trading_point_candidates),
        "trend_divergences": len(result.trend_divergences),
        "stroke_rollbacks": len(result.stroke_diagnostics),
        "shared_endpoint_replacements": sum(
            x.code == "SHARED_ENDPOINT_REPLACED" for x in result.stroke_diagnostics
        ),
        "merge_count": result.merge_count,
        "min_bi_len": result.min_bi_len,
        "segment_central_zone_candidates": len(result.segment_central_zone_candidates),
        "segment_central_zones": len(result.segment_central_zones),
        "trading_points": len(result.trading_points),
        "trading_point_counts": {key: sum(x.point_type.value == key for x in result.trading_points) for key in ("B1", "B2", "B3", "S1", "S2", "S3")},
    }
    )
    (output / f"{stem}_comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
