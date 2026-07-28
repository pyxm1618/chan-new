from __future__ import annotations

from pathlib import Path

from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import analyze_bars
from chan_monitor.reference import compare_with_czsc_reference


def test_synthetic_data_matches_frozen_upstream_reference() -> None:
    result = analyze_bars(demo_bars(180))
    comparison = compare_with_czsc_reference(result)
    assert comparison.all_match
    assert comparison.merged_match_count == len(result.merged_bars)
    assert comparison.fractal_match_count == len(result.fractals)
    assert comparison.stroke_match_count == len(result.strokes)
    assert comparison.unfinished_match_count == len(result.unfinished_bars)


def test_real_btcusdt_snapshot_keeps_base_layers_equal_and_records_pen_corrections() -> None:
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars)
    comparison = compare_with_czsc_reference(result)
    assert len(bars) == 500
    assert len(result.merged_bars) == 336
    assert len(result.fractals) == 170
    assert len(result.strokes) == 26
    assert len(result.unfinished_bars) == 57
    assert comparison.merged_match
    assert comparison.fractal_match
    assert comparison.unfinished_match
    assert comparison.stroke_match_count == 23
    assert not comparison.stroke_match
    assert sum(x.code == "SHARED_ENDPOINT_REPLACED" for x in result.stroke_diagnostics) == 2
