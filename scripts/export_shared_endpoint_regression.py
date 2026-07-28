from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from chan_monitor.chart import build_raw_chart, raw_frame, strokes_frame
from chan_monitor.engine import analyze_bars
from chan_monitor.metadata import AnalysisMetadata
from chan_monitor.models import RawBar
from chan_monitor.reference import run_frozen_czsc_reference
from chan_monitor.strokes import validate_stroke_chain


def regression_bars() -> list[RawBar]:
    """复现 2026-07-17 08:00 旧底、13:00 更低底的共享端点问题。"""
    values = [
        (8, 6),
        (9, 7),
        (10, 8),
        (12, 10),  # 01:00 顶
        (11, 9),
        (10, 8),
        (9, 7),
        (8, 6),
        (7, 5),
        (6.5, 4.5),
        (6, 4),  # 08:00 旧底
        (8, 6),
        (11, 9),
        (14, 12),  # 11:00 中间顶，先形成旧底 -> 中间顶
        (11, 9),
        (5, 3),  # 13:00 更低底
        (9, 7),
        (11, 9),
        (13, 11),
        (15, 13),
        (16, 14),  # 18:00 新顶
        (14, 12),
    ]
    base = datetime(2026, 7, 16, 22, tzinfo=timezone.utc)
    bars: list[RawBar] = []
    for i, (high, low) in enumerate(values):
        dt = base + timedelta(hours=i)
        bars.append(
            RawBar(
                symbol="BTCUSDT",
                interval="1h",
                open_time=dt,
                close_time=dt + timedelta(hours=1) - timedelta(milliseconds=1),
                open=low,
                high=high,
                low=low,
                close=high,
                volume=1,
                quote_volume=high,
                trade_count=1,
            )
        )
    return bars


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "regression"
    output.mkdir(parents=True, exist_ok=True)

    bars = regression_bars()
    metadata = AnalysisMetadata(
        source_name="共享端点确定性回归数据",
        market="DEMO / 模拟市场",
        is_demo=True,
        note="仅复现 2026-07-17 08:00 与 13:00 两个底的结构，不是真实 Binance 行情",
    )
    result = analyze_bars(bars, min_bi_len=6, metadata=metadata)
    reference = run_frozen_czsc_reference(bars, min_bi_len=6)
    issues = validate_stroke_chain(result.strokes, min_bi_len=6)

    raw_frame(result).to_csv(output / "shared_endpoint_20260717_bars.csv", index=False)
    strokes_frame(result).to_csv(output / "shared_endpoint_20260717_corrected_strokes.csv", index=False)
    pd.DataFrame(
        [
            {
                "笔序号": i,
                "方向": stroke.direction,
                "起点时间": stroke.fx_a.dt,
                "起点价格": stroke.fx_a.value,
                "终点时间": stroke.fx_b.dt,
                "终点价格": stroke.fx_b.value,
                "无包含K数": len(stroke.bars),
            }
            for i, stroke in enumerate(reference.strokes)
        ]
    ).to_csv(output / "shared_endpoint_20260717_old_baseline_strokes.csv", index=False)

    rows = []
    total = max(len(result.strokes), len(reference.strokes))
    for i in range(total):
        ours = result.strokes[i] if i < len(result.strokes) else None
        old = reference.strokes[i] if i < len(reference.strokes) else None
        rows.append(
            {
                "笔序号": i,
                "修正后方向": ours.direction.label if ours else None,
                "修正后起点": ours.start_dt if ours else None,
                "修正后终点": ours.end_dt if ours else None,
                "修正后终点价格": ours.end_value if ours else None,
                "旧基线方向": old.direction if old else None,
                "旧基线起点": old.fx_a.dt if old else None,
                "旧基线终点": old.fx_b.dt if old else None,
                "旧基线终点价格": old.fx_b.value if old else None,
            }
        )
    pd.DataFrame(rows).to_csv(output / "shared_endpoint_20260717_comparison.csv", index=False)

    build_raw_chart(
        result,
        title="共享端点回归：更低底替换旧底",
        show_fractals=True,
        show_strokes=True,
    ).write_html(output / "shared_endpoint_20260717_corrected.html", include_plotlyjs=True)

    summary = {
        "old_bottom": "2026-07-17T08:00:00+00:00",
        "replacement_bottom": "2026-07-17T13:00:00+00:00",
        "corrected_strokes": [
            {
                "direction": x.direction.value,
                "start": x.start_dt.isoformat(),
                "end": x.end_dt.isoformat(),
                "start_value": x.start_value,
                "end_value": x.end_value,
            }
            for x in result.strokes
        ],
        "old_baseline_strokes": [
            {
                "direction": x.direction,
                "start": x.fx_a.dt.isoformat(),
                "end": x.fx_b.dt.isoformat(),
                "start_value": x.fx_a.value,
                "end_value": x.fx_b.value,
            }
            for x in reference.strokes
        ],
        "shared_endpoint_replacements": [
            {"time": x.dt.isoformat() if x.dt else None, "message": x.message}
            for x in result.stroke_diagnostics
            if x.code == "SHARED_ENDPOINT_REPLACED"
        ],
        "chain_validation_issues": [x.message for x in issues],
    }
    (output / "shared_endpoint_20260717_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
