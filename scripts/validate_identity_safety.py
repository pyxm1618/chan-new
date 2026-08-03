from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_monitor.data import demo_bars
from chan_monitor.engine import StructureState, analyze_bars
from chan_monitor.models import RawBar, TradingPointType
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.segments import (
    SegmentMode,
    SegmentValidationTarget,
    detect_segments_from_anchor,
    validate_segment_chain,
)
from chan_monitor.trading_points import (
    _macd_histogram,
    build_macd_anchor,
    detect_trading_points,
    validate_trading_points,
)

# Reuse the deterministic a+A+b+B+c fixture used by the dedicated first-buy
# verifier. The verifier is imported as a module and does not execute its CLI.
import validate_first_buy_logic as first_buy_fixture


def stress_bars(seed: int, count: int = 1000) -> list[RawBar]:
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    drift = 0.0
    bars: list[RawBar] = []
    for i in range(count):
        if i % 18 == 0:
            drift = rng.uniform(-1.4, 1.4)
        open_ = price
        close = max(1.0, open_ + drift + rng.gauss(0, 1.25) + 1.2 * math.sin(i / 5.0))
        spread = abs(rng.gauss(1.4, 0.6)) + 0.2
        high = max(open_, close) + spread * rng.uniform(0.4, 1.4)
        low = min(open_, close) - spread * rng.uniform(0.4, 1.4)
        if bars and rng.random() < 0.06:
            previous = bars[-1]
            high = previous.high - rng.uniform(
                0.01, max(0.02, (previous.high - previous.low) * 0.15)
            )
            low = previous.low + rng.uniform(
                0.01, max(0.02, (previous.high - previous.low) * 0.15)
            )
            if low < high:
                open_ = min(max(open_, low), high)
                close = min(max(close, low), high)
        if rng.random() < 0.03:
            if rng.random() < 0.5:
                low -= rng.uniform(2, 8)
            else:
                high += rng.uniform(2, 8)
        dt = start + timedelta(minutes=5 * i)
        bars.append(
            RawBar(
                symbol="STRESS",
                interval="5m",
                open_time=dt,
                close_time=dt + timedelta(minutes=5) - timedelta(milliseconds=1),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1,
                quote_volume=1,
                trade_count=i,
            )
        )
        price = close
    return bars


def expect_value_error(fn, contains: str) -> bool:
    try:
        fn()
    except (TypeError, ValueError) as exc:
        return contains in str(exc)
    return False


