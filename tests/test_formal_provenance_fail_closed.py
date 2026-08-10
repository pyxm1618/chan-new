from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from chan_monitor import detect_trading_points as detect_formal_trading_points
from chan_monitor.data import demo_bars
from chan_monitor.engine import analyze_bars
from chan_monitor.segment_central_zones import detect_segment_central_zones


def _analysis():
    result = analyze_bars(
        demo_bars(1000, symbol="BTCUSDT", interval="5m"),
        left_boundary_anchored=True,
    )
    assert result.segments
    assert len(result.segment_evidence) == len(result.segments)
    return result


def _detect(analysis, evidence):
    zones = detect_segment_central_zones(analysis.segments).zones
    return detect_formal_trading_points(
        analysis.segments,
        zones,
        raw_bars=analysis.raw_bars,
        segment_evidence=evidence,
        macd_history_anchored=True,
    )


def test_formal_detector_rejects_stale_evidence_segment_index_with_diagnostic() -> None:
    analysis = _analysis()
    evidence = list(analysis.segment_evidence)
    evidence[0] = replace(
        evidence[0],
        segment_index=analysis.segments[0].index + 10_000,
    )

    result = _detect(analysis, evidence)

    assert result.points == ()
    assert any(
        item.code == "FORMAL_SEGMENT_EVIDENCE_IDENTITY_MISMATCH"
        for item in result.diagnostics
    )


@pytest.mark.parametrize(
    "invalid_committed_at",
    ["not-a-datetime", datetime(2026, 1, 1)],
)
def test_formal_detector_rejects_invalid_committed_at_with_diagnostic(
    invalid_committed_at,
) -> None:
    analysis = _analysis()
    evidence = list(analysis.segment_evidence)
    evidence[0] = replace(evidence[0], committed_at=invalid_committed_at)

    result = _detect(analysis, evidence)

    assert result.points == ()
    assert any(
        item.code == "FORMAL_SEGMENT_EVIDENCE_COMMIT_TIME_INVALID"
        for item in result.diagnostics
    )
