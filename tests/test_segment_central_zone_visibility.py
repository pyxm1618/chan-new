from pathlib import Path


def test_app_explains_missing_segment_central_zone() -> None:
    text = Path("app.py").read_text(encoding="utf-8")
    assert "线段中枢至少需要 3 条连续已确认线段" in text
    assert "无三段共同重叠" in text
    assert 'APP_VERSION = "0.10.13"' in text


def test_chart_contains_segment_zone_status_annotation() -> None:
    text = Path("src/chan_monitor/chart.py").read_text(encoding="utf-8")
    assert "_add_segment_central_zone_status" in text
    assert "当前仅" in text
    assert "无连续三段共同重叠" in text


def test_app_displays_feature_sequence_tail_coverage_metrics() -> None:
    text = Path("app.py").read_text(encoding="utf-8")
    assert 'fc3.metric("扫描至笔位置"' in text
    assert 'fc4.metric("尾部未扫描笔数"' in text
    assert "feature_tail_gap" in text