def run() -> dict[str, object]:
    failures: list[str] = []

    bars = demo_bars(300, symbol="BTCUSDT", interval="5m")
    anchor = build_macd_anchor(bars[:150])
    tail = bars[150:]

    macd_wrong_symbol_rejected = expect_value_error(
        lambda: _macd_histogram(
            tuple(replace(bar, symbol="ETHUSDT") for bar in tail),
            history_anchored=False,
            anchor=anchor,
        ),
        "品种不匹配",
    )
    macd_wrong_interval_rejected = expect_value_error(
        lambda: _macd_histogram(
            tuple(replace(bar, interval="15m") for bar in tail),
            history_anchored=False,
            anchor=anchor,
        ),
        "周期不匹配",
    )
    macd_gap_rejected = expect_value_error(
        lambda: _macd_histogram(
            tail[1:], history_anchored=False, anchor=anchor
        ),
        "不连续",
    )
    inexact_gap = _macd_histogram(
        bars[:149] + bars[150:], history_anchored=True, anchor=None
    )
    gapped_history_not_exact = not inexact_gap.exact

    a = analyze_bars(
        demo_bars(500, symbol="AAA", interval="5m"),
        left_boundary_anchored=True,
    )
    b = analyze_bars(
        demo_bars(500, symbol="BBB", interval="5m"),
        left_boundary_anchored=True,
    )
    cross_symbol_evidence_rejected = expect_value_error(
        lambda: detect_trading_points(
            a.segments,
            a.segment_central_zones,
            raw_bars=a.raw_bars,
            segment_evidence=b.segment_evidence,
            strokes=a.resolved_strokes,
            macd_history_anchored=True,
        ),
        "品种/周期/几何指纹不匹配",
    )
    index_commit_mapping_rejected = expect_value_error(
        lambda: detect_trading_points(
            a.segments,
            a.segment_central_zones,
            raw_bars=a.raw_bars,
            segment_commit_times={segment.index: a.raw_bars[-1].close_time for segment in a.segments},
            strokes=a.resolved_strokes,
            macd_history_anchored=True,
        ),
        "不再接受 segment_index",
    )

    base = [140, 120, 135, 125, 132, 100, 112, 102, 110, 90, 108, 80]
    durations = [5, 5, 5, 5, 20, 5, 5, 5, 5, 5, 25]
    segments = first_buy_fixture._segments(base, durations, start_bottom=False)
    segments[10] = first_buy_fixture._with_internal_strokes(
        segments[10],
        [108, 98, 104, 100, 103, 90, 96, 92, 95, 80],
        [1] * 9,
    )
    synthetic_bars = first_buy_fixture._bars(segments)
    zones = detect_segment_central_zones(segments).zones
    point_result = first_buy_fixture._detect_trading_points(
        segments,
        zones,
        raw_bars=synthetic_bars,
        macd_history_anchored=True,
    )
    first_buy = next(
        item for item in point_result.points if item.point_type is TradingPointType.BUY1
    )
    forged = replace(
        first_buy,
        confirmed_at_dt=first_buy.confirmed_at_dt + timedelta(days=1),
    )
    time_codes = {
        item.code
        for item in validate_trading_points(
            (forged,),
            segments,
            zones,
            raw_bars=synthetic_bars,
            segment_commit_times=first_buy_fixture._commit_times(segments),
            macd_history_anchored=True,
        )
    }
    confirmation_time_tamper_detected = (
        "TRADING_POINT_CONFIRM_TIME_MISMATCH" in time_codes
    )

    empty_committed_chain_clean = (
        validate_segment_chain(
            (),
            (),
            validation_target=SegmentValidationTarget.COMMITTED,
            stable_stroke_count=0,
        )
        == ()
    )

    demo_result = analyze_bars(
        demo_bars(500, symbol="TAIL", interval="5m"),
        left_boundary_anchored=True,
    )
    two_tail = tuple(demo_result.strokes[-2:])
    tail_result = detect_segments_from_anchor(
        two_tail,
        start_position=0,
        mode=SegmentMode.FEATURE_SEQUENCE,
        exclude_last_stroke_confirmation=True,
    )
    two_stroke_tail_audited = len(tail_result.feature_elements) == 1

    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    for bar in stress_bars(509):
        state.update(bar)
    seed_509_issues = validate_segment_chain(
        state.segments,
        state.canonical_strokes,
        mode=SegmentMode.FEATURE_SEQUENCE,
        evidence=state.evidence,
        validation_target=SegmentValidationTarget.COMMITTED,
        stable_stroke_count=len(state.stable_strokes),
    )
    seed_509_false_commit_time_issue_count = sum(
        item.code == "SEGMENT_COMMIT_TIME_BEFORE_EVIDENCE"
        for item in seed_509_issues
    )
    immutable_confirmation_snapshots_complete = bool(state.evidence) and all(
        item.confirmation_available_at is not None
        and item.confirmation_stroke_fingerprint
        for item in state.evidence
    )

    checks = {
        "macd_wrong_symbol_rejected": macd_wrong_symbol_rejected,
        "macd_wrong_interval_rejected": macd_wrong_interval_rejected,
        "macd_anchor_gap_rejected": macd_gap_rejected,
        "gapped_history_not_exact": gapped_history_not_exact,
        "cross_symbol_segment_evidence_rejected": cross_symbol_evidence_rejected,
        "segment_index_commit_mapping_rejected": index_commit_mapping_rejected,
        "trading_point_confirmation_time_tamper_detected": confirmation_time_tamper_detected,
        "empty_committed_chain_clean": empty_committed_chain_clean,
        "two_stroke_tail_audited": two_stroke_tail_audited,
        "immutable_confirmation_snapshots_complete": immutable_confirmation_snapshots_complete,
        "seed_509_false_commit_time_issue_count": seed_509_false_commit_time_issue_count,
    }
    for name, value in checks.items():
        passed = value == 0 if name.endswith("_issue_count") else bool(value)
        if not passed:
            failures.append(name)

    return {
        "checks": checks,
        "seed_509_formal_segments": len(state.segments),
        "seed_509_stable_strokes": len(state.stable_strokes),
        "seed_509_validator_issue_codes": [item.code for item in seed_509_issues],
        "failure_count": len(failures),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 MACD/线段身份绑定和提交时间审计")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 1 if result["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
