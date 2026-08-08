from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .fractals import detect_fractals, remove_include, validate_raw_bars
from .models import (
    Fractal,
    FractalMark,
    MergedBar,
    RawBar,
    Stroke,
    StrokeDiagnostic,
    StrokeDirection,
)

# Lesson 77 fixed-level default: a top/bottom fractal pair must leave at least
# one non-included K outside both three-K fractals, hence 3 + 1 + 3 = 7.
# Callers may still pass min_bi_len=6 explicitly for historical CZSC-compatibility
# regressions, but that override is not the original-theory default.
DEFAULT_MIN_BI_LEN = 7


@dataclass(frozen=True, slots=True)
class StrokeDetectionResult:
    strokes: tuple[Stroke, ...]
    unfinished_bars: tuple[MergedBar, ...]
    diagnostics: tuple[StrokeDiagnostic, ...]


def check_bi(
    bars: Sequence[MergedBar],
    *,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
) -> tuple[Stroke | None, list[MergedBar]]:
    """从一段未完成笔的无包含 K 线中查找一笔。

    该函数保持 CZSC ``check_bi`` 的候选笔语义，但默认笔长使用第77课口径：

    1. 起点使用序列中的第一个分型；
    2. 若起点为底分型，从后续更高的顶分型中选择最高者；
       若起点为顶分型，从后续更低的底分型中选择最低者；
    3. 起止分型的价格区间不能互相包含；
    4. 从起点分型第一根 K 到终点分型第三根 K 的无包含 K 数量
       必须不小于 ``min_bi_len``；默认值 7 保证两个三 K 分型之间至少存在
       一根不属于任一分型的独立 K；
    5. 成笔后保留终点分型的三根 K，从其第一根开始寻找下一笔。

    ``min_bi_len=6`` 仅保留给历史 CZSC-compatible 对照，不代表原著默认口径。
    """
    if min_bi_len < 3:
        raise ValueError("min_bi_len 不能小于 3")

    fxs, _ = detect_fractals(bars, czsc_compatibility=True)
    if len(fxs) < 2:
        return None, list(bars)

    fx_a = fxs[0]
    if fx_a.mark is FractalMark.BOTTOM:
        direction = StrokeDirection.UP
        candidates = [
            fx
            for fx in fxs
            if fx.mark is FractalMark.TOP and fx.dt > fx_a.dt and fx.value > fx_a.value
        ]
        fx_b = max(candidates, key=lambda fx: fx.high, default=None)
    elif fx_a.mark is FractalMark.TOP:
        direction = StrokeDirection.DOWN
        candidates = [
            fx
            for fx in fxs
            if fx.mark is FractalMark.BOTTOM and fx.dt > fx_a.dt and fx.value < fx_a.value
        ]
        fx_b = min(candidates, key=lambda fx: fx.low, default=None)
    else:  # pragma: no cover - Enum 已穷尽
        raise ValueError(f"未知分型类型：{fx_a.mark}")

    if fx_b is None:
        return None, list(bars)

    start_dt = fx_a.elements[0].dt
    end_dt = fx_b.elements[2].dt
    bars_a = [x for x in bars if start_dt <= x.dt <= end_dt]
    bars_b = [x for x in bars if x.dt >= fx_b.elements[0].dt]

    ab_include = (fx_a.high > fx_b.high and fx_a.low < fx_b.low) or (
        fx_a.high < fx_b.high and fx_a.low > fx_b.low
    )
    if ab_include or len(bars_a) < min_bi_len:
        return None, list(bars)

    internal_fxs = tuple(x for x in fxs if start_dt <= x.dt <= end_dt)
    stroke = Stroke(
        symbol=fx_a.symbol,
        fx_a=fx_a,
        fx_b=fx_b,
        fractals=internal_fxs,
        direction=direction,
        bars=tuple(bars_a),
    )
    return stroke, bars_b


def detect_strokes(
    raw_bars: Sequence[RawBar],
    *,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
) -> StrokeDetectionResult:
    """从原始 K 线识别全部笔，并持续校正共享端点。

    基础成笔规则沿用 CZSC 的增量状态机；额外补上一个重要的不变量：
    当下一段尚未完成时，如果出现了比上一共享底更低的底，或比上一共享顶
    更高的顶，已经确认的相邻笔必须级联回退，不能继续保留旧共享端点。

    例如 ``顶 A -> 底 B1 -> 顶 C`` 已暂时成笔，但 C 后很快出现更低底 B2，
    且 ``C -> B2`` 因最小笔长不足不能成笔。此时正确结构应回退为
    ``顶 A -> 底 B2``，而不是在后续新高出现后重新得到 ``底 B1 -> 新顶``。
    """
    validate_raw_bars(raw_bars)
    state = _StrokeState(min_bi_len=min_bi_len)
    for bar in raw_bars:
        state.update(bar)
    return StrokeDetectionResult(
        strokes=tuple(state.strokes),
        unfinished_bars=tuple(state.bars_ubi),
        diagnostics=tuple(state.diagnostics),
    )


