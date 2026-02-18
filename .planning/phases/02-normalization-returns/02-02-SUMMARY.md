---
phase: 02-normalization-returns
plan: 02
subsystem: database
tags: [sqlite, pandas, normalization, returns, policy-a, gradio]

# Dependency graph
requires:
  - phase: 02-normalization-returns/02-01
    provides: normalized_bars table (adj_close per ticker), returns_policy_a schema, normalize_all_pairs() orchestrator
provides:
  - normalization/returns_calc.py with compute_returns_for_ticker and compute_returns_all_pairs
  - returns_policy_a table populated with 1d/5d/10d/20d/60d pct_change returns, all tagged adjustment_policy_id='policy_a'
  - Gradio 'Normalize' tab wiring normalize_all_pairs + compute_returns_all_pairs behind a single button
  - 5 unit tests covering rolling returns, NaN boundary, cross-ticker isolation, policy tag, idempotency, empty ticker
affects: [03-features, 04-leadlag-engine, 05-signals, 06-paper-trading]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Process ONE ticker at a time in returns computation -- never load multi-ticker DataFrame and call pct_change (positional bleed)
    - pct_change(periods=N, fill_method=None) -- fill_method kwarg required for pandas >= 2.1 deprecation compliance
    - NaN returns stored as NULL in SQLite via None sentinel before executemany
    - Upsert via ON CONFLICT(ticker, trading_day) DO UPDATE makes returns computation idempotent

key-files:
  created:
    - lead-lag-quant/normalization/returns_calc.py
    - lead-lag-quant/tests/test_returns_calc.py
  modified:
    - lead-lag-quant/ui/app.py

key-decisions:
  - "Returns computed strictly per-ticker: single-ticker DataFrame fed to pct_change to prevent cross-ticker boundary bleed (NORM-04)"
  - "fill_method=None passed to pct_change to satisfy pandas >= 2.1 deprecation; positional return computation is correct behavior"
  - "First N rows per period carry NULL return (insufficient history) -- stored as NULL in SQLite, not zero"
  - "Normalize tab placed as third tab after Data Ingestion; run_normalization() runs normalize_all_pairs then compute_returns_all_pairs sequentially"

patterns-established:
  - "Returns pipeline is a second-stage consumer of normalized_bars -- never reads raw_api_responses directly"
  - "SPY always included in compute_returns_all_pairs via set deduplication (mirrors normalize_all_pairs pattern)"
  - "Gradio tab callbacks use gr.Progress(track_tqdm=False) default -- app.queue() already present from Plan 01-03"

# Metrics
duration: 15min
completed: 2026-02-18
---

# Phase 2 Plan 02: Returns Computation and Normalize UI Summary

**Multi-period rolling returns (1d/5d/10d/20d/60d) computed per-ticker from adj_close into returns_policy_a, with a Gradio Normalize tab wiring the full normalization + returns pipeline behind a single button**

## Performance

- **Duration:** 15 min
- **Started:** 2026-02-18T13:45:00Z
- **Completed:** 2026-02-18T14:00:00Z
- **Tasks:** 2 (both auto)
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments

- Implemented `normalization/returns_calc.py` with `compute_returns_for_ticker` (per-ticker pct_change upsert) and `compute_returns_all_pairs` (all active pair tickers + SPY)
- Added 5 unit tests covering basic computation, cross-ticker isolation, policy tag, idempotency, and empty ticker -- all 50 tests in suite pass
- Extended Gradio UI with a "Normalize" third tab: "Normalize All Pairs" button triggers normalize_all_pairs + compute_returns_all_pairs and displays a per-ticker log

## Task Commits

Each task was committed atomically:

1. **Task 1: Returns computation module (returns_calc.py) and tests** - `de1d321` (feat)
2. **Task 2: Add Normalize tab to Gradio UI** - `e718f59` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `lead-lag-quant/normalization/returns_calc.py` - compute_returns_for_ticker and compute_returns_all_pairs; per-ticker pct_change with NULL boundary handling; ON CONFLICT upsert
- `lead-lag-quant/tests/test_returns_calc.py` - 5 tests: basic computation (65 rows, NaN check, 60d check), cross-ticker isolation, policy tag, idempotency, empty ticker
- `lead-lag-quant/ui/app.py` - Added normalize imports, run_normalization() callback, Normalize tab with button + log textbox

## Decisions Made

- Returns computed strictly per-ticker: a single-ticker DataFrame is loaded from normalized_bars and pct_change is called on it. Mixing tickers into one DataFrame would cause pct_change to compute returns across ticker boundaries at the junction row, producing incorrect values. Processing one ticker at a time eliminates this risk entirely.
- `fill_method=None` passed explicitly to `pct_change()` to comply with the pandas >= 2.1 deprecation of the fill_method parameter's default. This is the correct behavior anyway -- we do not want forward-fill of missing adj_close values before computing returns.
- NULL (not zero) stored for the first N rows per period (insufficient prior history). A return of zero would be incorrect; NULL correctly communicates that no return can be computed for that row.
- The Normalize tab placed third (after Pair Management and Data Ingestion) to reflect the natural workflow order: add pairs, fetch data, then normalize.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 2 complete. Both normalized_bars (Policy A split-adjusted OHLCV) and returns_policy_a (5-period rolling returns) are populated and policy-tagged.
- Phase 3 (feature engineering) can consume adj_close from normalized_bars and rolling returns from returns_policy_a directly via SQLite queries.
- No blockers for Phase 3.

## Self-Check: PASSED

- FOUND: lead-lag-quant/normalization/returns_calc.py
- FOUND: lead-lag-quant/tests/test_returns_calc.py
- FOUND: lead-lag-quant/ui/app.py (modified)
- FOUND commit de1d321: feat(02-02): implement returns_calc module and tests
- FOUND commit e718f59: feat(02-02): add Normalize tab to Gradio UI

---
*Phase: 02-normalization-returns*
*Completed: 2026-02-18*
