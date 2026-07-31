from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from chan_monitor.data import demo_bars
from chan_monitor.engine import StructureAnchor, analyze_bars


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


def _zone_key(item) -> tuple:
    return (
        tuple(_stroke_key(x) for x in item.strokes[:3]),
        round(item.zd, 12),
        round(item.zg, 12),
    )


def _segment_zone_key(item) -> tuple:
    return (
        tuple(_segment_key(x) for x in item.segments[:3]),
        round(item.zd, 12),
        round(item.zg, 12),
    )


def _is_contiguous_subsequence(actual: Sequence[tuple], reference: Sequence[tuple]) -> bool:
    actual_values = tuple(actual)
    reference_values = tuple(reference)
    if not actual_values:
        return True
    try:
        start = reference_values.index(actual_values[0])
    except ValueError:
        return False
    return actual_values == reference_values[start : start + len(actual_values)]


def _sample_indices(values: Sequence[int], maximum: int) -> tuple[int, ...]:
    unique = tuple(sorted(set(values)))
    if len(unique) <= maximum:
        return unique
    return tuple(
        unique[round(i * (len(unique) - 1) / max(1, maximum - 1))]
        for i in range(maximum)
    )


def validate(
    count: int,
    *,
    raw_window_stride: int,
    minimum_window_bars: int,
    anchor_context_bars: int,
    max_anchor_windows: int,
) -> dict[str, object]:
    bars = demo_bars(count, symbol="BTCUSDT", interval="5m")
    full = analyze_bars(bars, left_boundary_anchored=True)

    reference_segments = tuple(_segment_key(x) for x in full.segments)
    reference_zones = tuple(_zone_key(x) for x in full.central_zones)
    reference_segment_zones = tuple(
        _segment_zone_key(x) for x in full.segment_central_zones
    )

    failures: list[dict[str, object]] = []

    # 一、没有真实历史起点声明/持久化锚点时，任意截断窗口必须 fail closed。
    unanchored_windows_checked = 0
    last_offset = max(0, count - minimum_window_bars)
    offsets = list(range(0, last_offset + 1, raw_window_stride))
    if last_offset not in offsets:
        offsets.append(last_offset)
    for offset in offsets:
        result = analyze_bars(bars[offset:])
        unanchored_windows_checked += 1
        checks = {
            "left_boundary_resolved": not result.left_boundary_resolved,
            "formal_segments_empty": result.segments == (),
            "formal_central_zones_empty": result.central_zones == (),
            "formal_segment_central_zones_empty": result.segment_central_zones == (),
            "formal_trading_points_empty": result.trading_points == (),
            "all_detected_segments_are_unresolved": (
                result.unresolved_prefix_segments == result.detected_segments
                and result.provisional_segments == ()
            ),
        }
        for name, passed in checks.items():
            if not passed:
                failures.append(
                    {
                        "kind": "unanchored_window",
                        "raw_bar_offset": offset,
                        "check": name,
                    }
                )

    # 二、提供完整历史中已经持久化的正式线段端点后，只允许发布其后的参考后缀。
    bar_position = {bar.open_time: i for i, bar in enumerate(bars)}
    eligible_anchor_indices: list[int] = []
    for i, segment in enumerate(full.segments[:-2]):
        endpoint_position = bar_position.get(segment.end_dt)
        if endpoint_position is None:
            continue
        if endpoint_position <= anchor_context_bars:
            continue
        eligible_anchor_indices.append(i)
    anchor_indices = _sample_indices(eligible_anchor_indices, max_anchor_windows)

    anchored_windows_checked = 0
    anchored_windows_with_formal_zones = 0
    for anchor_index in anchor_indices:
        segment = full.segments[anchor_index]
        endpoint_position = bar_position[segment.end_dt]
        offset = max(1, endpoint_position - anchor_context_bars)
        anchor = StructureAnchor(
            dt=segment.end_dt,
            value=segment.end_value,
            mark=segment.fx_b.mark,
        )
        result = analyze_bars(bars[offset:], left_anchor=anchor)
        anchored_windows_checked += 1

        if not result.left_boundary_resolved:
            failures.append(
                {
                    "kind": "persisted_anchor",
                    "anchor_segment_index": anchor_index,
                    "raw_bar_offset": offset,
                    "check": "anchor_not_resolved",
                }
            )
            continue

        actual_segments = tuple(_segment_key(x) for x in result.segments)
        expected_segments = reference_segments[
            anchor_index + 1 : anchor_index + 1 + len(actual_segments)
        ]
        if actual_segments != expected_segments:
            failures.append(
                {
                    "kind": "persisted_anchor",
                    "anchor_segment_index": anchor_index,
                    "raw_bar_offset": offset,
                    "check": "formal_segments_not_reference_suffix",
                    "actual_count": len(actual_segments),
                }
            )

        actual_zones = tuple(_zone_key(x) for x in result.central_zones)
        if actual_zones:
            anchored_windows_with_formal_zones += 1
        if not _is_contiguous_subsequence(actual_zones, reference_zones):
            failures.append(
                {
                    "kind": "persisted_anchor",
                    "anchor_segment_index": anchor_index,
                    "raw_bar_offset": offset,
                    "check": "formal_central_zones_not_reference_subsequence",
                    "actual_count": len(actual_zones),
                }
            )

        actual_segment_zones = tuple(
            _segment_zone_key(x) for x in result.segment_central_zones
        )
        if not _is_contiguous_subsequence(
            actual_segment_zones,
            reference_segment_zones,
        ):
            failures.append(
                {
                    "kind": "persisted_anchor",
                    "anchor_segment_index": anchor_index,
                    "raw_bar_offset": offset,
                    "check": "formal_segment_central_zones_not_reference_subsequence",
                    "actual_count": len(actual_segment_zones),
                }
            )

    # 三、锚点已被窗口裁掉时，不得猜测替代起点。
    missing_anchor_checks = 0
    if full.segments:
        old = full.segments[0]
        old_position = bar_position.get(old.end_dt)
        if old_position is not None:
            offset = min(len(bars) - 1, old_position + anchor_context_bars)
            result = analyze_bars(
                bars[offset:],
                left_anchor=StructureAnchor(
                    dt=old.end_dt,
                    value=old.end_value,
                    mark=old.fx_b.mark,
                ),
            )
            missing_anchor_checks += 1
            if (
                result.left_boundary_resolved
                or result.segments
                or result.central_zones
                or result.segment_central_zones
                or result.trading_points
            ):
                failures.append(
                    {
                        "kind": "missing_anchor",
                        "raw_bar_offset": offset,
                        "check": "did_not_fail_closed",
                    }
                )

    return {
        "bars_scanned": count,
        "trusted_origin_reference": {
            "strokes": len(full.strokes),
            "formal_segments": len(full.segments),
            "formal_central_zones": len(full.central_zones),
            "formal_segment_central_zones": len(full.segment_central_zones),
        },
        "unanchored_windows_checked": unanchored_windows_checked,
        "anchored_windows_checked": anchored_windows_checked,
        "anchored_windows_with_formal_zones": anchored_windows_with_formal_zones,
        "missing_anchor_checks": missing_anchor_checks,
        "raw_window_stride": raw_window_stride,
        "minimum_window_bars": minimum_window_bars,
        "anchor_context_bars": anchor_context_bars,
        "max_anchor_windows": max_anchor_windows,
        "failure_count": len(failures),
        "failures": failures[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "验证有限窗口左边界：无锚点时正式结构必须为空；提供持久化线段端点后，"
            "正式线段/中枢只能是完整历史结果的后缀或连续子序列。"
        )
    )
    parser.add_argument("--bars", type=int, default=5000)
    parser.add_argument("--raw-window-stride", type=int, default=250)
    parser.add_argument("--minimum-window-bars", type=int, default=500)
    parser.add_argument("--anchor-context-bars", type=int, default=750)
    parser.add_argument("--max-anchor-windows", type=int, default=20)
    args = parser.parse_args()
    if args.bars <= 0:
        parser.error("--bars 必须大于 0")
    if args.raw_window_stride <= 0:
        parser.error("--raw-window-stride 必须大于 0")
    if args.minimum_window_bars <= 0:
        parser.error("--minimum-window-bars 必须大于 0")
    if args.anchor_context_bars <= 0:
        parser.error("--anchor-context-bars 必须大于 0")
    if args.max_anchor_windows <= 0:
        parser.error("--max-anchor-windows 必须大于 0")

    result = validate(
        args.bars,
        raw_window_stride=args.raw_window_stride,
        minimum_window_bars=args.minimum_window_bars,
        anchor_context_bars=args.anchor_context_bars,
        max_anchor_windows=args.max_anchor_windows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
