from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_monitor.central_zone_reference import compare_central_zones_with_czsc
from chan_monitor.central_zones import detect_central_zones, validate_central_zones
from chan_monitor.chart import build_raw_chart
from chan_monitor.chart_styles import DEFAULT_CHART_STYLE
from chan_monitor.data import bars_from_csv, demo_bars
from chan_monitor.engine import FractalEngine, analyze_bars
from chan_monitor.models import Fractal, FractalMark, MergedBar, RawBar, Stroke, StrokeDirection


def _fractal(index: int, mark: FractalMark, value: float) -> Fractal:
    center = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index * 10)
    if mark is FractalMark.TOP:
        high, low = value, value - 2
    else:
        high, low = value + 2, value
    bars: list[MergedBar] = []
    for offset in (-1, 0, 1):
        dt = center + timedelta(hours=offset)
        raw = RawBar(
            symbol="TESTUSDT",
            interval="1h",
            open_time=dt,
            close_time=dt + timedelta(hours=1),
            open=low + 0.5,
            high=high,
            low=low,
            close=high - 0.5,
            volume=1,
            quote_volume=1,
            trade_count=1,
        )
        bars.append(MergedBar.from_raw(raw, id_=index * 3 + offset + 1))
    return Fractal(
        symbol="TESTUSDT",
        dt=center,
        mark=mark,
        high=high,
        low=low,
        value=value,
        elements=(bars[0], bars[1], bars[2]),
        merged_index=index,
    )


def _stroke_chain(values: list[float]) -> list[Stroke]:
    points = [
        _fractal(i, FractalMark.BOTTOM if i % 2 == 0 else FractalMark.TOP, value)
        for i, value in enumerate(values)
    ]
    return [
        Stroke(
            symbol="TESTUSDT",
            fx_a=a,
            fx_b=b,
            fractals=(a, b),
            direction=StrokeDirection.UP if a.mark is FractalMark.BOTTOM else StrokeDirection.DOWN,
            bars=(a.elements[1], b.elements[1]),
            index=i,
        )
        for i, (a, b) in enumerate(zip(points, points[1:]))
    ]


def test_three_strokes_form_central_zone_from_overlap() -> None:
    strokes = _stroke_chain([10, 20, 12, 18])
    result = detect_central_zones(strokes)

    assert len(result.groups) == 1
    assert len(result.zones) == 1
    zone = result.zones[0]
    assert zone.stroke_count == 3
    assert zone.zd == 12
    assert zone.zg == 18
    assert zone.zz == 15
    assert zone.gg == 20
    assert zone.dd == 10
    assert zone.is_valid
    assert validate_central_zones(result.zones, strokes) == ()


def test_zone_extends_while_later_strokes_intersect_first_three_overlap() -> None:
    strokes = _stroke_chain([10, 20, 12, 18, 13, 17])
    result = detect_central_zones(strokes)
    zone = result.zones[0]

    assert zone.stroke_count == 5
    assert [x.index for x in zone.strokes] == [0, 1, 2, 3, 4]
    assert (zone.zd, zone.zg) == (12, 18)
    assert zone.is_valid


def test_directional_separation_opens_new_zone_group() -> None:
    # 前五笔围绕 [12, 18]；第六笔向下且最低点为 22，完全位于 ZG=18 上方。
    strokes = _stroke_chain([10, 20, 12, 18, 13, 25, 22])
    result = detect_central_zones(strokes)

    assert len(result.groups) == 2
    assert [x.index for x in result.groups[0].strokes] == [0, 1, 2, 3, 4]
    assert [x.index for x in result.groups[1].strokes] == [5]
    assert len(result.zones) == 1
    assert any(x.code == "CENTRAL_ZONE_GROUP_SPLIT" for x in result.diagnostics)


def test_real_snapshot_central_zones_match_frozen_czsc_logic() -> None:
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, min_bi_len=6, left_boundary_anchored=True)
    # 全部当前笔的结果保留为候选，用于与冻结 CZSC 几何算法做兼容校验。
    comparison = compare_central_zones_with_czsc(
        result.central_zone_candidates,
        result.central_zone_candidate_groups,
        result.strokes,
    )

    assert len(result.central_zone_candidate_groups) == 3
    assert len(result.central_zone_candidates) == 2
    assert [x.stroke_count for x in result.central_zone_candidates] == [13, 11]
    assert [(x.zd, x.zg) for x in result.central_zone_candidates] == [
        (7929.03, 8023.0),
        (9074.34, 9369.8),
    ]
    assert comparison.all_match
    assert validate_central_zones(result.central_zone_candidates, result.strokes) == ()

    # 该测试显式声明输入从冻结样本的真实起点开始，因此首分组允许正式输出。
    assert result.unresolved_central_zones == ()
    # 正式笔中枢只消费已经进入正式线段几何范围的 stable_strokes。
    # 第二个候选中枢仍依赖确认尾部笔，因此留在候选层，不能提前正式输出。
    assert len(result.central_zones) == 1
    assert [x.stroke_count for x in result.central_zones] == [13]
    assert [(x.zd, x.zg) for x in result.central_zones] == [
        (7929.03, 8023.0),
    ]
    assert validate_central_zones(result.central_zones, result.resolved_strokes) == ()


def test_batch_and_incremental_results_include_identical_zones() -> None:
    bars = demo_bars(220)
    expected = analyze_bars(bars, left_boundary_anchored=True)
    actual = FractalEngine(left_boundary_anchored=True).extend(bars)
    assert actual.central_zone_groups == expected.central_zone_groups
    assert actual.central_zones == expected.central_zones
    assert actual.central_zone_diagnostics == expected.central_zone_diagnostics


def test_chart_draws_one_light_blue_rectangle_per_valid_zone() -> None:
    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, left_boundary_anchored=True)
    figure = build_raw_chart(result)

    rectangles = [
        x for x in figure.layout.shapes if x.type == "rect" and x.line.color == "#38BDF8"
    ]
    assert len(rectangles) == len(result.central_zones)
    assert all(x.fillcolor == DEFAULT_CHART_STYLE.central_zone.fillcolor for x in rectangles)
    trace = next(x for x in figure.data if x.name == "笔中枢")
    assert len(trace.x) == len(result.central_zones)
