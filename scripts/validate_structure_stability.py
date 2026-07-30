from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from chan_monitor.central_zones import detect_central_zones
from chan_monitor.data import demo_bars
from chan_monitor.engine import StructureState
from chan_monitor.segment_central_zones import detect_segment_central_zones
from chan_monitor.segments import SegmentMode


def _stroke_key(item) -> tuple:
    return (
        item.start_dt.isoformat(),
        item.end_dt.isoformat(),
        round(item.start_value, 12),
        round(item.end_value, 12),
        item.direction.value,
    )


def _segment_key(item) -> tuple:
    return (
        item.start_dt.isoformat(),
        item.end_dt.isoformat(),
        round(item.start_value, 12),
        round(item.end_value, 12),
        item.direction.value,
    )


def _zone_seed(item) -> tuple:
    return (
        tuple(_stroke_key(x) for x in item.strokes[:3]),
        round(item.zd, 12),
        round(item.zg, 12),
    )


def _segment_zone_seed(item) -> tuple:
    return (
        tuple(_segment_key(x) for x in item.segments[:3]),
        round(item.zd, 12),
        round(item.zg, 12),
    )


def _is_prefix(previous: Sequence[tuple], current: Sequence[tuple]) -> bool:
    return len(previous) <= len(current) and tuple(previous) == tuple(current[: len(previous)])


def validate(count: int) -> dict[str, object]:
    state = StructureState(min_bi_len=6, segment_mode=SegmentMode.FEATURE_SEQUENCE)
    previous_detected: tuple[tuple, ...] = ()
    previous_stable: tuple[tuple, ...] = ()
    previous_segments: tuple[tuple, ...] = ()
    previous_zones: dict[tuple, object] = {}
    previous_segment_zones: dict[tuple, object] = {}

    detected_stroke_retractions = 0
    stable_stroke_retractions: list[int] = []
    formal_segment_retractions: list[int] = []
    pen_zone_disappearances: list[int] = []
    pen_zone_right_shrinks: list[int] = []
    segment_zone_disappearances: list[int] = []
    segment_zone_right_shrinks: list[int] = []

    for position, bar in enumerate(
        demo_bars(count, symbol="BTCUSDT", interval="5m"), start=1
    ):
        state.update(bar)
        detected = tuple(_stroke_key(x) for x in state.detected_strokes)
        stable = tuple(_stroke_key(x) for x in state.stable_strokes)
        segments = tuple(_segment_key(x) for x in state.segments)

        if previous_detected and not _is_prefix(previous_detected, detected):
            detected_stroke_retractions += 1
        if not _is_prefix(previous_stable, stable):
            stable_stroke_retractions.append(position)
        if not _is_prefix(previous_segments, segments):
            formal_segment_retractions.append(position)

        canonical = state.canonical_strokes
        if canonical[: len(state.stable_strokes)] != state.stable_strokes:
            stable_stroke_retractions.append(position)
        if canonical[len(state.stable_strokes) :] != state.provisional_strokes:
            stable_stroke_retractions.append(position)

        if len(stable) != len(previous_stable):
            current_zones = {
                _zone_seed(item): item
                for item in detect_central_zones(state.stable_strokes).zones
            }
            for seed, old in previous_zones.items():
                new = current_zones.get(seed)
                if new is None:
                    pen_zone_disappearances.append(position)
                elif new.edt < old.edt:
                    pen_zone_right_shrinks.append(position)
            previous_zones = current_zones

        if len(segments) != len(previous_segments):
            current_segment_zones = {
                _segment_zone_seed(item): item
                for item in detect_segment_central_zones(state.segments).zones
            }
            for seed, old in previous_segment_zones.items():
                new = current_segment_zones.get(seed)
                if new is None:
                    segment_zone_disappearances.append(position)
                elif new.edt < old.edt:
                    segment_zone_right_shrinks.append(position)
            previous_segment_zones = current_segment_zones

        previous_detected = detected
        previous_stable = stable
        previous_segments = segments

    failures = {
        "stable_stroke_retractions": stable_stroke_retractions,
        "formal_segment_retractions": formal_segment_retractions,
        "pen_zone_disappearances": pen_zone_disappearances,
        "pen_zone_right_shrinks": pen_zone_right_shrinks,
        "segment_zone_disappearances": segment_zone_disappearances,
        "segment_zone_right_shrinks": segment_zone_right_shrinks,
    }
    return {
        "bars_scanned": count,
        "detected_stroke_retractions_expected_in_provisional_layer": detected_stroke_retractions,
        "final_detected_strokes": len(state.detected_strokes),
        "final_all_strokes": len(state.canonical_strokes),
        "final_stable_strokes": len(state.stable_strokes),
        "final_provisional_strokes": len(state.provisional_strokes),
        "final_formal_segments": len(state.segments),
        "final_provisional_segments": len(state.provisional_segments),
        "formal_failure_count": sum(len(values) for values in failures.values()),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="逐根扫描 DEMO K 线，验证稳定笔、正式线段和正式中枢不会回撤。"
    )
    parser.add_argument("--bars", type=int, default=5000)
    args = parser.parse_args()
    if args.bars <= 0:
        parser.error("--bars 必须大于 0")

    result = validate(args.bars)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["formal_failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
