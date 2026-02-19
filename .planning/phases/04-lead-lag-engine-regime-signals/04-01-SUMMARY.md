---
phase: 04-lead-lag-engine-regime-signals
plan: "01"
subsystem: database
tags: [sqlite, pandas, scipy, signal-detection, stability-scoring]

# Dependency graph
requires:
  - phase: 03-feature-engineering
    provides: features_cross_correlation table (ticker_a, ticker_b, trading_day, lag, correlation, is_significant)

provides:
  - leadlag_engine package with __init__.py, db.py, detector.py, stability.py
  - ENGINE-01: detect_optimal_lag() returning optimal_lag + signed correlation_strength or None
  - ENGINE-02: five RSI-v2 sub-score functions + compute_stability_score() with defined weights
  - Four Phase 4 SQLite tables: regime_states, distribution_events, signals, flow_map
  - upsert_signal() with immutable generated_at anchor; upsert_flow_map()

affects:
  - 04-02 (regime classification uses regime_states table; pipeline calls compute_stability_score)
  - 04-03 (gate logic reads stability_score and correlation_strength from detector + stability)
  - 04-04 (signal generation writes to signals table via upsert_signal)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - MAX(trading_day) anchoring for all DB reads (never datetime('now') to avoid weekend instability)
    - NULL-not-zero convention: insufficient history returns None/0.0, not fabricated zero
    - Immutable audit anchor: ON CONFLICT SET excludes generated_at so creation timestamp is never overwritten
    - Five-component weighted stability score with WEIGHTS constant summing to 1.0

key-files:
  created:
    - lead-lag-quant/leadlag_engine/__init__.py
    - lead-lag-quant/leadlag_engine/db.py
    - lead-lag-quant/leadlag_engine/detector.py
    - lead-lag-quant/leadlag_engine/stability.py
    - lead-lag-quant/tests/test_engine_detector.py
    - lead-lag-quant/tests/test_engine_stability.py
  modified:
    - lead-lag-quant/utils/db.py

key-decisions:
  - "RSI-v2 weights: lag_persistence=0.30, walk_forward_oos=0.25, rolling_confirmation=0.20, regime_stability=0.15, lag_drift=0.10 (resolves STATE.md blocker)"
  - "MIN_SIGNIFICANT_DAYS=30: minimum is_significant=1 observations per lag to qualify for optimal lag selection"
  - "detect_optimal_lag uses abs(median_corr) for lag selection but returns signed correlation_strength for direction preservation"
  - "init_engine_schema called from init_schema() so tmp_db fixture creates all Phase 4 tables automatically without fixture changes"
  - "walk_forward_oos_score returns 0.0 if fewer than 15 validation rows (sparse data guard)"

patterns-established:
  - "Anchor pattern: all DB queries anchor to MAX(trading_day) for the pair, not datetime('now')"
  - "Empty-returns-zero pattern: all sub-score functions return 0.0 on empty input, never raise"
  - "Eligible-lag filter: lag must have >= 30 significant observations before being considered optimal"

# Metrics
duration: 18min
completed: 2026-02-18
---

# Phase 4 Plan 01: Lead-Lag Engine Foundation Summary

**leadlag_engine package with ENGINE-01 optimal lag detector (median-corr aggregation over features_cross_correlation), ENGINE-02 five-component RSI-v2 stability scorer (WEIGHTS: 0.30/0.25/0.20/0.15/0.10), four Phase 4 SQLite tables, and 31 tests covering all behaviors**

## Performance

- **Duration:** 18 min
- **Started:** 2026-02-18T19:30:00Z
- **Completed:** 2026-02-18T19:48:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Created `leadlag_engine/` package with four modules (\_\_init\_\_, db, detector, stability) that form the numeric backbone for all Phase 4 signal generation
- ENGINE-01: `detect_optimal_lag()` reads `features_cross_correlation`, filters to is_significant=1 and non-NULL, requires 30+ days per lag, returns lag with highest |median correlation| plus signed correlation_strength (or None)
- ENGINE-02: five RSI-v2 sub-score functions (lag_persistence, walk_forward_oos, rolling_confirmation, regime_stability, lag_drift) plus `compute_stability_score()` with defined WEIGHTS constant resolving the STATE.md blocker on undefined weights
- Four Phase 4 SQLite tables added via `init_engine_schema()` automatically called from `init_schema()`: regime_states, distribution_events, signals (with immutable generated_at), flow_map
- 31 new tests, 105 total passing (zero regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create leadlag_engine package, Phase 4 schema, upsert helpers** - `ad8ee96` (feat)
2. **Task 2: ENGINE-01 detector, ENGINE-02 stability scorer, tests** - `1abf022` (feat)

**Plan metadata:** (docs commit after SUMMARY and STATE update)

## Files Created/Modified

- `lead-lag-quant/leadlag_engine/__init__.py` - Package marker for Phase 4 engine
- `lead-lag-quant/leadlag_engine/db.py` - `init_engine_schema()` creating 4 tables; `upsert_signal()` (immutable generated_at); `upsert_flow_map()`
- `lead-lag-quant/leadlag_engine/detector.py` - `detect_optimal_lag()` with MAX(trading_day) anchoring, 30-day minimum filter, signed correlation_strength
- `lead-lag-quant/leadlag_engine/stability.py` - Five RSI-v2 sub-score functions + `compute_stability_score()` with WEIGHTS constant
- `lead-lag-quant/tests/test_engine_detector.py` - 7 tests: empty DB, insufficient days, lag selection by count, negative correlation, NULL filtering, anchor stability, multi-lag selection
- `lead-lag-quant/tests/test_engine_stability.py` - 24 tests: weights validation, composite scoring, all five sub-score functions with empty and populated inputs
- `lead-lag-quant/utils/db.py` - Added `from leadlag_engine.db import init_engine_schema` and call at end of `init_schema()`

## Decisions Made

- **RSI-v2 component weights defined:** lag_persistence=0.30, walk_forward_oos=0.25, rolling_confirmation=0.20, regime_stability=0.15, lag_drift=0.10. Resolves the "stability_score weights not yet defined" blocker from STATE.md. Weights chosen to prioritize persistence (most predictive of future relationship stability) over regime context (least controllable).
- **MIN_SIGNIFICANT_DAYS=30:** Requires 30 is_significant=1 observations per lag before qualifying it. Prevents spurious lag selection on pairs with thin statistical history.
- **Signed correlation_strength:** detect_optimal_lag selects lag by abs(median_corr) but returns the signed value so downstream signal generation can distinguish positive/negative lead relationships.
- **init_engine_schema called inside init_schema():** Avoids needing to update the conftest.py fixture -- all tests that use tmp_db automatically get Phase 4 tables.
- **walk_forward_oos_score minimum 15 rows:** Sparse-data guard prevents misleading OOS scores from only 1-2 data points inflating to 100.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ENGINE-01 and ENGINE-02 complete; Phase 4 schema in place
- Phase 4 Plan 02 can implement regime classifier (ENGINE-03) using the regime_states table and stability_score produced by compute_stability_score()
- Blocker resolved: RSI-v2 weights are now defined constants in stability.py

## Self-Check: PASSED

Files verified: all 7 files found on disk.
Commits verified: ad8ee96, 1abf022 confirmed in git log.
Test suite: 105 passed, 0 failures.

---
*Phase: 04-lead-lag-engine-regime-signals*
*Completed: 2026-02-18*
