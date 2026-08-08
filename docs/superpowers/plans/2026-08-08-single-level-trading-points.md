# Single-Level Trading Points Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production detector emit B1/B2/B3 and S1/S2/S3 from confirmed same-level segments and segment central zones, with no internal stroke/sublevel requirement.

**Architecture:** Add a dedicated `single_level_trading_points.py` production detector that reuses the hardened bar/MACD/commit-evidence primitives from the legacy detector. Route `engine.py` and package-level exports to the new module. Keep the legacy recursive-like detector available internally until the later real multi-timeframe phase.

**Tech Stack:** Python >=3.10, dataclasses, pytest, GitHub Actions Python 3.10–3.13 matrix.

## Global Constraints

- Production B1/B2/B3/S1/S2/S3 use only confirmed same-level segments and confirmed segment central zones.
- No internal stroke-level central zone, third point, or B1/S1 may be required for a formal single-level point.
- Preserve fail-closed formal `SegmentEvidence` / fingerprint commit-time validation.
- Preserve exact MACD history/anchor and bar-continuity validation.
- Preserve `confirmed_at_dt` as the real formal availability time, never the geometric endpoint time.
- Keep B3/S3 boundary-touch behavior.
- Do not implement real recursive lower-timeframe confirmation in this phase.

---

### Task 1: Lock the single-level contract with failing tests

**Files:**
- Create: `tests/test_single_level_trading_points.py`

**Interfaces:**
- Consumes: `chan_monitor.single_level_trading_points.detect_trading_points` (initially missing).
- Produces: executable behavioral specification for B1/B2/B3/S1/S2/S3.

- [ ] **Step 1: Write deterministic segment helpers and failing tests**

Create real `Segment`, `Stroke`, `RawBar`, and `SegmentCentralZone` fixtures. Include tests proving:

```python
assert BUY1 is emitted when same-level trend + new low + exact MACD divergence hold
assert BUY1 is unchanged when the departure segment has only one internal stroke
assert BUY2 is emitted from the immediate rebound/retrace sequence without any stroke-level B1
assert BUY2 is rejected when the retracement breaks B1.price
assert BUY3 accepts an exact ZG boundary touch
assert missing formal commit evidence emits no formal points
```

Mirror the critical B1/B2 cases for S1/S2.

- [ ] **Step 2: Run the new test file and verify RED**

Run through GitHub Actions after committing only the tests. Expected failure: import/module-not-found or missing single-level detector behavior. A passing suite at this point means the test is not exercising the new production contract and must be corrected.

- [ ] **Step 3: Commit the red tests**

Commit message:

```text
test: specify single-level trading point semantics
```

---

### Task 2: Implement the single-level detector

**Files:**
- Create: `src/chan_monitor/single_level_trading_points.py`
- Test: `tests/test_single_level_trading_points.py`

**Interfaces:**
- Consumes hardened helpers from `chan_monitor.trading_points`: `TradingPointDetectionResult`, `_formal_segment_commit_times`, `_macd_histogram`, `_directional_macd_area`, `_raw_bars_from_segments`, `_segment_confirmation_dt`.
- Produces:

```python
def detect_trading_points(
    segments: Sequence[Segment],
    segment_central_zones: Sequence[SegmentCentralZone],
    *,
    raw_bars: Sequence[RawBar] = (),
    segment_evidence: Sequence[SegmentEvidence] = (),
    segment_commit_times: Mapping[str, datetime] | None = None,
    strokes: Sequence[Stroke] = (),
    macd_history_anchored: bool = False,
    macd_anchor: MacdAnchor | None = None,
) -> TradingPointDetectionResult
```

and a matching `validate_trading_points(...)`.

- [ ] **Step 1: Implement same-level B1/S1**

For adjacent segment-central-zone views:

```python
strict_down = last.trend_gg < previous.trend_dd - EPS
strict_up = last.trend_dd > previous.trend_gg + EPS
```

Find same-level `b` and `c`, require a new directional price extreme, exact MACD state, and smaller same-direction MACD histogram area on `c` than `b`. Do **not** inspect `segment.strokes` for sublevel structure.

Use evidence kind:

```text
SINGLE_LEVEL_TREND_MACD_DIVERGENCE
```

- [ ] **Step 2: Implement same-level B2/S2**

Starting from each confirmed B1/S1, inspect only the next two confirmed segments. For B2 require `UP` rebound, then `DOWN` first retracement, and `retrace.end_value >= b1.price`. Mirror for S2. Do not call any stroke-level detector.

Use evidence kind:

```text
SINGLE_LEVEL_FIRST_RETRACE
```

- [ ] **Step 3: Implement same-level B3/S3**

