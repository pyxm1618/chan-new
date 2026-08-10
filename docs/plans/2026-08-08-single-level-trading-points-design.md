# Single-Level Segment-Central-Zone Trading Points Design

## Goal

Make the first production trading-point mode strictly single-level: use only confirmed segments, confirmed segment central zones, same-level price structure, and same-level MACD evidence to emit B1/B2/B3 and S1/S2/S3. Do not use strokes inside a segment as a surrogate lower timeframe.

## Scope

This phase intentionally does **not** implement recursive multi-timeframe confirmation. A future phase may add a real lower-interval `AnalysisResult` (for example 1m evidence for a 5m operation level), but that evidence must be supplied explicitly and must never be synthesized from the current interval's internal strokes.

## Production semantics

### B1 / S1

A first buy/sell is evaluated from consecutive confirmed **segment central zones** at the current operation level.

For B1:

1. Two consecutive segment central zones form a strict downward trend (`last.trend_gg < previous.trend_dd`).
2. The connecting same-level segment `b` and final same-level departure segment `c` are both downward.
3. `c` creates a new same-level trend low relative to the compared path.
4. MACD state is exact (true history start or a valid persisted `MacdAnchor`).
5. The negative MACD histogram area of `c` is positive in magnitude and smaller than that of `b`.
6. The signal becomes available no earlier than the formal commit time of segment `c`.

S1 is the exact upward mirror.

No stroke-level central zone, stroke-level third point, or internal sublevel first point is required in this phase.

### B2 / S2

A second buy/sell is derived only from an already confirmed same-level B1/S1.

For B2:

1. After B1, the immediately following confirmed segment is an upward rebound.
2. The next confirmed segment is the **first** downward retracement.
3. The retracement endpoint does not break the B1 low (`retrace.end_value >= B1.price`, equality allowed).
4. The signal becomes available at the formal commit time of the retracement segment.

S2 is the exact downward/upward mirror.

No internal stroke-level B1/S1 is required.

### B3 / S3

Keep the existing same-level definition:

1. A confirmed segment leaves a fixed segment central zone boundary.
2. The immediately following first opposite confirmed segment is the first retest.
3. B3 requires the retest low to stay at or above `ZG`; S3 requires the retest high to stay at or below `ZD` (boundary touch allowed).
4. The signal becomes available at the formal commit time of the retest segment.

## Safety invariants

- Consume only confirmed segments and confirmed segment central zones.
- Require complete, identity-bound formal segment commit evidence; never fall back to structure endpoint time.
- Preserve exact MACD anchoring and K-line continuity validation.
- No signal may depend on future segments beyond the segment that formally confirms that signal.
- The detector must be insensitive to how many strokes happen to be stored inside a same-level segment.
- The engine default and package-level API must use the single-level detector.
- The previous recursive-like implementation may remain internal temporarily for regression/history, but must not be the production default.

## Architecture

Add a focused `single_level_trading_points.py` module that reuses the already hardened MACD, bar-stream, and segment-commit integrity helpers from `trading_points.py`, while owning the new B1/B2/B3 semantics. Route `engine.analyze_bars` and package-level `chan_monitor.detect_trading_points` / `validate_trading_points` to this module. Keep `build_macd_anchor` in the existing infrastructure module.

This split avoids a risky wholesale rewrite of the large legacy detector and provides a clean boundary for the later recursive implementation.

## Acceptance tests

1. A valid same-level B1 remains confirmed even if the departure segment contains only one stroke.
2. A valid same-level B2 remains confirmed even if the retracement segment contains only one stroke.
3. Removing/changing internal stroke detail without changing segment geometry cannot change single-level signals.
4. One segment central zone cannot produce B1/S1.
5. B2/S2 cannot exist without a prior formal B1/S1.
6. B2 rejects a first retracement that breaks the B1 extreme.
7. B3/S3 continue to accept an exact boundary touch.
8. Missing commit evidence fails closed.
9. Unanchored MACD history leaves B1/S1 pending rather than confirmed.
10. Batch and incremental engine results remain identical.