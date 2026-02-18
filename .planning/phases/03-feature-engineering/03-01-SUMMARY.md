---
phase: 03-feature-engineering
plan: 01
subsystem: features
tags: [scipy, statsmodels, rolling-ols, cross-correlation, bonferroni, sqlite, feature-engineering]

# Dependency graph
requires:
  - phase: 02-normalization-returns
    provides: returns_policy_a table with 1d/5d/10d/20d/60d returns per ticker

provides:
  - scipy>=1.13 and statsmodels>=0.14 runtime dependencies in pyproject.toml
  - 5 feature tables in SQLite via init_schema() (features_cross_correlation, features_relative_strength, features_volatility, features_zscore, features_lagged_returns)
  - features/db.py with 5 ON CONFLICT DO UPDATE upsert helpers
  - features/residualize.py with residualize_against_spy() using RollingOLS
  - features/cross_correlation.py with compute_rolling_xcorr_for_pair() and BONFERRONI_THRESHOLD=0.05/11
  - tests/test_features_xcorr.py with 10 tests covering all FEAT-01/02/03 behaviors

affects:
  - 03-feature-engineering (remaining plans for relative strength, volatility, z-score)
  - 04-leadlag-engine (reads features_cross_correlation to identify lead-lag pairs)
  - 05-signals (reads cross-correlation significance to generate trade signals)

# Tech tracking
tech-stack:
  added:
    - scipy==1.17.0 (pearsonr for per-lag p-values)
    - statsmodels==0.14.6 (RollingOLS for SPY residualization)
    - patsy==1.0.2 (statsmodels dependency)
  patterns:
    - RollingOLS residualization: use params to compute residuals manually (statsmodels 0.14 lacks .resid on RollingRegressionResults)
    - Manual rolling loop for two-series cross-correlation (pandas.rolling().apply() is 1D only)
    - Bonferroni correction: BONFERRONI_THRESHOLD = 0.05 / N_LAGS as module-level constant
    - Guard n < window before RollingOLS to prevent IndexError, return all-NaN series

key-files:
  created:
    - lead-lag-quant/features/__init__.py
    - lead-lag-quant/features/db.py
    - lead-lag-quant/features/residualize.py
    - lead-lag-quant/features/cross_correlation.py
    - lead-lag-quant/tests/test_features_xcorr.py
  modified:
    - lead-lag-quant/pyproject.toml
    - lead-lag-quant/utils/db.py
    - lead-lag-quant/uv.lock

key-decisions:
  - "statsmodels 0.14 RollingOLS: residuals computed manually as y - (alpha + beta*spy) because .resid attribute does not exist"
  - "BONFERRONI_THRESHOLD = 0.05/11 as module-level constant -- never test significance at raw 0.05 (42% false positive rate across 11 lag tests)"
  - "Manual rolling window loop for xcorr -- pandas.rolling().apply() cannot accept two series per window"
  - "Guard len(series) < window in residualize_against_spy to return all-NaN rather than crash with IndexError"
  - "RollingOLS min_nobs=window enforces full-window requirement -- partial windows produce NaN params not partial estimates"

patterns-established:
  - "Feature module pattern: features/residualize.py + features/cross_correlation.py + features/db.py as tripartite structure"
  - "Bonferroni threshold as BONFERRONI_THRESHOLD module constant, never magic number inline"
  - "Residualization before correlation: always remove SPY beta exposure before computing pair correlation"

# Metrics
duration: 6min
completed: 2026-02-18
---

# Phase 3 Plan 01: Feature Engineering - Cross-Correlation Foundation Summary

**Rolling SPY-residualized cross-correlation with Bonferroni significance (0.05/11) across lags -5 to +5, stored in SQLite via ON CONFLICT DO UPDATE upserts**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-18T21:22:41Z
- **Completed:** 2026-02-18T21:28:01Z
- **Tasks:** 2
- **Files modified:** 7 (2 modified, 5 created)

## Accomplishments

