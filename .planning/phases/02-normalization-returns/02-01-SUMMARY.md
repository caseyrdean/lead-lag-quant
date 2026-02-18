---
phase: 02-normalization-returns
plan: 01
subsystem: database
tags: [sqlite, exchange-calendars, pandas, normalization, splits, dividends, policy-a]

# Dependency graph
requires:
  - phase: 01-data-ingestion-pipeline/01-01
    provides: SQLite schema (raw_api_responses, ticker_pairs), db.py connection helpers
  - phase: 01-data-ingestion-pipeline/01-02
    provides: ingest_pair storing aggs/splits/dividends JSON in raw_api_responses
provides:
  - normalization/ module (5 source files) with Policy A split-adjusted price pipeline
  - Extended utils/db.py schema with splits, normalized_bars, returns_policy_a, dividends tables
  - normalize_ticker() orchestrator reading raw_api_responses and writing normalized_bars
  - store_dividends_for_ticker() writing dividends separately (never applied to prices)
  - unix_ms_to_trading_day() converting Polygon Unix-ms timestamps to NYSE session strings
  - 26 unit tests covering all normalization components
affects: [03-features, 04-leadlag-engine, 05-signals, 06-paper-trading]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Policy A: split-adjusted prices via multiply (adj_price = raw * factor), dividends stored separately and never applied
    - exchange_calendars XNYS module-level singleton for expensive calendar object reuse
    - Polygon historical_adjustment_factor: next split after bar_date provides cumulative backward factor; 1.0 if no splits after bar
    - adjustment_policy_id column on normalized_bars enables future multi-policy support without schema changes
    - fetched_at copied from raw_api_responses.retrieved_at for point-in-time backtest isolation

key-files:
  created:
    - lead-lag-quant/normalization/__init__.py
    - lead-lag-quant/normalization/timestamp_utils.py
    - lead-lag-quant/normalization/split_adjuster.py
    - lead-lag-quant/normalization/bar_normalizer.py
    - lead-lag-quant/normalization/dividend_storer.py
    - lead-lag-quant/normalization/normalizer.py
    - lead-lag-quant/tests/test_normalization.py
  modified:
    - lead-lag-quant/utils/db.py

key-decisions:
  - "Policy A is split-only: adj_price = raw_price * historical_adjustment_factor; dividends stored in dividends table and never applied to prices (NORM-02)"
  - "Polygon historical_adjustment_factor strategy: next split after bar_date provides the cumulative backward factor; returns 1.0 when no splits exist after bar_date"
  - "XNYS calendar instantiated once as module-level singleton in timestamp_utils.py to avoid repeated expensive creation"
  - "fetched_at on splits rows copied from raw_api_responses.retrieved_at to enable point-in-time backtest isolation (NORM-05)"
  - "adjustment_policy_id column defaults to 'policy_a' on normalized_bars for future multi-policy extensibility"

patterns-established:
  - "Normalization reads raw_api_responses exclusively -- normalization module never calls Polygon API directly"
  - "All normalized_bars timestamps stored as YYYY-MM-DD NYSE trading day strings (never Unix milliseconds)"
  - "Volume adjustment is inverse to price: adj_volume = raw_volume / factor"

# Metrics
duration: 25min
completed: 2026-02-18
---

# Phase 2 Plan 01: Normalization Module Summary

**SQLite schema extended with 4 tables (splits, normalized_bars, returns_policy_a, dividends) and Policy A normalization pipeline implemented: split-adjusted OHLCV bars via Polygon historical_adjustment_factor, dividends stored separately and never touching prices**

## Performance

- **Duration:** 25 min
- **Started:** 2026-02-18T13:20:00Z
- **Completed:** 2026-02-18T13:45:00Z
- **Tasks:** 2 (both auto)
- **Files modified:** 8 (7 created, 1 extended)

## Accomplishments

- Extended `utils/db.py` `init_schema()` with 4 new tables (splits, normalized_bars, returns_policy_a, dividends) and 3 composite indexes, all idempotent via `CREATE TABLE IF NOT EXISTS`
- Implemented the full normalization/ module: timestamp_utils, split_adjuster, bar_normalizer, dividend_storer, normalizer orchestrator (5 source files, 1 package marker)
- Wrote 26 unit tests covering every component; all 45 tests in the suite (26 new + 19 existing) pass with zero failures

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend SQLite schema and implement normalization module** - `a245e3e` (feat)
2. **Task 2: Normalizer orchestrator and unit tests** - `63ebb09` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `lead-lag-quant/utils/db.py` - Extended init_schema() with splits, normalized_bars, returns_policy_a, dividends tables and 3 indexes
- `lead-lag-quant/normalization/__init__.py` - Package marker
- `lead-lag-quant/normalization/timestamp_utils.py` - unix_ms_to_trading_day() via XNYS module-level singleton
- `lead-lag-quant/normalization/split_adjuster.py` - extract_splits_to_table(), get_adjustment_factor_for_bar()
- `lead-lag-quant/normalization/bar_normalizer.py` - normalize_bars_for_ticker() with Policy A split adjustment
- `lead-lag-quant/normalization/dividend_storer.py` - store_dividends_for_ticker() (dividends never touch prices)
- `lead-lag-quant/normalization/normalizer.py` - normalize_ticker() and normalize_all_pairs() orchestrators
- `lead-lag-quant/tests/test_normalization.py` - 26 unit tests covering all normalization components

## Decisions Made

- Policy A is split-only: `adj_price = raw_price * historical_adjustment_factor`. Dividends are stored in the dividends table and never applied to price calculations (NORM-02). This keeps price series purely split-adjusted, dividends available as separate reference data.
- Polygon's `historical_adjustment_factor` is used as-is for the cumulative backward factor. The strategy: find the first split executed after bar_date and use its factor. If no split exists after bar_date, factor = 1.0. This correctly handles the most recent bars (no future splits yet) returning unadjusted prices.
- XNYS calendar created once at module import time as `_nyse_calendar` singleton in timestamp_utils.py. The `exchange_calendars.get_calendar()` call is expensive; calling it per-bar would be prohibitively slow.
- `fetched_at` on splits rows is copied from `raw_api_responses.retrieved_at` rather than `datetime('now')` to preserve point-in-time information enabling future backtest isolation (NORM-05).
- `adjustment_policy_id` column defaults to `'policy_a'` in the schema and is hardcoded in the INSERT statement, enabling future multi-policy support (e.g., policy_b with dividend adjustment) without schema changes.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 2 Plan 01 complete. normalized_bars table populated with Policy A split-adjusted OHLCV bars, dividends table populated with raw dividend records.
- Phase 2 Plan 02 (returns computation) can proceed: log return computation over normalized_bars into returns_policy_a table. The schema is already in place.
- No blockers for Phase 2 Plan 02.

## Self-Check: PASSED

- FOUND: lead-lag-quant/normalization/__init__.py
- FOUND: lead-lag-quant/normalization/timestamp_utils.py
- FOUND: lead-lag-quant/normalization/split_adjuster.py
- FOUND: lead-lag-quant/normalization/bar_normalizer.py
- FOUND: lead-lag-quant/normalization/dividend_storer.py
- FOUND: lead-lag-quant/normalization/normalizer.py
- FOUND: lead-lag-quant/tests/test_normalization.py
- FOUND: .planning/phases/02-normalization-returns/02-01-SUMMARY.md
- FOUND commit a245e3e: feat(02-01): extend schema with 4 normalization tables
- FOUND commit 63ebb09: feat(02-01): add normalizer orchestrator and normalization unit tests

---
*Phase: 02-normalization-returns*
*Completed: 2026-02-18*