Use the existing fixed segment-central-zone rule: first confirmed departure, immediately followed by first opposite confirmed retest. B3 requires `pullback.low >= zone.zg - EPS`; S3 requires `pullback.high <= zone.zd + EPS`.

Use evidence kind:

```text
SINGLE_LEVEL_ZONE_DEPARTURE_RETEST
```

- [ ] **Step 4: Implement fail-closed diagnostics and deterministic ordering**

Missing segment commit evidence returns zero formal points with `FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING`. Invalid MACD stream/anchor propagates hardened validation behavior. Sort/deduplicate by `(point_type, dt, segment_index)`.

- [ ] **Step 5: Implement validator by formal recalculation**

Recalculate expected points with the same production inputs and flag:

```text
TRADING_POINT_DUPLICATE
TRADING_POINT_SEGMENT_MISSING
TRADING_POINT_ENDPOINT_MISMATCH
TRADING_POINT_DIRECTION_INVALID
TRADING_POINT_FUTURE_TIME_INVALID
TRADING_POINT_NOT_IN_FORMAL_RECALCULATION
TRADING_POINT_CONFIRM_TIME_MISMATCH
TRADING_POINT_EVIDENCE_MISMATCH
```

- [ ] **Step 6: Run new tests and verify GREEN**

Expected: all `tests/test_single_level_trading_points.py` tests pass.

- [ ] **Step 7: Commit implementation**

Commit message:

```text
feat: add single-level segment-zone trading points
```

---

### Task 3: Route production to the single-level detector

**Files:**
- Modify: `src/chan_monitor/engine.py`
- Modify: `src/chan_monitor/__init__.py`
- Test: `tests/test_single_level_trading_points.py`

**Interfaces:**
- `engine.analyze_bars` must call `single_level_trading_points.detect_trading_points`.
- `chan_monitor.detect_trading_points` and `chan_monitor.validate_trading_points` must expose the single-level API.
- `chan_monitor.build_macd_anchor` remains sourced from the hardened legacy infrastructure module.

- [ ] **Step 1: Add an engine-routing test**

Assert that a deterministic batch analysis uses the single-level evidence kinds and that changing internal stroke decomposition without changing formal segment geometry does not alter same-level point identities.

- [ ] **Step 2: Run and verify RED before routing changes**

Expected: engine still uses the legacy detector and therefore fails the single-level-only assertion.

- [ ] **Step 3: Change imports only**

In `engine.py`:

```python
from .trading_points import build_macd_anchor
from .single_level_trading_points import detect_trading_points
```

In `__init__.py`:

```python
from .trading_points import build_macd_anchor
from .single_level_trading_points import detect_trading_points, validate_trading_points
```

- [ ] **Step 4: Run focused tests and full suite**

Focused expected: green. Full suite expected: no regression. Any legacy test that intentionally asserts sublevel requirements must remain scoped to the legacy module rather than production engine behavior.

- [ ] **Step 5: Commit routing**

Commit message:

```text
feat: make single-level trading points the production default
```

---

### Task 4: Document and release the behavior change

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Package version becomes `0.11.0` because formal trading-point semantics intentionally change.

- [ ] **Step 1: Document the level boundary**

README must state:

```text
Current production trading points are single-level segment-zone signals.
They do not use strokes inside a segment as a substitute for a lower timeframe.
Real recursive lower-timeframe confirmation is a future phase.
```

- [ ] **Step 2: Add changelog entry**

Record that B1/S1 no longer require internal stroke-level third-point/two-zone evidence and B2/S2 no longer require an internal stroke-level B1/S1; formal segment commit/MACD integrity remains unchanged.

- [ ] **Step 3: Bump version to 0.11.0**

Change only the `[project].version` value.

- [ ] **Step 4: Commit docs/version**

Commit message:

```text
release: document single-level trading points v0.11.0
```

---

### Task 5: Final verification and PR

**Files:**
- No new production files beyond Tasks 1–4.

**Interfaces:**
- GitHub Actions matrix is the release gate.

- [ ] **Step 1: Run the full GitHub Actions test matrix**

Require Python 3.10, 3.11, 3.12, and 3.13 to complete successfully.

- [ ] **Step 2: Inspect the PR diff**

Confirm the production behavior change is limited to the new single-level detector, routing, tests, and documentation/version metadata. No segment, central-zone, bar-stream, or MACD-anchor algorithm should change.

- [ ] **Step 3: Open PR against `main`**

Title:

```text
Add single-level segment-zone trading points v0.11.0
```

PR body must state the old recursive-like internal-stroke requirements removed from production, the exact B1/B2/B3 semantics, TDD red/green evidence, and final CI result.

- [ ] **Step 4: Mark ready only after final CI is green**

Do not claim completion before the final head commit passes the full matrix.