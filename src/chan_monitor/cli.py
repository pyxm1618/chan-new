from __future__ import annotations

import argparse
from pathlib import Path

from .binance import BinanceKlineClient, BinanceMarket
from .chart import (
    build_raw_chart,
    central_zones_frame,
    segment_central_zones_frame,
    segments_frame,
    strokes_frame,
    trading_points_frame,
)
from .data import demo_bars, save_bars_csv
from .engine import analyze_bars
from .metadata import AnalysisMetadata
from .segments import SegmentMode


def main() -> None:
    parser = argparse.ArgumentParser(description="CZSC 分型、笔、线段、双层中枢与买卖点检查工具")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="从 Binance 下载 K 线并分析")
    fetch.add_argument("--symbol", default="BTCUSDT")
    fetch.add_argument("--interval", default="5m")
    fetch.add_argument("--limit", type=int, default=5000)
    fetch.add_argument("--market", choices=[x.value for x in BinanceMarket], default="spot")
    fetch.add_argument("--min-bi-len", type=int, default=6)
    fetch.add_argument("--segment-mode", choices=[SegmentMode.FEATURE_SEQUENCE.value], default=SegmentMode.FEATURE_SEQUENCE.value)
    fetch.add_argument("--output", default="artifacts/binance_klines.csv")
    fetch.add_argument(
        "--trust-left-boundary",
        action="store_true",
        help=(
            "仅当下载范围确实从该品种/周期真实历史起点开始时启用正式线段、中枢和买卖点；"
            "普通最近 N 根窗口请勿开启"
        ),
    )

    export = sub.add_parser("export-demo", help="导出带水印的模拟数据 HTML")
    export.add_argument("--count", type=int, default=180)
    export.add_argument("--min-bi-len", type=int, default=6)
    export.add_argument("--segment-mode", choices=[SegmentMode.FEATURE_SEQUENCE.value], default=SegmentMode.FEATURE_SEQUENCE.value)
    export.add_argument("--output", default="artifacts/demo_strokes.html")

    args = parser.parse_args()
    if args.command == "fetch":
        market = BinanceMarket(args.market)
        client = BinanceKlineClient()
        bars = client.fetch_klines(args.symbol, args.interval, args.limit, market=market)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        save_bars_csv(bars, output)
        result = analyze_bars(
            bars,
            min_bi_len=args.min_bi_len,
            segment_mode=SegmentMode(args.segment_mode),
            metadata=AnalysisMetadata.binance_rest(
                market=f"Binance {market.label}",
                source_url=client.source_url(market),
            ),
            left_boundary_anchored=args.trust_left_boundary,
        )
        strokes_frame(result).to_csv(output.with_name(output.stem + "_strokes.csv"), index=False)
        segments_frame(result).to_csv(output.with_name(output.stem + "_segments.csv"), index=False)
        central_zones_frame(result).to_csv(output.with_name(output.stem + "_central_zones.csv"), index=False)
        segment_central_zones_frame(result).to_csv(
            output.with_name(output.stem + "_segment_central_zones.csv"), index=False
        )
        trading_points_frame(result).to_csv(
            output.with_name(output.stem + "_trading_points.csv"), index=False
        )
        print(f"保存 {len(bars)} 根 K 线到 {output}")
        if not result.left_boundary_resolved:
            print(
                "警告：当前窗口没有可信左边界，线段/中枢/买卖点只输出候选；"
                "正式 CSV 将为空。"
            )
        print(
            f"无包含 K {len(result.merged_bars)} 根，分型 {len(result.fractals)} 个，"
            f"笔 {len(result.strokes)} 条，线段 {len(result.segments)} 条，"
            f"笔中枢 {len(result.central_zones)} 个，线段中枢 {len(result.segment_central_zones)} 个，"
            f"买卖点 {len(result.trading_points)} 个，"
            f"未完成区 {len(result.unfinished_bars)} 根"
        )
    elif args.command == "export-demo":
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        result = analyze_bars(
            demo_bars(args.count),
            min_bi_len=args.min_bi_len,
            segment_mode=SegmentMode(args.segment_mode),
            metadata=AnalysisMetadata.demo(),
            left_boundary_anchored=True,
        )
        build_raw_chart(result).write_html(output, include_plotlyjs=True)
        print(f"已导出 {output}")


if __name__ == "__main__":
    main()