def validate_stroke_chain(
    strokes: Sequence[Stroke],
    *,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
) -> tuple[StrokeDiagnostic, ...]:
    """检查最终笔链的方向、共享端点、长度和端点极值不变量。"""
    issues: list[StrokeDiagnostic] = []
    for i, stroke in enumerate(strokes):
        expected = (
            (FractalMark.BOTTOM, FractalMark.TOP)
            if stroke.direction is StrokeDirection.UP
            else (FractalMark.TOP, FractalMark.BOTTOM)
        )
        if (stroke.fx_a.mark, stroke.fx_b.mark) != expected:
            issues.append(StrokeDiagnostic(
                code="DIRECTION_MARK_MISMATCH",
                message=f"第 {i} 笔方向与起止分型类型不一致",
                dt=stroke.start_dt,
            ))
        if stroke.length < min_bi_len:
            issues.append(StrokeDiagnostic(
                code="STROKE_TOO_SHORT",
                message=f"第 {i} 笔仅 {stroke.length} 根无包含 K，少于 {min_bi_len}",
                dt=stroke.end_dt,
            ))
        if i == 0:
            continue

        replacement = _more_extreme_shared_endpoint(stroke)
        if replacement is not None:
            issues.append(StrokeDiagnostic(
                code="STALE_SHARED_ENDPOINT",
                message=(
                    f"第 {i} 笔内部存在更极端的{replacement.mark.label} "
                    f"{replacement.value:.12g}，共享起点 {stroke.start_value:.12g} 已失效"
                ),
                dt=replacement.dt,
            ))

        previous = strokes[i - 1]
        if previous.direction is stroke.direction:
            issues.append(StrokeDiagnostic(
                code="DIRECTION_NOT_ALTERNATING",
                message=f"第 {i - 1}、{i} 笔方向未交替",
                dt=stroke.start_dt,
            ))
        if (
            previous.end_dt != stroke.start_dt
            or previous.fx_b.mark is not stroke.fx_a.mark
            or previous.end_value != stroke.start_value
        ):
            issues.append(StrokeDiagnostic(
                code="ENDPOINT_NOT_SHARED",
                message=f"第 {i - 1}、{i} 笔没有共享同一个分型端点",
                dt=stroke.start_dt,
            ))
    return tuple(issues)