- Installed scipy 1.17.0 and statsmodels 0.14.6 via uv sync; both importable in venv
- Extended SQLite schema with 5 feature tables (cross_correlation, relative_strength, volatility, zscore, lagged_returns) and 3 indexes via init_schema()
- Implemented SPY beta residualization using RollingOLS with 60-day rolling window; first (window-1) rows return NaN per project convention
- Implemented rolling cross-correlation at lags -5 to +5 with manual window loop; Bonferroni threshold = 0.05/11 for significance flag
- 10 new tests cover Bonferroni constant, residualization length/NaN/alignment, lag arithmetic, DB storage with all 11 lags, significance flag correctness, insufficient history guard
- 60 total tests passing (50 existing + 10 new); no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add dependencies, extend SQLite schema, and implement features/db.py insert helpers** - `c2964aa` (feat)
2. **Task 2: Implement SPY residualization and rolling cross-correlation with Bonferroni tests** - `a325942` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `lead-lag-quant/pyproject.toml` - Added scipy>=1.13, statsmodels>=0.14, pandas>=2.1, numpy>=1.26
- `lead-lag-quant/uv.lock` - Updated with scipy, statsmodels, patsy
- `lead-lag-quant/utils/db.py` - Extended init_schema() with 5 feature tables and 3 indexes
- `lead-lag-quant/features/__init__.py` - Package marker
- `lead-lag-quant/features/db.py` - 5 ON CONFLICT DO UPDATE upsert helpers
- `lead-lag-quant/features/residualize.py` - residualize_against_spy() using RollingOLS
- `lead-lag-quant/features/cross_correlation.py` - compute_rolling_xcorr_for_pair(), BONFERRONI_THRESHOLD=0.05/11
- `lead-lag-quant/tests/test_features_xcorr.py` - 10 tests for FEAT-01/02/03

## Decisions Made

- statsmodels 0.14 RollingOLS does not expose `.resid`; residuals computed manually as `y - (alpha + beta*spy)` using the rolling params DataFrame
- BONFERRONI_THRESHOLD = 0.05/11 as module-level constant to prevent accidental raw 0.05 usage (11 lag tests per window = ~42% false positive rate without correction)
- Manual Python loop for cross-correlation slicing (pandas.rolling().apply() is 1D; cannot accept two series per window)
- Guard `len(series) < window` before RollingOLS to return all-NaN series instead of crashing with `IndexError: index out of bounds`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed RollingRegressionResults API: .resid attribute does not exist in statsmodels 0.14**
- **Found during:** Task 2 (residualize.py implementation, first test run)
- **Issue:** Plan specified `results.resid` but statsmodels 0.14.6 `RollingRegressionResults` has no `.resid` attribute; 4 tests failed with `AttributeError`
- **Fix:** Compute residuals manually from rolling params: `predicted = params[const_col] + params[spy_col] * spy_returns; residuals = ticker_returns - predicted`. Mathematically equivalent.
- **Files modified:** `lead-lag-quant/features/residualize.py`
- **Verification:** `test_residualize_returns_same_length` and `test_residualize_first_window_minus_one_are_nan` both pass
- **Committed in:** `a325942` (part of Task 2 commit)

**2. [Rule 1 - Bug] Added guard for series shorter than window in residualize_against_spy**
- **Found during:** Task 2 (test_xcorr_null_when_insufficient_history test)
- **Issue:** RollingOLS raises `IndexError: index N is out of bounds for axis 0 with size M` when data has fewer rows than window size; test with n=50 < window=60 crashed
- **Fix:** Added early-return guard at top of `residualize_against_spy`: if `len(ticker_returns) < window`, return all-NaN series immediately without calling RollingOLS
- **Files modified:** `lead-lag-quant/features/residualize.py`
- **Verification:** `test_xcorr_null_when_insufficient_history` passes; count=0 with insufficient data
- **Committed in:** `a325942` (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bugs in statsmodels API behavior vs plan specification)
**Impact on plan:** Both fixes necessary for correct behavior. No scope creep. Mathematically equivalent residualization.

## Issues Encountered

None beyond the two auto-fixed bugs above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Cross-correlation engine complete; features_cross_correlation table ready to receive data
- `compute_rolling_xcorr_for_pair(conn, ticker_a, ticker_b)` callable for any pair with sufficient returns history
- Remaining Phase 3 plans can implement relative strength, volatility, z-score, and lagged returns features using the established features/db.py upsert pattern

---
*Phase: 03-feature-engineering*
*Completed: 2026-02-18*

## Self-Check: PASSED

- All 8 key files verified to exist on disk
- Commit c2964aa (Task 1): FOUND in git log
- Commit a325942 (Task 2): FOUND in git log
- 60 tests passing (uv run pytest tests/ -q)
