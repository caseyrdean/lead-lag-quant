---
phase: 05-paper-trading-simulation
verified: 2026-02-19T06:00:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
---

# Phase 5: Paper Trading Simulation Verification Report

**Phase Goal:** Users can validate signal quality with simulated trades -- auto-executed from signals or manually entered -- with live-ish price tracking and full P&L accounting
**Verified:** 2026-02-19T06:00:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can set starting paper capital and see it reflected in a portfolio row | VERIFIED | set_capital() in engine.py upserts paper_portfolio with ON CONFLICT; smoke test confirmed cash_balance=100000 |
| 2 | System auto-executes trades when qualifying signals fire (with auto-execute toggle) | VERIFIED | auto_execute_signals() in engine.py; execute_signals_callback() guards on toggle before calling engine |
| 3 | User can manually enter Buy or Sell for any ticker with custom share quantity via Gradio panel | VERIFIED | buy_callback() and sell_callback() in paper_trading_panel.py; fetch live price via Polygon, call engine |
| 4 | Open positions display entry price, current price, unrealized P&L with 15-min refresh during market hours | VERIFIED | gr.Timer(value=900) in paper_trading_panel.py; price_timer.tick(fn=refresh_prices_callback) wired |
| 5 | Closed positions record realized P&L in SQLite; full trade history visible in UI | VERIFIED | close_position() computes and records realized_pnl; history_table fed by get_trade_history_display() |
| 6 | Positions are flagged for exit when leader reversal exceeds invalidation_threshold | VERIFIED | check_exit_flags() queries returns_policy_a for leader ticker; exit_flag boolean in each position dict |
| 7 | Duplicate auto-execution of same signal is impossible (DB constraint enforced) | VERIFIED | Partial unique index idx_trades_signal_buy WHERE side=buy; test_duplicate_auto_execution_blocked passes |
| 8 | Price polling only fires during NYSE market hours | VERIFIED | is_market_open() uses pandas_market_calendars; poll_and_update_prices() returns 0 if market is closed |
| 9 | Signal Dashboard tab shows active signals with auto-execute toggle | VERIFIED | build_signal_dashboard_tab() builds gr.Tab with Checkbox, Dataframe (7-day query), Execute/Refresh buttons |
| 10 | Paper Trading tab has capital setup, positions, manual trade entry, portfolio summary, trade history | VERIFIED | build_paper_trading_tab() builds full 5-section layout; all UI components wired to engine |
| 11 | All 5 tabs work correctly (3 existing + Signal Dashboard + Paper Trading) | VERIFIED | app.py builds cleanly; 147/147 tests pass with 0 regressions |
| 12 | Portfolio summary (cash, unrealized P&L, realized P&L, win rate) computed correctly | VERIFIED | get_portfolio_summary() uses COALESCE + CASE WHEN; smoke test confirmed correct output |

**Score:** 12/12 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| paper_trading/__init__.py | Package exports for PaperTradingEngine | VERIFIED | Exports all 12 symbols via __all__; imports from engine, price_poller, db |
| paper_trading/db.py | Schema (3 tables + indexes) and all DB helpers | VERIFIED | 226 lines; init_paper_trading_schema + 6 helper functions including check_exit_flags |
| paper_trading/engine.py | Core trading logic: set_capital, open, close, auto, summaries | VERIFIED | 436 lines; all 7 required functions fully implemented |
| paper_trading/price_poller.py | Polygon snapshot fetching + market hours guard | VERIFIED | 114 lines; is_market_open, fetch_snapshot_price (fallback chain), poll_and_update_prices |
| paper_trading/models.py | Dataclass definitions for Portfolio, Position, Trade | VERIFIED | 47 lines; all 3 dataclasses with correct field definitions |
| tests/test_paper_trading.py | Unit tests for engine core logic (min 40 lines) | VERIFIED | 262 lines; 10 tests covering capital, positions, P&L, sizing, idempotency -- all pass |
| ui/signal_dashboard.py | Signal Dashboard panel builder (UI-01) | VERIFIED | 179 lines; exports build_signal_dashboard_tab(conn, config) |
| ui/paper_trading_panel.py | Paper Trading panel builder (UI-04) | VERIFIED | 440 lines; exports build_paper_trading_tab(conn, config) |
| ui/app.py | Updated Gradio app with 5 tabs | VERIFIED | Imports and calls both builders inside gr.Blocks; 5-tab app creation confirmed |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| paper_trading/engine.py | paper_trading/db.py | from paper_trading.db import | WIRED | Lines 10-15: imports check_exit_flags, get_open_positions, get_portfolio, get_trade_history |
| paper_trading/engine.py | signals table (via rowid) | SELECT rowid AS signal_id | WIRED | db.py line 125: exact query in get_unprocessed_signals |
| paper_trading/db.py | utils/db.py init_schema() | init_paper_trading_schema called from init_schema | WIRED | utils/db.py line 7 (import) and line 190 (call) confirmed |
| paper_trading/price_poller.py | Polygon snapshot API | requests.get to /v2/snapshot/locale/us/markets/stocks/tickers/{ticker} | WIRED | price_poller.py lines 57-59 confirmed |
| paper_trading/engine.py | paper_trading/price_poller.py | fetch_snapshot_price in auto_execute_signals | WIRED | engine.py line 16 (import) and line 266 (call in auto_execute loop) |
| ui/signal_dashboard.py | paper_trading.engine | auto_execute_signals() called from Execute button | WIRED | signal_dashboard.py line 12 (import) and line 133 (call in callback) |
| ui/paper_trading_panel.py | paper_trading.engine | set_capital, open/close, summary, display functions | WIRED | paper_trading_panel.py lines 14-22: all 7 engine functions imported and called |
| ui/paper_trading_panel.py | paper_trading.price_poller | poll_and_update_prices via gr.Timer tick | WIRED | line 23 (import), line 314 (call in refresh_prices_callback), line 374 (price_timer.tick) |
| ui/app.py | ui/signal_dashboard.py | build_signal_dashboard_tab() inside gr.Blocks | WIRED | app.py line 12 (import), line 303 (call inside gr.Blocks context) |
| ui/app.py | ui/paper_trading_panel.py | build_paper_trading_tab() inside gr.Blocks | WIRED | app.py line 13 (import), line 306 (call inside gr.Blocks context) |

