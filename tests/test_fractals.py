from __future__ import annotations

from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.fractals import check_fractal, remove_include, remove_inclusions
from chan_monitor.models import FractalMark, MergedBar, RawBar


def rb(i: int, high: float, low: float, *, bearish: bool = False) -> RawBar:
    return RawBar.simple(i, high, low, open_=high if bearish else low, close=low if bearish else high)


def mb(i: int, high: float, low: float) -> MergedBar:
    return MergedBar.from_raw(rb(i, high, low), i)


def test_top_fractal_requires_both_high_and_low_strictly_higher() -> None:
    fx = check_fractal(mb(0, 10, 5), mb(1, 12, 7), mb(2, 11, 6), merged_index=1)
    assert fx is not None
    assert fx.mark is FractalMark.TOP
    assert fx.value == 12

    assert check_fractal(mb(0, 10, 5), mb(1, 12, 5), mb(2, 11, 4)) is None
    assert check_fractal(mb(0, 12, 5), mb(1, 12, 7), mb(2, 11, 6)) is None


def test_bottom_fractal_requires_both_high_and_low_strictly_lower() -> None:
    fx = check_fractal(mb(0, 12, 7), mb(1, 10, 5), mb(2, 11, 6), merged_index=1)
    assert fx is not None
    assert fx.mark is FractalMark.BOTTOM
    assert fx.value == 5

    assert check_fractal(mb(0, 12, 5), mb(1, 10, 5), mb(2, 11, 6)) is None
    assert check_fractal(mb(0, 10, 7), mb(1, 10, 5), mb(2, 11, 6)) is None


def test_remove_include_up_direction_uses_higher_high_and_low() -> None:
    k1, k2, k3 = mb(0, 10, 5), mb(1, 12, 7), rb(2, 11, 8, bearish=True)
    included, merged = remove_include(k1, k2, k3)
    assert included is True
    assert (merged.high, merged.low) == (12, 8)
    assert merged.dt == k2.dt
    assert (merged.open, merged.close) == (12, 8)
    assert merged.raw_count == 2


def test_remove_include_down_direction_uses_lower_high_and_low() -> None:
    k1, k2, k3 = mb(0, 12, 7), mb(1, 10, 5), rb(2, 11, 4)
    included, merged = remove_include(k1, k2, k3)
    assert included is True
    assert (merged.high, merged.low) == (10, 4)
    assert merged.dt == k3.open_time
    assert (merged.open, merged.close) == (4, 10)


def test_equal_previous_high_does_not_merge_for_czsc_compatibility() -> None:
    included, merged = remove_include(mb(0, 10, 5), mb(1, 10, 6), rb(2, 9, 7))
    assert included is False
    assert merged.raw_count == 1


def test_pipeline_detects_fractal_only_after_inclusion_removal() -> None:
    bars = [
        rb(0, 10, 5),
        rb(1, 12, 7),
        rb(2, 11.5, 8),  # 被第 2 根包含；向上合并后 low 抬高
        rb(3, 11, 6),
    ]
    result = analyze_bars(bars)
    assert len(result.merged_bars) == 3
    assert result.merge_count == 1
    assert len(result.fractals) == 1
    assert result.fractals[0].mark is FractalMark.TOP
    assert result.fractals[0].elements[1].raw_count == 2


def test_batch_and_incremental_engine_are_identical() -> None:
    bars = [
        rb(0, 10, 5), rb(1, 12, 7), rb(2, 11, 8), rb(3, 9, 4),
        rb(4, 10, 6), rb(5, 13, 8), rb(6, 11, 7), rb(7, 8, 3),
    ]
    expected = analyze_bars(bars)
    actual = FractalEngine().extend(bars)
    assert actual.merged_bars == expected.merged_bars
    assert actual.fractals == expected.fractals
    assert actual.strokes == expected.strokes
    assert actual.unfinished_bars == expected.unfinished_bars


def test_replacing_last_unclosed_bar_recomputes_result() -> None:
    engine = FractalEngine()
    bars = [rb(0, 10, 5), rb(1, 12, 7), rb(2, 11, 6)]
    first = engine.extend(bars)
    assert len(first.fractals) == 1
    replacement = RawBar.simple(2, 13, 8)
    second = engine.update(replacement)
    assert len(second.fractals) == 0
    assert len(second.raw_bars) == 3


def test_remove_inclusions_rejects_duplicate_time() -> None:
    bar = rb(0, 10, 5)
    try:
        remove_inclusions([bar, bar])
    except ValueError as exc:
        assert "严格递增" in str(exc)
    else:
        raise AssertionError("duplicate open_time should fail")


def test_randomized_pipeline_matches_literal_upstream_rules() -> None:
    """用独立的字典版参考实现做确定性随机差分，避免只测少数手工样例。"""
    import random

    def reference(raw):
        merged = []
        for item in raw:
            current = {**item, "elements": [item["i"]]}
            if len(merged) < 2:
                merged.append(current)
                continue
            k1, k2 = merged[-2], merged[-1]
            if k1["high"] < k2["high"]:
                direction = "up"
            elif k1["high"] > k2["high"]:
                direction = "down"
            else:
                merged.append(current)
                continue
            include = (
                (k2["high"] <= item["high"] and k2["low"] >= item["low"])
                or (k2["high"] >= item["high"] and k2["low"] <= item["low"])
            )
            if not include:
                merged.append(current)
                continue
            if direction == "up":
                high = max(k2["high"], item["high"])
                low = max(k2["low"], item["low"])
                dt = k2["dt"] if k2["high"] > item["high"] else item["dt"]
            else:
                high = min(k2["high"], item["high"])
                low = min(k2["low"], item["low"])
                dt = k2["dt"] if k2["low"] < item["low"] else item["dt"]
            merged[-1] = {
                **item,
                "high": high,
                "low": low,
                "dt": dt,
                "elements": sorted(set(k2["elements"] + [item["i"]])),
            }

        fxs = []
        for i in range(1, len(merged) - 1):
            k1, k2, k3 = merged[i - 1], merged[i], merged[i + 1]
            mark = None
            value = None
            if k1["high"] < k2["high"] > k3["high"] and k1["low"] < k2["low"] > k3["low"]:
                mark, value = "G", k2["high"]
            if k1["low"] > k2["low"] < k3["low"] and k1["high"] > k2["high"] < k3["high"]:
                mark, value = "D", k2["low"]
            if mark is None:
                continue
            if len(fxs) >= 2 and mark == fxs[-1][1]:
                continue
            fxs.append((k2["dt"], mark, value))
        return merged, fxs

    rng = random.Random(20260726)
    for case in range(200):
        bars = []
        raw_ref = []
        close = 100.0
        for i in range(60):
            center = close + rng.uniform(-3, 3)
            spread = rng.uniform(0.2, 3)
            low = center - spread
            high = center + spread
            open_ = min(max(close, low), high)
            next_close = rng.uniform(low, high)
            bar = RawBar.simple(case * 100 + i, high, low, open_=open_, close=next_close)
            bars.append(bar)
            raw_ref.append({"i": i, "dt": bar.open_time, "high": high, "low": low, "open": open_, "close": next_close})
            close = next_close

        expected_merged, expected_fxs = reference(raw_ref)
        actual = analyze_bars(bars)
        assert [(x.dt, x.high, x.low) for x in actual.merged_bars] == [
            (x["dt"], x["high"], x["low"]) for x in expected_merged
        ]
        assert [(x.dt, x.mark.value, x.value) for x in actual.fractals] == expected_fxs
