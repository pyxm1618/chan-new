from __future__ import annotations

from chan_monitor.chart import build_raw_chart, provenance_text
from chan_monitor.chart_styles import DEFAULT_CHART_STYLE
from chan_monitor.data import demo_bars
from chan_monitor.engine import analyze_bars
from chan_monitor.metadata import AnalysisMetadata


def test_chart_has_complete_provenance() -> None:
    metadata = AnalysisMetadata(
        source_name="Binance REST API",
        market="Binance 现货",
        source_url="https://example.test/klines",
    )
    result = analyze_bars(demo_bars(30, symbol="BTCUSDT", interval="1h"), metadata=metadata, left_boundary_anchored=True)
    figure = build_raw_chart(result)
    annotation_text = " ".join(x.text for x in figure.layout.annotations)
    assert "Binance 现货" in annotation_text
    assert "BTCUSDT" in annotation_text
    assert "1h" in annotation_text
    assert "数据源：Binance REST API" in annotation_text
    assert "<br>" in annotation_text
    assert "首根：" in annotation_text
    assert "末根：" in annotation_text
    assert "币种：BTCUSDT" in provenance_text(result)


def test_demo_chart_has_watermark() -> None:
    result = analyze_bars(demo_bars(30), metadata=AnalysisMetadata.demo(), left_boundary_anchored=True)
    figure = build_raw_chart(result)
    assert any("DEMO / 模拟数据" in x.text for x in figure.layout.annotations)


def test_default_segment_style_is_thinner() -> None:
    from pathlib import Path

    from chan_monitor.data import bars_from_csv

    root = Path(__file__).resolve().parents[1]
    path = next((root / "artifacts" / "real").glob("*0100_bars.csv"))
    bars = bars_from_csv(path, symbol="BTCUSDT", interval="1h")
    result = analyze_bars(bars, left_boundary_anchored=True)
    figure = build_raw_chart(result)
    trace = next(x for x in figure.data if x.name == "线段")
    assert trace.line.width == DEFAULT_CHART_STYLE.segment.width
    assert trace.line.width < 3
    assert trace.line.color == DEFAULT_CHART_STYLE.segment.color


def test_fullscreen_header_is_compact() -> None:
    result = analyze_bars(
        demo_bars(500, symbol="BTCUSDT", interval="5m"),
        metadata=AnalysisMetadata(
            source_name="Binance REST API",
            market="Binance 现货",
        ),
    )
    figure = build_raw_chart(result)
    assert figure.layout.margin.t <= 160

    title = next(x for x in figure.layout.annotations if "BTCUSDT" in x.text)
    provenance = next(x for x in figure.layout.annotations if "数据源：" in x.text)
    assert title.y <= 1.18
    assert provenance.y <= 1.12
    assert provenance.text.count("<br>") <= 3
    assert "首根：" in provenance.text
    assert "末根：" in provenance.text
    assert "中枢：" in provenance.text
