---
phase: 07-outperformance-signal-enhancement
plan: "03"
subsystem: backtest
tags: [backtest, pipeline-scheduler, sqlite, numpy, pandas, per-action-metrics]

# Dependency graph
requires:
  - phase: 07-01
    provides: signals table with action column (nullable, COALESCE to UNKNOWN)
provides:
  - Pipeline scheduler polling every 15 minutes instead of 30
  - run_backtest() returns by_action dict with BUY/HOLD/SELL/UNKNOWN always present
  - _compute_action_metrics() helper for per-group Sharpe/drawdown/outperformance computation
  - outperformance_vs_leader = mean(follower_return - leader_return) per action group
affects:
  - 07-04-PLAN.md (tests for by_action backtest structure)
  - backtest API routes that consume run_backtest() output

# Tech tracking
tech-stack:
  added: [numpy (added import to engine.py)]
  patterns:
    - COALESCE(action, 'UNKNOWN') in SQL query handles pre-Phase-7 signals with null action
    - Per-action metric helper (_compute_action_metrics) receives (follower_return, leader_return) pairs
    - by_action always contains all 4 keys — missing action groups get zero-dict via empty-list path

key-files:
  created: []
  modified:
    - utils/pipeline_scheduler.py
    - backtest/engine.py

key-decisions:
  - "POLL_INTERVAL changed from 1800 to 900 — more responsive signal updates at no cost"
  - "by_action is additive — existing flat aggregate metrics (hit_rate, annualized_sharpe, etc.) unchanged"
  - "outperformance_vs_leader uses only paired rows where leader return is non-null; falls back to 0.0 when no leader data"
  - "leader return is fetched from features_lagged_returns using the same (leader, signal_date, optimal_lag) key as follower"

patterns-established:
  - "_compute_action_metrics() pattern: zero-dict guard on empty input, separate follower/leader return filtering"
  - "action_trade_tuples list: (follower_return, leader_return, action) per-signal accumulator fed into groupby"

requirements-completed: [OUT-04, OUT-05]

# Metrics
duration: 2min
completed: 2026-03-21
---

# Phase 7 Plan 03: Pipeline Scheduler + Per-Action Backtest Summary

**Pipeline scheduler reduced to 15-minute polling; run_backtest() extended with per-action BUY/HOLD/SELL/UNKNOWN breakdown including outperformance_vs_leader metric**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-21T22:34:22Z
- **Completed:** 2026-03-21T22:36:01Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Changed `POLL_INTERVAL` from 1800 to 900 in `utils/pipeline_scheduler.py` — pipeline now checks every 15 minutes instead of 30
- Extended `run_backtest()` to fetch `COALESCE(action, 'UNKNOWN')` from the signals query; pre-Phase-7 null-action signals land in UNKNOWN bucket
- Added `_compute_action_metrics()` helper that computes total_trades, winning_trades, hit_rate, mean_return, annualized_sharpe, max_drawdown, and outperformance_vs_leader for any action group
- `by_action` dict always contains all 4 keys (BUY/HOLD/SELL/UNKNOWN); missing action groups get zero-filled sub-dict
- All 4 existing backtest engine tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Reduce pipeline scheduler poll interval to 15 minutes** - `3541ea5` (feat)
2. **Task 2: Add per-action breakdown to run_backtest()** - `3e50623` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `utils/pipeline_scheduler.py` - POLL_INTERVAL 1800 → 900; docstring comment updated to match
- `backtest/engine.py` - Added numpy import, updated signals query, per-signal leader return fetch, _compute_action_metrics helper, by_action assembly and return key

## Decisions Made
- `by_action` is purely additive — all existing flat aggregate keys (hit_rate, mean_return_per_trade, annualized_sharpe, max_drawdown) remain unchanged, ensuring backward compatibility with all current callers
- Leader return lookup uses the same `(leader, signal_date, optimal_lag)` key as the follower return — consistent with BACKTEST-01 (SQLite-only reads)
- `outperformance_vs_leader` gracefully falls back to 0.0 when no leader return data is available for a group, rather than None or error

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 07-04 can now write tests for by_action backtest structure, _compute_action_metrics edge cases, and COALESCE/UNKNOWN bucket behavior
- run_backtest() API consumers (UI routes) can start surfacing per-action metrics if desired

---
*Phase: 07-outperformance-signal-enhancement*
*Completed: 2026-03-21*
