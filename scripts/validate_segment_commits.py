from __future__ import annotations

import argparse
import json

from chan_monitor.data import demo_bars
from chan_monitor.engine import StructureState, analyze_bars
from chan_monitor.segments import (
    SegmentMode,
    SegmentValidationTarget,
    validate_segment_chain,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="验证正式线段校验语义与真实提交时间")
    parser.add_argument("--bars", type=int, default=5000)
    args = parser.parse_args()

    bars = demo_bars(args.bars, symbol="BTCUSDT", interval="5m")
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    first_seen: dict[int, tuple] = {}
    previous_count = 0
    for position, bar in enumerate(bars):
        state.update(bar)
        for item in state.evidence[previous_count:]:
            first_seen[item.segment_index] = (bar.close_time, position)
        previous_count = len(state.evidence)

    result = analyze_bars(bars, left_boundary_anchored=True)
    issues = validate_segment_chain(
        result.segments,
        result.strokes,
        mode=result.segment_mode,
        evidence=result.segment_evidence,
        validation_target=SegmentValidationTarget.COMMITTED,
        stable_stroke_count=len(result.stable_strokes),
    )

    commit_mismatches = []
    for item in result.segment_evidence:
        expected = first_seen.get(item.segment_index)
        actual = (item.committed_at, item.committed_at_bar_position)
        if expected != actual:
            commit_mismatches.append(
                {
                    "segment_index": item.segment_index,
                    "expected": tuple(str(x) for x in expected) if expected else None,
                    "actual": tuple(str(x) for x in actual),
                }
            )

    missing_commit_time = [
        item.segment_index
        for item in result.segment_evidence
        if item.committed_at is None or item.committed_at_bar_position is None
    ]
    commit_times = [item.committed_at for item in result.segment_evidence]
    commit_positions = [item.committed_at_bar_position for item in result.segment_evidence]
    monotonic_time = commit_times == sorted(commit_times)
    monotonic_position = commit_positions == sorted(commit_positions)

    output = {
        "bars_scanned": args.bars,
        "formal_segments": len(result.segments),
        "stable_strokes": len(result.stable_strokes),
        "validator_issue_count": len(issues),
        "validator_issues": [
            {"code": item.code, "message": item.message} for item in issues
        ],
        "missing_commit_time": missing_commit_time,
        "commit_time_monotonic": monotonic_time,
        "commit_position_monotonic": monotonic_position,
        "commit_first_seen_mismatch_count": len(commit_mismatches),
        "commit_first_seen_mismatches": commit_mismatches,
        "first_commit": (
            result.segment_evidence[0].committed_at.isoformat()
            if result.segment_evidence else None
        ),
        "last_commit": (
            result.segment_evidence[-1].committed_at.isoformat()
            if result.segment_evidence else None
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if (
        issues
        or missing_commit_time
        or not monotonic_time
        or not monotonic_position
        or commit_mismatches
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
