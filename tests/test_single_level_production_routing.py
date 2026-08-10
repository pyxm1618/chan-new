from __future__ import annotations

import chan_monitor
import chan_monitor.engine as engine


def test_package_api_routes_to_formal_single_level_detector() -> None:
    assert chan_monitor.detect_trading_points.__module__ == (
        "chan_monitor.formal_single_level_trading_points"
    )
    assert chan_monitor.validate_trading_points.__module__ == (
        "chan_monitor.formal_single_level_trading_points"
    )


def test_engine_routes_to_formal_single_level_detector() -> None:
    assert engine.detect_trading_points.__module__ == (
        "chan_monitor.formal_single_level_trading_points"
    )
