---
phase: "06-backtest-visualization"
plan: "01"
subsystem: "backtest"
tags: [backtest, sqlite, fastapi, python, metrics]
dependency_graph:
  requires:
    - "features_lagged_returns table (Phase 3)"
    - "signals table (Phase 4)"
    - "features_cross_correlation table (Phase 3)"
    - "regime_states table (Phase 4)"
    - "distribution_events table (Phase 4)"
  provides:
    - "backtest.engine.run_backtest() — hit rate, Sharpe, drawdown for a pair+date range"
    - "backtest.engine.xcorr_data() — cross-correlation heatmap data"
    - "backtest.engine.regime_state() — current regime with sentinel fallback"
    - "GET /api/backtest/run, /xcorr, /regime FastAPI endpoints"
  affects:
    - "Plan 06-02 (React frontend consumes these three endpoints)"
tech_stack:
  added: []
  patterns:
    - "Pure Python backtest module with no Polygon dependency (BACKTEST-01)"
    - "Signal date range as primary look-ahead bias control (BACKTEST-02)"
    - "Metrics mirror paper_trading/analytics.py (BACKTEST-03)"
    - "FastAPI route pattern mirrors api/routes/analytics.py"
key_files:
  created:
    - "lead-lag-quant/backtest/__init__.py"
    - "lead-lag-quant/backtest/engine.py"
    - "lead-lag-quant/api/routes/backtest.py"
    - "lead-lag-quant/tests/test_backtest_engine.py"
    - "lead-lag-quant/tests/test_api_backtest.py"
  modified:
    - "lead-lag-quant/api/main.py"
decisions:
  - "features_lagged_returns used for return-at-lag lookup to avoid calendar vs. trading day arithmetic (BACKTEST-01, look-ahead bias prevention)"
  - "Signal date range filter (signal_date BETWEEN start AND end) is the primary look-ahead bias control — stored returns already split-adjusted via Policy A"
  - "max_drawdown returned as negative decimal using cumsum/cummax pattern from paper_trading/analytics.py"
  - "regime endpoint accepts leader param for API consistency but queries regime_states by follower (regime is follower-keyed)"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-03-21"
  tasks_completed: 2
  tasks_total: 2
  files_created: 5
  files_modified: 1
---

# Phase 6 Plan 01: Backtest Engine and FastAPI Endpoints Summary

**One-liner:** SQLite-only backtest engine (run_backtest, xcorr_data, regime_state) with three FastAPI endpoints under /api/backtest, backed by four performance metrics computed using the paper_trading/analytics.py patterns.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Backtest engine package | 3ecaad8 | backtest/__init__.py, backtest/engine.py |
| 2 | FastAPI routes + tests | e65280f | api/routes/backtest.py, api/main.py, tests/test_backtest_engine.py, tests/test_api_backtest.py |

## What Was Built

**backtest/engine.py** — three pure Python functions, no Polygon import:

- `run_backtest(conn, leader, follower, start_date, end_date)` — queries signals filtered by date range (look-ahead bias control), looks up `features_lagged_returns` for return-at-lag per signal, computes hit_rate, mean_return_per_trade, annualized_sharpe (via `(mean/std)*sqrt(252)`), max_drawdown (cumsum/cummax). Returns zero-dict when no signals found.

- `xcorr_data(conn, leader, follower, days=60)` — queries features_cross_correlation for last N calendar days. Returns empty list gracefully.

- `regime_state(conn, follower)` — queries regime_states LEFT JOIN distribution_events for most recent trading day. Returns sentinel `{"regime": "Unknown", ...}` when table is empty.

**api/routes/backtest.py** — three GET endpoints mirroring analytics.py pattern:
- `GET /backtest/run` — calls run_backtest
- `GET /backtest/xcorr` — calls xcorr_data, days param defaults to 60
- `GET /backtest/regime` — calls regime_state(follower)

**api/main.py** — backtest router registered under `/api` prefix.

**Tests** — 7 tests total, all passing:
- 4 unit tests in test_backtest_engine.py (zero-dict, hit_rate=0.5, empty xcorr, sentinel regime)
- 3 integration tests in test_api_backtest.py (all three endpoints return 200 with required keys)

## Deviations from Plan

None — plan executed exactly as written.

## Pre-existing Test Failures (Out of Scope)

Two test files had pre-existing failures before this plan's changes, confirmed by git stash verification:
- `tests/test_engine_detector.py::test_detect_optimal_lag_insufficient_days` (1 failure)
- `tests/test_signals_generator.py` (multiple failures related to unstaged changes in leadlag_engine/detector.py and leadlag_engine/pipeline.py)

Neither file was touched by this plan. Logged for deferred handling.

## Self-Check: PASSED

Files verified:
- `lead-lag-quant/backtest/__init__.py` — exists
- `lead-lag-quant/backtest/engine.py` — exists
- `lead-lag-quant/api/routes/backtest.py` — exists
- `lead-lag-quant/tests/test_backtest_engine.py` — exists
- `lead-lag-quant/tests/test_api_backtest.py` — exists

Commits verified:
- `3ecaad8` — backtest engine package
- `e65280f` — routes, main.py, tests