---

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| TRADE-01 | SATISFIED | set_capital() creates/resets paper_portfolio row with starting capital and cash_balance |
| TRADE-02 | SATISFIED | auto_execute_signals() with SIZING_FRACTIONS (full/half/quarter); compute_share_quantity() |
| TRADE-03 | SATISFIED | open_or_add_position() (buy) and close_position() (sell); manual Buy/Sell UI form |
| TRADE-04 | SATISFIED | get_open_positions_display() computes unrealized P&L per position using current_price |
| TRADE-05 | SATISFIED | gr.Timer(900) + poll_and_update_prices() + is_market_open() NYSE calendar guard |
| TRADE-06 | SATISFIED | close_position() computes realized_pnl = shares * (close_price - avg_cost) |
| TRADE-07 | SATISFIED | check_exit_flags() queries leader return_1d vs invalidation_threshold; EXIT flag shown in UI |
| TRADE-08 | SATISFIED | get_trade_history_display() + history_table DataFrame in Paper Trading tab |
| UI-01 | SATISFIED | build_signal_dashboard_tab() with toggle, signals table (last 7 days), Execute/Refresh buttons |
| UI-04 | SATISFIED | build_paper_trading_tab() with all sub-sections per plan specification |

---

### Anti-Patterns Found

None. No stub patterns, TODO/FIXME comments, empty returns, or placeholder implementations found in any Phase 5 file.

The only match for the word placeholder in Phase 5 files is paper_trading_panel.py line 385 (placeholder="e.g. AAPL") -- a Textbox widget hint attribute, not a code stub.

---

### Human Verification

The following items were confirmed by the user during plan 05-02 Task 3 (checkpoint:human-verify, APPROVED 2026-02-19):

1. 5-tab UI layout -- All 5 tabs visible: Pair Management, Data Ingestion, Normalize, Signal Dashboard, Paper Trading.
2. Set Capital flow -- Enter 100000, click Set Capital -- Cash Balance reflects 100000 immediately.
3. Buy flow -- Enter AAPL, 10 shares, click Buy -- position in Open Positions, trade in Trade History, cash decreases.
4. Sell flow -- Enter AAPL, 5 shares, click Sell -- partial close, realized P&L in history, cash increases.
5. Portfolio summary updates -- Cash Balance, Total P&L, Win Rate update after each trade action.
6. Signal Dashboard -- Signals table loads, auto-execute toggle and Execute button work without errors.
7. Existing tabs unaffected -- Pair Management, Data Ingestion, Normalize all still functional.
8. gr.Timer active -- 15-minute timer confirmed active for position price refresh.

---

### Test Results

- uv run pytest tests/test_paper_trading.py -v -- 10/10 passed
- uv run pytest tests/ --tb=short -- 147/147 passed (0 regressions)

### Commit Verification

All 4 phase task commits verified in git log:
- bc27a04 -- feat(05-01): create paper_trading package with schema, models, and DB helpers
- 77403aa -- feat(05-01): build trading engine, price poller, and tests
- e8ad354 -- feat(05-02): create Signal Dashboard and Paper Trading panel modules
- 834afd3 -- feat(05-02): integrate Signal Dashboard and Paper Trading tabs into app.py

---

## Gaps Summary

No gaps. All 12 must-have truths verified. All artifacts exist, are substantive, and are fully wired. All 10 requirements satisfied. No anti-patterns found. User-approved end-to-end verification completed.

Phase 5 goal is fully achieved. Key highlights:

- DB schema creates 3 tables with idempotency via partial unique index (idx_trades_signal_buy) preventing duplicate signal auto-execution at the database level.
- Avg-cost basis position model is correctly implemented with ON CONFLICT arithmetic in SQL.
- Price poller correctly guards with is_market_open() using pandas_market_calendars before hitting the Polygon snapshot API.
- All 10 unit tests pass, covering capital setup, position lifecycle, P&L math, share sizing, and idempotency prevention.
- Both Gradio tab builders are fully wired. The gr.Timer tick is connected to refresh_prices_callback which calls poll_and_update_prices.
- The app assembles cleanly with 5 tabs and passed the user-approved end-to-end checklist.

---

_Verified: 2026-02-19T06:00:00Z_
_Verifier: Claude (gsd-verifier)_
