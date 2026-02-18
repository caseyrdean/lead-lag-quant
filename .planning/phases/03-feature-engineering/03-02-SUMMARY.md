---
phase: 03-feature-engineering
plan: 02
subsystem: features
tags: [pandas, rolling, relative-strength, volatility, zscore, lagged-returns, pipeline, feature-engineering]

# Dependency graph
requires:
  - phase: 03-feature-engineering
    plan: 01
    provides: features/db.py upsert helpers, 5 feature tables, cross_correlation module

provides:
  - features/relative_strength.py with compute_relative_strength_for_pair() (FEAT-04)
  - features/volatility.py with compute_volatility_for_ticker() (FEAT-05)
  - features/zscore.py with compute_zscore_for_ticker() (FEAT-06)
  - features/lagged_returns.py with compute_lagged_returns_for_ticker() (FEAT-07)
  - features/pipeline.py with compute_features_for_pair(), compute_features_for_ticker(), compute_features_all_pairs()
  - features/__init__.py exporting public API
  - tests/test_features_simple.py (11 tests for FEAT-04 through FEAT-07)
  - tests/test_features_pipeline.py (3 integration tests)

affects:
  - 03-feature-engineering (plan 03, final plan of phase)
  - 04-leadlag-engine (reads all 5 feature tables to identify lead-lag pairs)
  - 05-signals (reads feature tables to generate trade signals)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rolling feature pattern: pd.read_sql_query -> rolling(window, min_periods=window) -> NaN to None -> upsert"
    - "Lagged returns: series.shift(lag) where positive lag=backward look (first N rows NaN), negative lag=forward look (last N rows NaN)"
    - "Pipeline orchestrator: compute_features_all_pairs reads ticker_pairs, calls pair-level and per-ticker functions"

key-files:
  created:
    - lead-lag-quant/features/relative_strength.py
    - lead-lag-quant/features/volatility.py
    - lead-lag-quant/features/zscore.py
    - lead-lag-quant/features/lagged_returns.py
    - lead-lag-quant/features/pipeline.py
    - lead-lag-quant/tests/test_features_simple.py
    - lead-lag-quant/tests/test_features_pipeline.py
  modified:
    - lead-lag-quant/features/__init__.py

key-decisions:
  - "Lagged returns use series.shift(lag): positive lag is backward-looking (first N NaN), negative lag is forward-looking (last N NaN) -- plan docstring had inverted description but test expectations were correct"
  - "pipeline.py separates pair-level features (xcorr, RS) from per-ticker features (volatility, zscore, lagged_returns) into distinct functions for clean orchestration"
  - "compute_features_all_pairs always includes SPY in per-ticker feature computation regardless of active pairs"

# Metrics
duration: 8min
completed: 2026-02-18
---

# Phase 3 Plan 02: Feature Engineering - Remaining Features and Pipeline Summary

**Rolling pandas features (RS 10d, volatility 20d, zscore 20d, lagged returns +/-5) plus pipeline orchestrator completing all 7 Phase 3 features**

## Performance

- **Duration:** 8 min
- **Completed:** 2026-02-18
- **Tasks:** 2
- **Files modified:** 8 (1 modified, 7 created)

## Accomplishments

- Implemented 4 remaining feature modules following the NULL-not-zero convention with min_periods=window enforcement
- RS (FEAT-04): rolling 10-day cumulative return differential, NULL for first 9 rows per pair
- Volatility (FEAT-05): rolling 20-day std of returns, NULL for first 19 rows per ticker
- Z-score (FEAT-06): rolling 20-day standardized returns, NULL for insufficient history or flat periods
- Lagged returns (FEAT-07): 10 offsets (+/-1 to +/-5 excluding 0), NULL at leading/trailing edges
- Pipeline orchestrator compute_features_all_pairs() reads all active pairs and computes all 7 features in one call
- Updated features/__init__.py to export the public API
- 14 new tests (11 unit + 3 integration); full suite now at 74 tests with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement RS, volatility, z-score, lagged returns modules with tests** - `bfc72d4` (feat)
2. **Task 2: Implement pipeline.py orchestrator, update features/__init__.py, and integration test** - `e776461` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `lead-lag-quant/features/relative_strength.py` - compute_relative_strength_for_pair(), 10d rolling RS
- `lead-lag-quant/features/volatility.py` - compute_volatility_for_ticker(), 20d rolling std
- `lead-lag-quant/features/zscore.py` - compute_zscore_for_ticker(), 20d rolling z-score
- `lead-lag-quant/features/lagged_returns.py` - compute_lagged_returns_for_ticker(), 10 offsets
- `lead-lag-quant/features/pipeline.py` - pipeline orchestrator for all 7 features
- `lead-lag-quant/features/__init__.py` - updated to export public API from pipeline
- `lead-lag-quant/tests/test_features_simple.py` - 11 tests for FEAT-04 through FEAT-07
- `lead-lag-quant/tests/test_features_pipeline.py` - 3 integration tests for pipeline orchestrator

## Decisions Made

- Lagged returns use `series.shift(lag)` not `series.shift(-lag)`: positive lag is backward-looking (first N rows NaN), negative lag is forward-looking (last N rows NaN). The plan docstring had the description inverted but the test expectations were authoritative.
- Pipeline separates pair-level features (xcorr, RS) from per-ticker features (volatility, zscore, lagged_returns) into distinct functions for clean orchestration and independent reuse.
- compute_features_all_pairs always includes SPY in per-ticker computation (hardcoded into tickers set) to ensure SPY features are always available for residualization validation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed lagged_returns shift direction: series.shift(-lag) should be series.shift(lag)**
- **Found during:** Task 1 (test_lagged_returns_edges_are_null failure on first test run)
- **Issue:** Plan specified `series.shift(-lag)` in implementation but the test expects lag=-5 to produce NULL at the LAST 5 rows (forward-looking, past end of series). With `shift(-lag)` = `shift(5)`, the first 5 rows become NaN instead of the last 5.
- **Fix:** Changed to `series.shift(lag)`. For lag=-5: `shift(-5)` in pandas shifts up by 5, making last 5 rows NaN. For lag=+5: `shift(5)` shifts down by 5, making first 5 rows NaN. Updated docstring to match corrected semantics.
- **Files modified:** `lead-lag-quant/features/lagged_returns.py`
- **Verification:** `test_lagged_returns_edges_are_null` passes; all 11 tests pass
- **Committed in:** `bfc72d4` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - implementation bug where plan docstring and code had inverted shift direction vs test expectations)
**Impact on plan:** Fix required for correct behavior. Mathematically: shift(lag) is the standard pandas convention where positive shift = look back.

## Issues Encountered

None beyond the one auto-fixed bug above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 7 Phase 3 features complete: xcorr (FEAT-01/02/03), RS (FEAT-04), volatility (FEAT-05), zscore (FEAT-06), lagged_returns (FEAT-07)
- `compute_features_all_pairs(conn)` provides single-call orchestration for Phase 4 and UI integration
- All 5 feature tables populated with correct NULL semantics for insufficient history
- 74 tests passing; feature engineering foundation stable for Phase 4 (lead-lag engine)

---
*Phase: 03-feature-engineering*
*Completed: 2026-02-18*

## Self-Check: PASSED

- All 8 key files verified to exist on disk (7 created + 1 modified)
- Commit bfc72d4 (Task 1): FOUND in git log
- Commit e776461 (Task 2): FOUND in git log
- 74 tests passing (uv run pytest tests/ -v); 14 new tests, 0 regressions
