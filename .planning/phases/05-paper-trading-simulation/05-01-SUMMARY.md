---
phase: 05-paper-trading-simulation
plan: 01
subsystem: trading-engine
tags: [sqlite, paper-trading, polygon-api, pandas-market-calendars, avg-cost-basis]

# Dependency graph
requires:
  - phase: 04-lead-lag-engine-regime-signals
    provides: signals table with rowid for source_signal_id FK, returns_policy_a for exit flag checks
provides:
  - paper_trading package with full engine (set_capital, open/close positions, auto-execute signals)
  - 3 SQLite tables (paper_portfolio, paper_positions, paper_trades) with idempotency indexes
  - Polygon snapshot price poller with NYSE market hours guard
  - Portfolio summary with unrealized/realized P&L and win rate
affects: [05-02-PLAN, ui-paper-trading-panel, signal-dashboard]

# Tech tracking
tech-stack:
  added: [pandas-market-calendars>=5.3]
  patterns: [avg-cost-basis-positions, partial-unique-index-idempotency, lazy-singleton-calendar, polygon-snapshot-fallback-chain]

key-files:
  created:
    - paper_trading/__init__.py
    - paper_trading/db.py
    - paper_trading/engine.py
    - paper_trading/models.py
    - paper_trading/price_poller.py
    - tests/test_paper_trading.py
  modified:
    - utils/db.py
    - pyproject.toml

key-decisions:
  - "Average-cost basis for position tracking (not FIFO); simpler, matches Alpaca approach"
  - "SIZING_FRACTIONS: full=20%, half=10%, quarter=5% of starting capital per position"
  - "Polygon snapshot price fallback chain: lastTrade.p -> min.c -> day.c -> prevDay.c"
  - "Lazy-init NYSE calendar singleton (_NYSE=None) to avoid import-time overhead"
  - "Partial unique index idx_trades_signal_buy prevents duplicate auto-execution at DB level"
  - "SQLite FILTER not available; used CASE WHEN for win_rate computation in get_portfolio_summary"

patterns-established:
  - "init_paper_trading_schema called from init_schema: same wiring pattern as init_engine_schema"
  - "All engine functions take conn as first arg: consistent with project convention"
  - "Integer share enforcement: cast to int before any DB write to avoid float precision"
  - "check_exit_flags cross-references signals.ticker_a (leader) against returns_policy_a for invalidation"

# Metrics
duration: 8min
completed: 2026-02-19
---

# Phase 5 Plan 1: Paper Trading Engine Summary

**Paper trading engine with avg-cost positions, Polygon snapshot poller, NYSE market hours guard, and duplicate-safe auto-execution via partial unique index**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-19T05:18:00Z
- **Completed:** 2026-02-19T05:26:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Built complete paper_trading package with schema (3 tables + 4 indexes), engine, price poller, and models
- All 10 new tests pass alongside 137 existing tests (147 total, 0 regressions)
- Idempotent auto-execution: partial unique index on paper_trades(source_signal_id) WHERE side='buy' prevents duplicate signal processing at DB level
- Portfolio summary computes unrealized P&L, realized P&L, win rate, and total P&L with NULL safety

## Task Commits

Each task was committed atomically:

1. **Task 1: Create paper_trading package with schema, models, and DB helpers** - `bc27a04` (feat)
2. **Task 2: Build trading engine, price poller, and tests** - `77403aa` (feat)

## Files Created/Modified
- `paper_trading/__init__.py` - Package exports for all engine and poller functions
- `paper_trading/db.py` - Schema creation (3 tables + indexes) and all DB helper functions
- `paper_trading/engine.py` - Core trading logic: set_capital, open/close positions, auto-execute, P&L summary, exit flags
- `paper_trading/models.py` - Portfolio, Position, Trade dataclasses
- `paper_trading/price_poller.py` - Polygon snapshot price fetching with NYSE market hours guard
- `utils/db.py` - Added init_paper_trading_schema call to init_schema
- `pyproject.toml` - Added pandas-market-calendars>=5.3 dependency
- `tests/test_paper_trading.py` - 10 unit tests covering capital, positions, P&L, sizing, idempotency

## Decisions Made
- Average-cost basis for position tracking (not FIFO) -- simpler and appropriate for a paper trading simulator
- SIZING_FRACTIONS constants: full=20%, half=10%, quarter=5% of starting capital -- conservative per-position sizing
- Polygon snapshot fallback chain: lastTrade.p -> min.c -> day.c -> prevDay.c for robust price extraction
- Lazy-init NYSE calendar singleton to avoid import-time pandas_market_calendars overhead
- Used CASE WHEN instead of FILTER (WHERE ...) for SQLite compatibility in win_rate computation in get_portfolio_summary

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used CASE WHEN instead of FILTER in portfolio summary SQL**
- **Found during:** Task 2 (get_portfolio_summary implementation)
- **Issue:** Plan's research code used `COUNT(*) FILTER (WHERE realized_pnl > 0)` which is SQLite 3.30+ syntax but some builds may not support it reliably with the row_factory pattern
- **Fix:** Used `COUNT(CASE WHEN realized_pnl > 0 THEN 1 END)` which is universally supported
- **Files modified:** paper_trading/engine.py
- **Verification:** test_get_portfolio_summary passes
- **Committed in:** 77403aa (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug prevention)
**Impact on plan:** Minimal -- SQL syntax adjustment for broader compatibility. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- paper_trading package is fully importable with all engine + price_poller exports
- Plan 05-02 (Gradio UI) can directly import: set_capital, open_or_add_position, close_position, auto_execute_signals, get_portfolio_summary, get_open_positions_display, get_trade_history_display, fetch_snapshot_price, is_market_open, poll_and_update_prices
- All functions take conn as first arg for thread-safe per-connection usage from Gradio timer handlers

## Self-Check: PASSED

- All 7 created files exist on disk
- Commit bc27a04 (Task 1) found in git log
- Commit 77403aa (Task 2) found in git log
- 147 tests pass (10 new + 137 existing)

---
*Phase: 05-paper-trading-simulation*
*Completed: 2026-02-19*
