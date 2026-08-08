from __future__ import annotations

import argparse
import json
import math
import random
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_monitor.engine import StructureState, _common_stroke_prefix_length, _fractal_key
from chan_monitor.models import RawBar
from chan_monitor.segments import SegmentMode, detect_segments


def stress_bars(seed: int, count: int = 300) -> list[RawBar]:
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
            high = previous.high - rng.uniform(0.01, max(0.02, (previous.high - previous.low) * 0.15))
            low = previous.low + rng.uniform(0.01, max(0.02, (previous.high - previous.low) * 0.15))
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


def _audit_seed(args: tuple[int, int]) -> dict[str, object]:
    seed, count = args
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    anchor_loss_events: list[dict[str, int]] = []
    previous_stable = ()
    previous_segments = ()
    monotonic_failure = False

    for position, bar in enumerate(stress_bars(seed, count), 1):
        state.update(bar)
        stable = tuple(
            (x.start_dt, x.end_dt, round(x.start_value, 12), round(x.end_value, 12), x.direction)
            for x in state.stable_strokes
        )
        segments = tuple(
            (x.start_dt, x.end_dt, round(x.start_value, 12), round(x.end_value, 12), x.direction)
            for x in state.segments
        )
        if previous_stable != stable[: len(previous_stable)]:
            monotonic_failure = True
        if previous_segments != segments[: len(previous_segments)]:
            monotonic_failure = True
        previous_stable = stable
        previous_segments = segments

        if state.stable_strokes:
            common = _common_stroke_prefix_length(state.stable_strokes, state.detected_strokes)
            if common < len(state.stable_strokes):
                endpoint = _fractal_key(state.stable_strokes[-1].fx_b)
                reconnect = next(
                    (
                        i
                        for i, stroke in enumerate(state.detected_strokes)
                        if _fractal_key(stroke.fx_a) == endpoint
                    ),
                    None,
                )
                if reconnect is None:
                    anchor_loss_events.append(
                        {
                            "bar": position,
                            "stable": len(state.stable_strokes),
                            "detected": len(state.detected_strokes),
                            "common": common,
                        }
                    )

    direct = detect_segments(
        state.detected_strokes,
        mode=SegmentMode.FEATURE_SEQUENCE,
        exclude_last_stroke_confirmation=True,
    )
    commit_lag = max(0, len(direct.segments) - len(state.segments) - 1)
    return {
        "seed": seed,
        "anchor_loss_events": anchor_loss_events,
        "monotonic_failure": monotonic_failure,
        "detected_strokes": len(state.detected_strokes),
        "canonical_strokes": len(state.canonical_strokes),
        "stable_strokes": len(state.stable_strokes),
        "formal_segments": len(state.segments),
        "direct_segments": len(direct.segments),
        "commit_lag": commit_lag,
        "shared_endpoint_replacements": sum(
            x.code == "SHARED_ENDPOINT_REPLACED"
            for x in state.stroke_state.diagnostics
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=1000)
    parser.add_argument("--bars", type=int, default=300)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    work = [(seed, args.bars) for seed in range(args.seeds)]
    if args.workers == 1:
        rows = [_audit_seed(item) for item in work]
    else:
        workers = args.workers or None
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_audit_seed, work, chunksize=8))

    failures = [
        row
        for row in rows
        if row["anchor_loss_events"]
        or row["monotonic_failure"]
        or row["commit_lag"]
        or row["canonical_strokes"] < row["stable_strokes"]
    ]
    summary = {
        "seeds": args.seeds,
        "bars_per_seed": args.bars,
        "shared_endpoint_replacement_seeds": sum(
            row["shared_endpoint_replacements"] > 0 for row in rows
        ),
        "anchor_loss_seed_count": sum(bool(row["anchor_loss_events"]) for row in rows),
        "monotonic_failure_count": sum(bool(row["monotonic_failure"]) for row in rows),
        "commit_lag_seed_count": sum(bool(row["commit_lag"]) for row in rows),
        "failure_count": len(failures),
        "failure_examples": failures[:10],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
