---
phase: 05-paper-trading-simulation
plan: 02
subsystem: ui
tags: [gradio, paper-trading, gr.Timer, signal-dashboard, live-refresh]

# Dependency graph
requires:
  - phase: 05-paper-trading-simulation/05-01
    provides: paper_trading engine, price poller, DB schema (TRADE-01 through TRADE-08)
provides:
  - Signal Dashboard tab (UI-01): active signals table with auto-execute toggle, last 7 days
  - Paper Trading tab (UI-04): capital setup, open positions with 15-min live refresh, manual Buy/Sell, portfolio P&L summary, trade history
  - gr.Timer(900) for automatic position price polling every 15 minutes
affects: [06-backtesting-analysis]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - build_*_tab(conn, config) functions called inside gr.Blocks context -- each creates its own gr.Tab internally
    - gr.Timer(value=900, active=True) wired to poll_and_update_prices for live refresh without user action
    - Shared conn (check_same_thread=False + WAL mode) passed into all tab builders for single-user local app

key-files:
  created:
    - ui/signal_dashboard.py
    - ui/paper_trading_panel.py
  modified:
    - ui/app.py

key-decisions:
  - "build_signal_dashboard_tab and build_paper_trading_tab each create their own gr.Tab internally -- app.py only calls the builders, no wrapping needed"
  - "gr.Timer(900) wired to refresh_prices_callback which calls poll_and_update_prices then returns updated positions DataFrame"
  - "Shared conn passed by closure into tab builders -- WAL mode + check_same_thread=False makes this safe for single-user local app"
  - "execute_signals_callback guards on auto_execute_enabled toggle before calling auto_execute_signals to prevent accidental execution"

patterns-established:
  - "Tab builder pattern: module exports build_*_tab(conn, config) -> called inside gr.Blocks, creates gr.Tab internally"
  - "Live refresh pattern: gr.Timer.tick() -> backend price poller -> return updated DataFrame to Dataframe component"

# Metrics
duration: ~25min
completed: 2026-02-19
---

# Phase 5 Plan 02: Signal Dashboard and Paper Trading UI Summary

**Two new Gradio tabs wiring the paper_trading backend to the browser: Signal Dashboard with auto-execute toggle and Paper Trading with gr.Timer(900) live position refresh, manual Buy/Sell, and portfolio P&L tracking.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-02-19
- **Completed:** 2026-02-19
- **Tasks:** 3 (2 auto + 1 checkpoint:human-verify -- APPROVED)
- **Files modified:** 3

## Accomplishments

- Built ui/signal_dashboard.py (UI-01): queries signals from last 7 days, shows auto-execute toggle, Execute and Refresh buttons, Executed column per signal
- Built ui/paper_trading_panel.py (UI-04): capital setup (TRADE-01), open positions table with gr.Timer(900) for 15-min auto price refresh (TRADE-04/05), manual Buy/Sell form (TRADE-03), portfolio summary (cash, total P&L, win rate), trade history table (TRADE-08)
- Updated ui/app.py: added 2 imports and 2 build function calls inside gr.Blocks -- app now has 5 tabs total while all 3 existing tabs remain unchanged
- User-verified end-to-end: capital set, Buy executed, partial Sell, P&L tracked, signal dashboard loaded, existing tabs functional -- APPROVED

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Signal Dashboard and Paper Trading panel modules** - `e8ad354` (feat)
2. **Task 2: Integrate new tabs into existing ui/app.py** - `834afd3` (feat)
3. **Task 3: Verify full paper trading UI end-to-end** - checkpoint:human-verify -- APPROVED (no code commit)

## Files Created/Modified

- `ui/signal_dashboard.py` - Signal Dashboard tab builder: signals table (last 7 days), auto-execute toggle, Execute/Refresh buttons, Executed column
- `ui/paper_trading_panel.py` - Paper Trading tab builder: capital setup, positions table with gr.Timer(900), manual Buy/Sell, portfolio summary, trade history
- `ui/app.py` - Added 2 imports and 2 build calls inside gr.Blocks; tab count: 3 -> 5

## Decisions Made

- `build_signal_dashboard_tab` and `build_paper_trading_tab` each create their own `gr.Tab` internally so `app.py` stays minimal -- just two function calls
- `gr.Timer(value=900, active=True)` declared inside the Paper Trading tab builder; `.tick()` wired to `refresh_prices_callback` which calls `poll_and_update_prices` then returns an updated positions DataFrame
- Shared `conn` (already opened with `check_same_thread=False` and WAL mode) passed into tab builders by closure -- appropriate for single-user local app
- `execute_signals_callback` checks the `auto_execute_enabled` toggle before calling `auto_execute_signals`; returns early with a status message if toggle is off

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required beyond the existing `.env` with `POLYGON_API_KEY`.

## Checkpoint Outcome

**Task 3 (checkpoint:human-verify) -- APPROVED by user on 2026-02-19.**

Verification checklist confirmed:
- All 5 tabs visible: Pair Management, Data Ingestion, Normalize, Signal Dashboard, Paper Trading
- Paper Trading tab: Set Capital to 100000, cash balance reflected immediately
- Paper Trading tab: Buy AAPL 10 shares -- position in Open Positions, trade in Trade History, cash decreased
- Paper Trading tab: Sell AAPL 5 shares -- partial close, realized P&L in history, cash increased
- Portfolio summary (Cash Balance, Total P&L, Win Rate) updated after each trade
- Signal Dashboard tab: signals table loaded, auto-execute toggle and Execute button functional
- Existing tabs (Pair Management, Data Ingestion, Normalize) unaffected
- gr.Timer active for 15-min position price refresh

## Next Phase Readiness

- Phase 5 complete. All paper trading functionality is live in the Gradio UI.
- Phase 6 (Backtesting and Analysis) can begin. The paper_trading engine (open positions, trade history, P&L) provides the ground-truth dataset for backtest comparison.
- No blockers.

---
*Phase: 05-paper-trading-simulation*
*Completed: 2026-02-19*
