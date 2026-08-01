from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from chan_monitor.engine import StructureState
from chan_monitor.models import RawBar
from chan_monitor.segments import SegmentMode


def _stress_bars(seed: int, count: int = 1000) -> list[RawBar]:
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


def _run(seed: int) -> tuple[StructureState, dict[int, tuple[int, int, int, int]]]:
    state = StructureState(
        min_bi_len=6,
        segment_mode=SegmentMode.FEATURE_SEQUENCE,
        left_boundary_anchored=True,
    )
    snapshots: dict[int, tuple[int, int, int, int]] = {}
    for position, bar in enumerate(_stress_bars(seed), 1):
        state.update(bar)
        if position in {300, 600, 1000}:
            snapshots[position] = (
                len(state.detected_strokes),
                len(state.canonical_strokes),
                len(state.stable_strokes),
                len(state.segments),
            )
    return state, snapshots


def test_shared_endpoint_replacement_does_not_permanently_stop_formal_structure() -> None:
    # 这两个种子在 v0.10.14 会在共享端点迁移后永久冻结：
    # seed=159 最终停在 9 笔/1 段，seed=188 停在 15 笔/1 段。
    for seed in (159, 188):
        state, snapshots = _run(seed)
        assert any(
            item.code == "SHARED_ENDPOINT_REPLACED"
            for item in state.stroke_state.diagnostics
        )
        # 正式链不再丢失尾部，完整检测链与规范链持续同步推进。
        assert len(state.canonical_strokes) == len(state.detected_strokes)
        assert state.canonical_strokes == state.stable_strokes + state.provisional_strokes
        # 后续结构必须继续增长，不能只满足“旧前缀不回撤”却永久停更。
        assert snapshots[1000][2] > snapshots[300][2]
        assert snapshots[1000][3] > snapshots[300][3]
        assert len(state.segments) >= 5


def test_stable_prefix_ends_at_formal_segment_geometry_not_confirmation_tail() -> None:
    state, _ = _run(159)
    assert state.evidence
    last = state.evidence[-1]
    assert last.end_position == len(state.stable_strokes) - 1
    assert last.confirmed_at_position >= len(state.stable_strokes)
