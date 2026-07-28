from __future__ import annotations

"""CZSC v0.9.69 分型与笔核心源码快照。

来源：``czsc/analyze.py`` tag ``v0.9.69``。本文件保留本项目差分需要的
``remove_include``、``check_fx``、``check_fxs``、``check_bi`` 和 CZSC 的
增量成笔状态机。轻量数据类只替代上游对象模型及环境变量依赖。

上游源码：
https://github.com/waditu/czsc/blob/v0.9.69/czsc/analyze.py
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import List

logger = logging.getLogger("czsc.analyze.frozen")


class Mark(Enum):
    G = "G"
    D = "D"


class Direction(Enum):
    Up = "向上"
    Down = "向下"


@dataclass
class RawBar:
    symbol: str
    id: int
    freq: str
    dt: object
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float


@dataclass
class NewBar:
    symbol: str
    id: int
    freq: str
    dt: object
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    elements: list[RawBar]

    @property
    def raw_bars(self):
        return self.elements


@dataclass
class FX:
    symbol: str
    dt: object
    mark: Mark
    high: float
    low: float
    fx: float
    elements: list[NewBar]


@dataclass
class BI:
    symbol: str
    fx_a: FX
    fx_b: FX
    fxs: list[FX]
    direction: Direction
    bars: list[NewBar] = field(default_factory=list)

    @property
    def sdt(self):
        return self.fx_a.dt

    @property
    def edt(self):
        return self.fx_b.dt

    @property
    def high(self):
        return max(self.fx_a.high, self.fx_b.high)

    @property
    def low(self):
        return min(self.fx_a.low, self.fx_b.low)


# 以下函数控制流与 CZSC v0.9.69 czsc/analyze.py 保持一致。
def remove_include(k1: NewBar, k2: NewBar, k3: RawBar):
    """去除包含关系：输入三根k线，其中k1和k2为没有包含关系的K线，k3为原始K线"""
    if k1.high < k2.high:
        direction = Direction.Up
    elif k1.high > k2.high:
        direction = Direction.Down
    else:
        k4 = NewBar(symbol=k3.symbol, id=k3.id, freq=k3.freq, dt=k3.dt, open=k3.open,
                    close=k3.close, high=k3.high, low=k3.low, vol=k3.vol, amount=k3.amount, elements=[k3])
        return False, k4
    if (k2.high <= k3.high and k2.low >= k3.low) or (k2.high >= k3.high and k2.low <= k3.low):
        if direction == Direction.Up:
            high = max(k2.high, k3.high)
            low = max(k2.low, k3.low)
            dt = k2.dt if k2.high > k3.high else k3.dt
        elif direction == Direction.Down:
            high = min(k2.high, k3.high)
            low = min(k2.low, k3.low)
            dt = k2.dt if k2.low < k3.low else k3.dt
        else:  # pragma: no cover
            raise ValueError

        open_, close = (high, low) if k3.open > k3.close else (low, high)
        vol = k2.vol + k3.vol
        amount = k2.amount + k3.amount
        elements = [x for x in k2.elements[:100] if x.dt != k3.dt] + [k3]
        k4 = NewBar(symbol=k3.symbol, id=k2.id, freq=k2.freq, dt=dt, open=open_,
                    close=close, high=high, low=low, vol=vol, amount=amount, elements=elements)
        return True, k4
    else:
        k4 = NewBar(symbol=k3.symbol, id=k3.id, freq=k3.freq, dt=k3.dt, open=k3.open,
                    close=k3.close, high=k3.high, low=k3.low, vol=k3.vol, amount=k3.amount, elements=[k3])
        return False, k4


def check_fx(k1: NewBar, k2: NewBar, k3: NewBar):
    """查找分型"""
    fx = None
    if k1.high < k2.high > k3.high and k1.low < k2.low > k3.low:
        fx = FX(symbol=k1.symbol, dt=k2.dt, mark=Mark.G, high=k2.high,
                low=k2.low, fx=k2.high, elements=[k1, k2, k3])
    if k1.low > k2.low < k3.low and k1.high > k2.high < k3.high:
        fx = FX(symbol=k1.symbol, dt=k2.dt, mark=Mark.D, high=k2.high,
                low=k2.low, fx=k2.low, elements=[k1, k2, k3])
    return fx


def check_fxs(bars: List[NewBar]) -> List[FX]:
    """输入一串无包含关系K线，查找其中所有分型"""
    fxs = []
    for i in range(1, len(bars) - 1):
        fx = check_fx(bars[i - 1], bars[i], bars[i + 1])
        if isinstance(fx, FX):
            if len(fxs) >= 2 and fx.mark == fxs[-1].mark:
                logger.error(f"check_fxs错误: {bars[i].dt}，{fx.mark}，{fxs[-1].mark}")
            else:
                fxs.append(fx)
    return fxs


def check_bi(bars: List[NewBar], min_bi_len: int = 6):
    """输入一串无包含关系K线，查找其中的一笔。"""
    fxs = check_fxs(bars)
    if len(fxs) < 2:
        return None, bars

    fx_a = fxs[0]
    if fx_a.mark == Mark.D:
        direction = Direction.Up
        fxs_b = (x for x in fxs if x.mark == Mark.G and x.dt > fx_a.dt and x.fx > fx_a.fx)
        fx_b = max(fxs_b, key=lambda fx: fx.high, default=None)
    elif fx_a.mark == Mark.G:
        direction = Direction.Down
        fxs_b = (x for x in fxs if x.mark == Mark.D and x.dt > fx_a.dt and x.fx < fx_a.fx)
        fx_b = min(fxs_b, key=lambda fx: fx.low, default=None)
    else:  # pragma: no cover
        raise ValueError

    if fx_b is None:
        return None, bars

    bars_a = [x for x in bars if fx_a.elements[0].dt <= x.dt <= fx_b.elements[2].dt]
    bars_b = [x for x in bars if x.dt >= fx_b.elements[0].dt]
    ab_include = (fx_a.high > fx_b.high and fx_a.low < fx_b.low) or \
                 (fx_a.high < fx_b.high and fx_a.low > fx_b.low)

    if (not ab_include) and (len(bars_a) >= min_bi_len):
        fxs_ = [x for x in fxs if fx_a.elements[0].dt <= x.dt <= fx_b.elements[2].dt]
        bi = BI(symbol=fx_a.symbol, fx_a=fx_a, fx_b=fx_b, fxs=fxs_, direction=direction, bars=bars_a)
        return bi, bars_b
    return None, bars


class FrozenCZSC:
    """仅用于差分的 v0.9.69 增量成笔状态机。"""

    def __init__(self, bars: List[RawBar] | None = None, min_bi_len: int = 6):
        self.min_bi_len = min_bi_len
        self.bars_raw: list[RawBar] = []
        self.bars_ubi: list[NewBar] = []
        self.bi_list: list[BI] = []
        for bar in bars or []:
            self.update(bar)

    def _update_bi(self):
        bars_ubi = self.bars_ubi
        if len(bars_ubi) < 3:
            return

        if not self.bi_list:
            fxs = check_fxs(bars_ubi)
            if not fxs:
                return
            fx_a = fxs[0]
            fxs_a = [x for x in fxs if x.mark == fx_a.mark]
            for fx in fxs_a:
                if (fx_a.mark == Mark.D and fx.low <= fx_a.low) or \
                        (fx_a.mark == Mark.G and fx.high >= fx_a.high):
                    fx_a = fx
            bars_ubi = [x for x in bars_ubi if x.dt >= fx_a.elements[0].dt]
            bi, bars_ubi_ = check_bi(bars_ubi, self.min_bi_len)
            if isinstance(bi, BI):
                self.bi_list.append(bi)
            self.bars_ubi = bars_ubi_
            return

        bi, bars_ubi_ = check_bi(bars_ubi, self.min_bi_len)
        self.bars_ubi = bars_ubi_
        if isinstance(bi, BI):
            self.bi_list.append(bi)

        last_bi = self.bi_list[-1]
        bars_ubi = self.bars_ubi
        if (last_bi.direction == Direction.Up and bars_ubi[-1].high > last_bi.high) or \
                (last_bi.direction == Direction.Down and bars_ubi[-1].low < last_bi.low):
            self.bars_ubi = last_bi.bars[:-2] + [x for x in bars_ubi if x.dt >= last_bi.bars[-2].dt]
            self.bi_list.pop(-1)

    def update(self, bar: RawBar):
        if not self.bars_raw or bar.dt != self.bars_raw[-1].dt:
            self.bars_raw.append(bar)
            last_bars = [bar]
        else:
            self.bars_raw[-1] = bar
            last_bars = self.bars_ubi.pop(-1).raw_bars
            assert bar.dt == last_bars[-1].dt
            last_bars[-1] = bar

        bars_ubi = self.bars_ubi
        for current in last_bars:
            if len(bars_ubi) < 2:
                bars_ubi.append(NewBar(symbol=current.symbol, id=current.id, freq=current.freq, dt=current.dt,
                                       open=current.open, close=current.close, amount=current.amount,
                                       high=current.high, low=current.low, vol=current.vol, elements=[current]))
            else:
                k1, k2 = bars_ubi[-2:]
                has_include, k3 = remove_include(k1, k2, current)
                if has_include:
                    bars_ubi[-1] = k3
                else:
                    bars_ubi.append(k3)
        self.bars_ubi = bars_ubi
        self._update_bi()
