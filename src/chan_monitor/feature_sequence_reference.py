from __future__ import annotations

"""标准特征序列的独立差分参考实现。

本模块不导入 ``segments.py`` 中的识别器或辅助函数。它用另一套可变状态对象
重新表达同一组原文规则，用于发现生产实现中的状态回退、包含处理和缺口确认错误。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import pandas as pd

from .models import FractalMark, Segment, SegmentEvidence, Stroke, StrokeDirection

REFERENCE_NAME = "独立标准特征序列状态机（原文规则 + chan.py actual_break/reset）"
REFERENCE_URL = "https://github.com/Vespa314/chan.py/blob/main/Seg/EigenFX.py"
_EPS = 1e-12


class _RefBreakStatus(str, Enum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    REJECTED = "rejected"


@dataclass(slots=True)
class _RefElement:
    positions: list[int]
    high: float
    low: float
    merge_up: bool


@dataclass(slots=True)
class _RefFX:
    boundary: int
    gap: bool
    status: _RefBreakStatus
    detected: int
    mark: FractalMark
    right_end: int

    @property
    def actual(self) -> bool:
        return self.status is _RefBreakStatus.CONFIRMED


@dataclass(slots=True)
class _RefDetector:
    strokes: Sequence[Stroke]
    line_up: bool
    begin: int
    raw: list[int]
    elements: list[_RefElement]

    @classmethod
    def create(cls, strokes: Sequence[Stroke], *, line_up: bool, begin: int) -> "_RefDetector":
        return cls(strokes=strokes, line_up=line_up, begin=begin, raw=[], elements=[])

    def accepts(self, pos: int) -> bool:
        expected = StrokeDirection.DOWN if self.line_up else StrokeDirection.UP
        return self.strokes[pos].direction is expected

    def feed(self, pos: int) -> _RefFX | None:
        if not self.accepts(pos):
            return None
        self.raw.append(pos)
        return self._consume(pos)

    def _consume(self, pos: int) -> _RefFX | None:
        bi = self.strokes[pos]
        if not self.elements:
            self.elements.append(_RefElement([pos], bi.high, bi.low, self.line_up))
            return None

        if len(self.elements) == 1:
            old = self.elements[0]
            rel = _classify(old.high, old.low, bi.high, bi.low, special=True)
            if rel == "merge":
                _merge_element(old, bi, pos)
                return None
            new = _RefElement([pos], bi.high, bi.low, self.line_up)
            self.elements.append(new)
            impossible = (self.line_up and new.high < old.high - _EPS) or (
                not self.line_up and new.low > old.low + _EPS
            )
            return self._restart() if impossible else None

        if len(self.elements) != 2:
            raise RuntimeError("参考特征序列状态损坏")

        mid = self.elements[1]
        rel = _classify(
            mid.high,
            mid.low,
            bi.high,
            bi.low,
            special=False,
            equal_top=1 if self.line_up else -1,
        )
        if rel == "merge":
            _merge_element(mid, bi, pos)
            return None
        merge_up = rel == "up"
        self.elements.append(_RefElement([pos], bi.high, bi.low, merge_up))
        fx = self._evaluate()
        return fx if fx is not None else self._restart()

    def _restart(self) -> _RefFX | None:
        rest = self.raw[1:]
        self.raw = []
        self.elements = []
        for pos in rest:
            self.raw.append(pos)
            fx = self._consume(pos)
            if fx is not None:
                return fx
        return None

    def _evaluate(self) -> _RefFX | None:
        a, b, c = self.elements
        if self.line_up:
            if not (a.high < b.high - _EPS and c.high <= b.high + _EPS and c.low < b.low - _EPS):
                return None
            peak_pos = max(b.positions, key=lambda p: (self.strokes[p].high, p))
            status, detected = _break_down(self.strokes, b, c)
            return _RefFX(
                boundary=peak_pos,
                gap=a.high < b.low - _EPS,
                status=status,
                detected=detected,
                mark=FractalMark.TOP,
                right_end=c.positions[-1],
            )
        if not (a.low > b.low + _EPS and c.low >= b.low - _EPS and c.high > b.high + _EPS):
            return None
        peak_pos = min(b.positions, key=lambda p: (self.strokes[p].low, -p))
        status, detected = _break_up(self.strokes, b, c)
        return _RefFX(
            boundary=peak_pos,
            gap=a.low > b.high + _EPS,
            status=status,
            detected=detected,
            mark=FractalMark.BOTTOM,
            right_end=c.positions[-1],
        )


@dataclass(frozen=True, slots=True)
class RefSegment:
    start: int
    end: int
    direction: StrokeDirection
    confirmation: str
    confirmed_at: int


@dataclass(frozen=True, slots=True)
class FeatureSequenceComparison:
    reference_name: str
    reference_url: str
    segment_rows: tuple[dict[str, object], ...]
    evidence_rows: tuple[dict[str, object], ...]

    @property
    def segment_match_count(self) -> int:
        return sum(bool(row["一致"]) for row in self.segment_rows)

    @property
    def evidence_match_count(self) -> int:
        return sum(bool(row["一致"]) for row in self.evidence_rows)

    @property
    def all_match(self) -> bool:
        return self.segment_match_count == len(self.segment_rows) and self.evidence_match_count == len(self.evidence_rows)

    def segment_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.segment_rows)

    def evidence_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.evidence_rows)

    def summary(self) -> dict[str, object]:
        return {
            "feature_sequence_reference_name": self.reference_name,
            "feature_sequence_reference_url": self.reference_url,
            "feature_sequence_segment_rows": len(self.segment_rows),
            "feature_sequence_segment_match_count": self.segment_match_count,
            "feature_sequence_evidence_rows": len(self.evidence_rows),
            "feature_sequence_evidence_match_count": self.evidence_match_count,
            "feature_sequence_all_match": self.all_match,
        }


def run_feature_sequence_reference(strokes: Sequence[Stroke]) -> tuple[RefSegment, ...]:
    values = tuple(strokes)
    if len(values) < 3:
        return ()

    first_candidates: list[RefSegment] = []
    for begin in range(max(0, len(values) - 2)):
        if not _overlap_first_three(values, begin):
            continue
        candidate = _scan(values, begin)
        if candidate is None or not _first_segment_extremes_valid(
            values, candidate.start, candidate.end
        ):
            continue
        first_candidates.append(candidate)

    if not first_candidates:
        return ()

    def first_key(candidate: RefSegment) -> tuple[int, float, int, int]:
        start_value = values[candidate.start].fx_a.value
        extreme_key = (
            start_value
            if candidate.direction is StrokeDirection.UP
            else -start_value
        )
        return candidate.end, extreme_key, -candidate.start, candidate.confirmed_at

    first = min(first_candidates, key=first_key)
    output = [first]
    begin = first.end
    while len(values) - begin >= 3:
        nxt = _scan(values, begin)
        if nxt is None:
            break
        output.append(nxt)
        begin = nxt.end
    return tuple(output)


def compare_feature_sequence_reference(
    segments: Sequence[Segment],
    evidence: Sequence[SegmentEvidence],
    strokes: Sequence[Stroke],
) -> FeatureSequenceComparison:
    ref = run_feature_sequence_reference(strokes)
    segment_rows: list[dict[str, object]] = []
    total = max(len(segments), len(ref))
    for i in range(total):
        ours = segments[i] if i < len(segments) else None
        expected = ref[i] if i < len(ref) else None
        match = bool(
            ours is not None
            and expected is not None
            and ours.direction is expected.direction
            and _point_key(ours.fx_a) == _point_key(strokes[expected.start].fx_a)
            and _point_key(ours.fx_b) == _point_key(strokes[expected.end].fx_a)
            and ours.stroke_count == expected.end - expected.start
        )
        segment_rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目方向": ours.direction.label if ours else None,
                "参考方向": expected.direction.label if expected else None,
                "本项目起点": ours.start_dt if ours else None,
                "参考起点": strokes[expected.start].fx_a.dt if expected else None,
                "本项目终点": ours.end_dt if ours else None,
                "参考终点": strokes[expected.end].fx_a.dt if expected else None,
                "本项目笔数": ours.stroke_count if ours else None,
                "参考笔数": expected.end - expected.start if expected else None,
            }
        )

    evidence_rows: list[dict[str, object]] = []
    total_ev = max(len(evidence), len(ref))
    for i in range(total_ev):
        ours = evidence[i] if i < len(evidence) else None
        expected = ref[i] if i < len(ref) else None
        match = bool(
            ours is not None
            and expected is not None
            and ours.start_position == expected.start
            and ours.end_position == expected.end
            and ours.confirmation == expected.confirmation
            and ours.confirmed_at_position == expected.confirmed_at
        )
        evidence_rows.append(
            {
                "序号": i,
                "一致": match,
                "本项目确认方式": ours.confirmation if ours else None,
                "参考确认方式": expected.confirmation if expected else None,
                "本项目确认笔位置": ours.confirmed_at_position if ours else None,
                "参考确认笔位置": expected.confirmed_at if expected else None,
            }
        )
    return FeatureSequenceComparison(
        reference_name=REFERENCE_NAME,
        reference_url=REFERENCE_URL,
        segment_rows=tuple(segment_rows),
        evidence_rows=tuple(evidence_rows),
    )


def _scan(strokes: Sequence[Stroke], begin: int) -> RefSegment | None:
    """独立事件回放。

    主特征序列会完整收集并按“实际检测时间”排序候选，避免检测器重放后
    才产出的更早候选被遗漏；有缺口等待期间则按原始同类笔端点持续迁移
    极值，直到反向特征分型锁定当前端点。
    """
    line_up = strokes[begin].direction is StrokeDirection.UP
    candidates = _trace_ref_candidates(strokes, line_up=line_up, begin=begin)
    confirmed = [
        fx
        for fx in candidates
        if fx.status is _RefBreakStatus.CONFIRMED
        and _valid_boundary(strokes, begin, fx.boundary)
    ]
    if not confirmed:
        return None

    first_time = min(fx.detected for fx in confirmed)
    first_group = [fx for fx in confirmed if fx.detected == first_time]
    if line_up:
        first = max(
            first_group,
            key=lambda fx: (
                strokes[fx.boundary].fx_a.value,
                fx.boundary,
                -fx.detected,
            ),
        )
    else:
        first = min(
            first_group,
            key=lambda fx: (
                strokes[fx.boundary].fx_a.value,
                -fx.boundary,
                fx.detected,
            ),
        )

    if not first.gap:
        return RefSegment(
            begin,
            first.boundary,
            strokes[begin].direction,
            "NO_GAP",
            first.detected,
        )

    active = first.boundary
    active_value = strokes[active].fx_a.value
    reverse = _find_reverse_confirmation(strokes, active, line_up=line_up)
    expected = StrokeDirection.DOWN if line_up else StrokeDirection.UP

    for pos in range(active + 1, len(strokes)):
        if reverse is not None and reverse.detected < pos:
            return RefSegment(
                begin,
                active,
                strokes[begin].direction,
                "GAP_REVERSE_FRACTAL",
                reverse.detected,
            )
        stroke = strokes[pos]
        if stroke.direction is not expected:
            continue
        value = stroke.fx_a.value
        more_extreme = (
            value > active_value + _EPS
            if line_up
            else value < active_value - _EPS
        ) or (abs(value - active_value) <= _EPS and pos > active)
        if not more_extreme:
            continue
        active = pos
        active_value = value
        reverse = _find_reverse_confirmation(strokes, active, line_up=line_up)

    if reverse is None:
        return None
    return RefSegment(
        begin,
        active,
        strokes[begin].direction,
        "GAP_REVERSE_FRACTAL",
        reverse.detected,
    )


def _trace_ref_candidates(
    strokes: Sequence[Stroke], *, line_up: bool, begin: int
) -> list[_RefFX]:
    detector = _RefDetector.create(strokes, line_up=line_up, begin=begin)
    candidates: list[_RefFX] = []
    seen: set[tuple] = set()
    position = begin + 1
    pending: _RefFX | None = None
    guard = max(32, len(strokes) * 8)
    steps = 0
    while position < len(strokes) or pending is not None:
        steps += 1
        if steps > guard:  # pragma: no cover - 状态机死循环防御
            raise RuntimeError("参考特征序列回放超过安全步数")
        if pending is not None:
            fx = pending
            pending = None
        else:
            fx = detector.feed(position)
            position += 1
        if fx is None:
            continue
        signature = (
            fx.boundary,
            fx.gap,
            fx.status,
            fx.detected,
            fx.mark,
            fx.right_end,
        )
        if signature not in seen:
            seen.add(signature)
            candidates.append(fx)
        pending = detector._restart()
    return candidates


def _find_reverse_confirmation(
    strokes: Sequence[Stroke], endpoint: int, *, line_up: bool
) -> _RefFX | None:
    detector = _RefDetector.create(strokes, line_up=not line_up, begin=endpoint)
    pos = endpoint + 1
    pending: _RefFX | None = None
    while pos < len(strokes) or pending is not None:
        if pending is not None:
            fx = pending
            pending = None
        else:
            fx = detector.feed(pos)
            pos += 1
        if fx is None:
            continue
        if fx.status is _RefBreakStatus.CONFIRMED:
            return fx
        if fx.status is _RefBreakStatus.PENDING:
            return None
        pending = detector._restart()
    return None

def _classify(
    h1: float,
    l1: float,
    h2: float,
    l2: float,
    *,
    special: bool,
    equal_top: int | None = None,
) -> str:
    if h1 >= h2 - _EPS and l1 <= l2 + _EPS:
        return "merge"
    if h1 <= h2 + _EPS and l1 >= l2 - _EPS:
        if equal_top == 1 and abs(h1 - h2) <= _EPS and l1 > l2 + _EPS:
            return "down"
        if equal_top == -1 and abs(l1 - l2) <= _EPS and h1 < h2 - _EPS:
            return "up"
        return "separate" if special else "merge"
    if h1 > h2 + _EPS and l1 > l2 + _EPS:
        return "down"
    if h1 < h2 - _EPS and l1 < l2 - _EPS:
        return "up"
    return "merge"


def _merge_element(element: _RefElement, stroke: Stroke, pos: int) -> None:
    element.positions.append(pos)
    if element.merge_up:
        element.high = max(element.high, stroke.high)
        element.low = max(element.low, stroke.low)
    else:
        element.high = min(element.high, stroke.high)
        element.low = min(element.low, stroke.low)


def _break_down(
    strokes: Sequence[Stroke], middle: _RefElement, right: _RefElement
) -> tuple[_RefBreakStatus, int]:
    pos = right.positions[-1]
    if right.low < strokes[middle.positions[-1]].low - _EPS:
        return _RefBreakStatus.CONFIRMED, pos
    later = pos + 2
    if later < len(strokes):
        if strokes[later].low < strokes[pos].low - _EPS:
            return _RefBreakStatus.CONFIRMED, later
        if later + 1 >= len(strokes):
            return _RefBreakStatus.PENDING, later
        return _RefBreakStatus.REJECTED, later
    opposite = pos + 1
    if opposite < len(strokes):
        if strokes[opposite].high > middle.high + _EPS:
            return _RefBreakStatus.REJECTED, opposite
        return _RefBreakStatus.PENDING, opposite
    return _RefBreakStatus.PENDING, pos


def _break_up(
    strokes: Sequence[Stroke], middle: _RefElement, right: _RefElement
) -> tuple[_RefBreakStatus, int]:
    pos = right.positions[-1]
    if right.high > strokes[middle.positions[-1]].high + _EPS:
        return _RefBreakStatus.CONFIRMED, pos
    later = pos + 2
    if later < len(strokes):
        if strokes[later].high > strokes[pos].high + _EPS:
            return _RefBreakStatus.CONFIRMED, later
        if later + 1 >= len(strokes):
            return _RefBreakStatus.PENDING, later
        return _RefBreakStatus.REJECTED, later
    opposite = pos + 1
    if opposite < len(strokes):
        if strokes[opposite].low < middle.low - _EPS:
            return _RefBreakStatus.REJECTED, opposite
        return _RefBreakStatus.PENDING, opposite
    return _RefBreakStatus.PENDING, pos



def _first_segment_extremes_valid(
    strokes: Sequence[Stroke], begin: int, end: int
) -> bool:
    if not _valid_boundary(strokes, begin, end):
        return False
    start_positions = range(begin, end + 1, 2)
    end_positions = range(begin + 1, end + 1, 2)
    start_values = [strokes[pos].fx_a.value for pos in start_positions]
    end_values = [strokes[pos].fx_a.value for pos in end_positions]
    if not start_values or not end_values:
        return False

    start_value = strokes[begin].fx_a.value
    end_value = strokes[end].fx_a.value
    if strokes[begin].direction is StrokeDirection.UP:
        return (
            start_value <= min(start_values) + _EPS
            and end_value >= max(end_values) - _EPS
        )
    return (
        start_value >= max(start_values) - _EPS
        and end_value <= min(end_values) + _EPS
    )


def _overlap_first_three(strokes: Sequence[Stroke], begin: int) -> bool:
    values = strokes[begin : begin + 3]
    return len(values) == 3 and max(x.low for x in values) <= min(x.high for x in values) + _EPS


def _valid_boundary(strokes: Sequence[Stroke], begin: int, end: int) -> bool:
    count = end - begin
    return count >= 3 and count % 2 == 1 and _overlap_first_three(strokes, begin)


def _point_key(value):
    return value.dt, value.mark, round(value.value, 12)
