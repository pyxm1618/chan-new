"""可选差分测试：安装兼容版 czsc 后直接调用上游包。

运行：pip install -e '.[dev,reference]' && pytest -m reference
"""
from __future__ import annotations

import pytest

from chan_monitor.engine import analyze_bars
from chan_monitor.models import RawBar

pytestmark = pytest.mark.reference


def test_against_installed_czsc_if_compatible() -> None:
    czsc = pytest.importorskip("czsc")
    required = ["RawBar", "Freq", "check_fxs", "remove_include", "NewBar"]
    if not all(hasattr(czsc, name) for name in required):
        pytest.skip("已安装的 czsc 没有暴露旧版 Python 参考 API")

    bars = [
        RawBar.simple(0, 10, 5),
        RawBar.simple(1, 12, 7),
        RawBar.simple(2, 11.5, 8),
        RawBar.simple(3, 11, 6),
        RawBar.simple(4, 9, 4),
        RawBar.simple(5, 10, 6),
    ]
    ours = analyze_bars(bars)
    refs = [
        czsc.RawBar(
            symbol=x.symbol,
            id=i,
            freq=czsc.Freq.F60,
            dt=x.open_time.replace(tzinfo=None),
            open=x.open,
            close=x.close,
            high=x.high,
            low=x.low,
            vol=x.volume,
            amount=x.quote_volume,
        )
        for i, x in enumerate(bars)
    ]
    merged = []
    for bar in refs:
        if len(merged) < 2:
            merged.append(czsc.NewBar(**bar.__dict__, elements=[bar]))
        else:
            included, new_bar = czsc.remove_include(merged[-2], merged[-1], bar)
            if included:
                merged[-1] = new_bar
            else:
                merged.append(new_bar)
    fxs = czsc.check_fxs(merged)
    assert [(x.dt.replace(tzinfo=None), x.mark.value, x.value) for x in ours.fractals] == [
        (x.dt, x.mark.value, x.fx) for x in fxs
    ]