@dataclass(slots=True)
class _StrokeState:
    min_bi_len: int = DEFAULT_MIN_BI_LEN
    bars_ubi: list[MergedBar] = field(default_factory=list)
    strokes: list[Stroke] = field(default_factory=list)
    diagnostics: list[StrokeDiagnostic] = field(default_factory=list)
    # 当所有已成笔因端点破坏被回退时，保留原结构起点，避免再次套用
    # “第一笔从所有同型分型中取最极端者”的启动启发式而跳过有效历史端点。
    anchored_start_dt: object | None = None

    def update(self, bar: RawBar) -> None:
        if len(self.bars_ubi) < 2:
            self.bars_ubi.append(MergedBar.from_raw(bar, id_=len(self.bars_ubi)))
        else:
            included, new_bar = remove_include(self.bars_ubi[-2], self.bars_ubi[-1], bar)
            if included:
                self.bars_ubi[-1] = new_bar
            else:
                self.bars_ubi.append(new_bar)
        self._update_bi()

    def _update_bi(self) -> None:
        # 回退时可能需要在同一根最新 K 线上重新形成一到两笔；有限循环既保证
        # 当前批次结果立即稳定，也避免异常数据导致无限重算。
        for _ in range(100):
            if len(self.bars_ubi) < 3:
                return

            if not self.strokes:
                recovering = self.anchored_start_dt is not None
                if recovering:
                    self.bars_ubi = [x for x in self.bars_ubi if x.dt >= self.anchored_start_dt]
                    stroke, remaining = check_bi(self.bars_ubi, min_bi_len=self.min_bi_len)
                    if stroke is None:
                        return
                    self.strokes.append(_with_index(stroke, 0))
                    self.anchored_start_dt = None
                    self.bars_ubi = remaining
                    # 回退恢复后继续使用当前已有数据寻找下一笔。
                    continue

                fxs, _ = detect_fractals(self.bars_ubi, czsc_compatibility=True)
                if not fxs:
                    return

                # 第一笔从首批同型分型中选取更极端的起点；相等时后者覆盖前者。
                fx_a = fxs[0]
                for fx in (x for x in fxs if x.mark is fx_a.mark):
                    if (fx_a.mark is FractalMark.BOTTOM and fx.low <= fx_a.low) or (
                        fx_a.mark is FractalMark.TOP and fx.high >= fx_a.high
                    ):
                        fx_a = fx

                self.bars_ubi = [x for x in self.bars_ubi if x.dt >= fx_a.elements[0].dt]
                stroke, remaining = check_bi(self.bars_ubi, min_bi_len=self.min_bi_len)
                if stroke is not None:
                    self.strokes.append(_with_index(stroke, 0))
                self.bars_ubi = remaining
                return

            candidate, remaining = check_bi(self.bars_ubi, min_bi_len=self.min_bi_len)
            if candidate is not None:
                replacement = _more_extreme_shared_endpoint(candidate)
                if replacement is not None:
                    previous = self.strokes[-1]
                    self._rollback_last(
                        code="SHARED_ENDPOINT_REPLACED",
                        message=(
                            f"候选{candidate.direction.label}笔内部出现更极端的"
                            f"{replacement.mark.label} {replacement.value:.12g} "
                            f"({replacement.dt.isoformat()})，替换旧共享端点 "
                            f"{previous.end_value:.12g} ({previous.end_dt.isoformat()})"
                        ),
                        dt=replacement.dt,
                    )
                    continue

            self.bars_ubi = remaining
            if candidate is not None:
                self.strokes.append(_with_index(candidate, len(self.strokes)))

            self._invalidate_last_if_extended()
            return

        raise RuntimeError("笔结构在 100 次回退后仍未稳定，请检查输入数据")

    def _invalidate_last_if_extended(self) -> bool:
        """保持 CZSC 的最新 K 线同向延伸回退规则。"""
        if not self.strokes or not self.bars_ubi:
            return False

        latest = self.bars_ubi[-1]
        last = self.strokes[-1]
        if last.direction is StrokeDirection.UP:
            if latest.high <= last.end_value:
                return False
            self._rollback_last(
                code="LAST_STROKE_INVALIDATED",
                message=f"向上笔终点被最新无包含 K 新高 {latest.high:.12g} 突破，撤销该笔",
                dt=latest.dt,
            )
            return True

        if latest.low >= last.end_value:
            return False
        self._rollback_last(
            code="LAST_STROKE_INVALIDATED",
            message=f"向下笔终点被最新无包含 K 新低 {latest.low:.12g} 跌破，撤销该笔",
            dt=latest.dt,
        )
        return True

    def _rollback_last(self, *, code: str, message: str, dt) -> None:
        last = self.strokes.pop()
        self.diagnostics.append(StrokeDiagnostic(code=code, message=message, dt=dt))

        # 与 CZSC 增量状态机保持一致：保留被撤销笔的前部 K 线，并从倒数第二根
        # 无包含 K 开始接回当前未完成区。这样既保留原包含处理状态，也让共享端点
        # 附近的后续更极端分型重新参与成笔。
        boundary_dt = last.bars[-2].dt
        self.bars_ubi = list(last.bars[:-2]) + [x for x in self.bars_ubi if x.dt >= boundary_dt]

        if not self.strokes:
            self.anchored_start_dt = last.fx_a.elements[0].dt


def _more_extreme_shared_endpoint(candidate: Stroke) -> Fractal | None:
    """返回候选笔内部比起点更极端的同类分型。"""
    start = candidate.fx_a
    same_mark = [
        fx
        for fx in candidate.fractals
        if fx.dt > start.dt and fx.mark is start.mark
    ]
    if start.mark is FractalMark.BOTTOM:
        lower = [fx for fx in same_mark if fx.low < start.low]
        return min(lower, key=lambda fx: (fx.low, fx.dt), default=None)

    higher = [fx for fx in same_mark if fx.high > start.high]
    return max(higher, key=lambda fx: (fx.high, fx.dt), default=None)


def _with_index(stroke: Stroke, index: int) -> Stroke:
    return Stroke(
        symbol=stroke.symbol,
        fx_a=stroke.fx_a,
        fx_b=stroke.fx_b,
        fractals=stroke.fractals,
        direction=stroke.direction,
        bars=stroke.bars,
        index=index,
    )
