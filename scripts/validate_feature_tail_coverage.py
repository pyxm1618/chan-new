from __future__ import annotations

import json
from pathlib import Path

from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import analyze_bars
from chan_monitor.segments import (
    SegmentValidationTarget,
    detect_segments_from_anchor,
    validate_feature_sequence_coverage,
    validate_segment_chain,
)


def _committed_issues(result) -> list[dict[str, str]]:
    return [
        {"code": item.code, "message": item.message}
        for item in validate_segment_chain(
            result.segments,
            result.strokes,
            mode=result.segment_mode,
            evidence=result.segment_evidence,
            validation_target=SegmentValidationTarget.COMMITTED,
            stable_stroke_count=len(result.stable_strokes),
        )
    ]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    real_path = (
        root
        / "artifacts"
        / "real"
        / "BTCUSDT_spot_1h_20191014-0600_20191104-0100_bars.csv"
    )
    real_bars = bars_from_csv(real_path, symbol="BTCUSDT", interval="1h")
    real = analyze_bars(real_bars, left_boundary_anchored=True)
    real_issues = _committed_issues(real)

    anchor_position = real.segment_evidence[0].start_position
    anchored = detect_segments_from_anchor(
        real.strokes,
        start_position=anchor_position,
        mode=real.segment_mode,
        exclude_last_stroke_confirmation=False,
    )
    anchored_coverage_issues = [
        {"code": item.code, "message": item.message}
        for item in validate_feature_sequence_coverage(
            anchored.feature_elements,
            real.strokes,
        )
    ]
    feature_tail_position = max(
        (
            position
            for element in anchored.feature_elements
            for position in element.stroke_positions
        ),
        default=-1,
    )

    prefix_failures = []
    prefixes_checked = 0
    for count in range(50, len(real_bars) + 1):
        result = analyze_bars(real_bars[:count], left_boundary_anchored=True)
        if not result.segments:
            continue
        prefixes_checked += 1
        issues = _committed_issues(result)
        if issues:
            prefix_failures.append({"bars": count, "issues": issues})

    demo = analyze_bars(
        demo_bars(5000, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )
    demo_issues = _committed_issues(demo)

    output = {
        "real_bars": len(real_bars),
        "real_strokes": len(real.strokes),
        "real_stable_strokes": len(real.stable_strokes),
        "real_formal_segments": len(real.segments),
        "real_validator_issues": real_issues,
        "anchored_feature_tail_position": feature_tail_position,
        "real_last_stroke_position": len(real.strokes) - 1,
        "anchored_feature_tail_gap": len(real.strokes) - 1 - feature_tail_position,
        "anchored_coverage_issues": anchored_coverage_issues,
        "real_prefixes_checked": prefixes_checked,
        "real_prefix_failure_count": len(prefix_failures),
        "real_prefix_failures": prefix_failures,
        "demo_bars": 5000,
        "demo_formal_segments": len(demo.segments),
        "demo_validator_issues": demo_issues,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if real_issues or anchored_coverage_issues or prefix_failures or demo_issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
