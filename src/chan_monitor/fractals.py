from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from .models import Fractal, FractalDiagnostic, FractalMark, MergedBar, RawBar, unique_elements


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"


def bars_include(a: MergedBar, b: RawBar | MergedBar) -> bool:
    """两根 K 线是否存在包含关系，边界相等也算包含。"""
    return (a.high <= b.high and a.low >= b.low) or (a.high >= b.high and a.low <= b.low)


def remove_include(k1: MergedBar, k2: MergedBar, k3: RawBar) -> tuple[bool, MergedBar]:
    """按 CZSC 的方向规则处理 k2 与原始 k3 的包含关系。

    该函数逐项复刻上游 ``remove_include`` 的关键语义：
    - 趋势方向由无包含关系的 k1、k2 的 high 决定；
    - 向上时取较高的 high 与较高的 low；
    - 向下时取较低的 high 与较低的 low；
    - k1.high == k2.high 时不做包含合并。
    """
    if k1.high < k2.high:
        direction = Direction.UP
    elif k1.high > k2.high:
        direction = Direction.DOWN
    else:
        return False, MergedBar.from_raw(k3, id_=k3_index(k3, k2.id + 1))

    if not bars_include(k2, k3):
        return False, MergedBar.from_raw(k3, id_=k3_index(k3, k2.id + 1))

    if direction is Direction.UP:
        high = max(k2.high, k3.high)
        low = max(k2.low, k3.low)
        dt = k2.dt if k2.high > k3.high else k3.open_time
    else:
        high = min(k2.high, k3.high)
        low = min(k2.low, k3.low)
        dt = k2.dt if k2.low < k3.low else k3.open_time

    open_, close = (high, low) if k3.open > k3.close else (low, high)
    elements = unique_elements((*k2.elements, k3))
    merged = MergedBar(
        id=k2.id,
        symbol=k3.symbol,
        interval=k3.interval,
        dt=dt,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=k2.volume + k3.volume,
        quote_volume=k2.quote_volume + k3.quote_volume,
        elements=elements,
    )
    return True, merged


def remove_inclusions(raw_bars: Sequence[RawBar]) -> tuple[list[MergedBar], int]:
    """将原始 K 线转换成无包含 K 线序列，并返回合并次数。"""
    validate_raw_bars(raw_bars)
    merged: list[MergedBar] = []
    merge_count = 0
    for index, bar in enumerate(raw_bars):
        if len(merged) < 2:
            merged.append(MergedBar.from_raw(bar, id_=index))
            continue

        has_include, new_bar = remove_include(merged[-2], merged[-1], bar)
        if has_include:
            merged[-1] = new_bar
            merge_count += 1
        else:
            merged.append(new_bar)
    return merged, merge_count


def check_fractal(k1: MergedBar, k2: MergedBar, k3: MergedBar, *, merged_index: int = -1) -> Fractal | None:
    """检查三根无包含 K 线是否构成严格顶/底分型。"""
    if k1.high < k2.high > k3.high and k1.low < k2.low > k3.low:
        return Fractal(
            symbol=k1.symbol,
            dt=k2.dt,
            mark=FractalMark.TOP,
            high=k2.high,
            low=k2.low,
            value=k2.high,
            elements=(k1, k2, k3),
            merged_index=merged_index,
        )

    if k1.low > k2.low < k3.low and k1.high > k2.high < k3.high:
        return Fractal(
            symbol=k1.symbol,
            dt=k2.dt,
            mark=FractalMark.BOTTOM,
            high=k2.high,
            low=k2.low,
            value=k2.low,
            elements=(k1, k2, k3),
            merged_index=merged_index,
        )
    return None


def detect_fractals(
    bars: Sequence[MergedBar], *, czsc_compatibility: bool = True
) -> tuple[list[Fractal], list[FractalDiagnostic]]:
    """查找所有分型。

    ``czsc_compatibility=True`` 时，复刻当前上游 ``check_fxs`` 的过滤条件：
    从第三个已接纳分型开始，若与前一个分型同型，则丢弃并记录诊断。
    同时保留候选检测的严格三 K 线定义。
    """
    fractals: list[Fractal] = []
    diagnostics: list[FractalDiagnostic] = []
    for i in range(1, len(bars) - 1):
        fx = check_fractal(bars[i - 1], bars[i], bars[i + 1], merged_index=i)
        if fx is None:
            continue
        if czsc_compatibility and len(fractals) >= 2 and fx.mark == fractals[-1].mark:
            diagnostics.append(
                FractalDiagnostic(
                    code="NON_ALTERNATING_FRACTAL",
                    message=f"同型分型被 CZSC 兼容规则过滤：{fx.label}",
                    dt=fx.dt,
                )
            )
            continue
        fractals.append(fx)
    return fractals, diagnostics


def validate_raw_bars(raw_bars: Sequence[RawBar]) -> None:
    if not raw_bars:
        return
    previous = raw_bars[0]
    for current in raw_bars[1:]:
        if current.symbol != previous.symbol or current.interval != previous.interval:
            raise ValueError("同一次分析中的 symbol 与 interval 必须一致")
        if current.open_time <= previous.open_time:
            raise ValueError("K 线必须按 open_time 严格递增且不能重复")
        previous = current


def k3_index(k3: RawBar, fallback: int) -> int:
    """MergedBar.id 只用于展示；没有全局索引时使用顺序回退值。"""
    del k3
    return fallback
