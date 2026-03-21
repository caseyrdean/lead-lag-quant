---
phase: 07-outperformance-signal-enhancement
plan: "04"
subsystem: testing
tags: [tests, signals, backtest, phase-7, regression]
dependency_graph:
  requires: [07-02, 07-03]
  provides: [test coverage for classify_action, helper None-safety, transition logging, by_action breakdown]
  affects: [tests/test_signals_generator.py, tests/test_backtest_engine.py]
tech_stack:
  added: []
  patterns: [pytest.mark.parametrize, in-memory SQLite fixtures, tmp_db fixture]
key_files:
  created: []
  modified:
    - tests/test_signals_generator.py
    - tests/test_backtest_engine.py
decisions:
  - Transition logging tests use tmp_db fixture (full schema) with minimal data inserts; generate_signal called directly to exercise the transition dedup path
  - classify_action tests use pytest.mark.parametrize for all standard cases; edge cases (always-negative, always-positive) are separate functions with explicit assertions
  - outperformance_vs_leader tests insert both follower and leader rows at same (ticker, signal_date, lag) key — consistent with BACKTEST-01 SQLite-only convention
  - by_action NULL action test omits action column on insert; COALESCE in engine maps it to UNKNOWN
metrics:
  duration_seconds: 154
  completed_date: "2026-03-21"
  tasks_completed: 2
  files_modified: 2
---

# Phase 7 Plan 04: Phase 7 Signal Enhancement Tests Summary

**One-liner:** Regression test suite for classify_action classification logic, helper None-safety (compute_rs_slope, compute_leader_baseline_return, compute_response_window), transition dedup prevention, and by_action/outperformance_vs_leader backtest metrics.

## What Was Built

### Task 1 — tests/test_signals_generator.py

Added 15 new tests covering all Phase 7 signal generation logic:

**classify_action (parametrized, 6 cases):**
- BUY condition 1: consistent positive RS (5 sessions all positive)
- BUY condition 2: reversal (prior negative, recent 3 all positive)
- BUY condition 1: short series (exactly 3 positive, no prior context)
- SELL: 3 consecutive declining sessions
- HOLD: oscillating within band
- HOLD: insufficient data (len < 3)

**classify_action edge case tests (2 standalone):**
- Always-negative declining RS must NOT return BUY
- Always-positive RS returns BUY via condition 1, not reversal path

**Helper None-safety (5 tests):**
- `compute_rs_slope`: None on empty table, None when rows < lookback_sessions (2 < 5)
- `compute_leader_baseline_return`: None on empty features_lagged_returns
- `compute_response_window`: None on empty signal_transitions, None on single BUY cycle (need >= 2)

**Transition logging duplicate prevention (2 tests):**
- HOLD->HOLD: second generate_signal call with same action does NOT add a row to signal_transitions
- HOLD->BUY: action change on a new signal_date adds a second transition row

### Task 2 — tests/test_backtest_engine.py

Added 5 new tests covering Phase 7 backtest breakdown:

**by_action structure (3 tests):**
- Empty date range: by_action always has all 4 keys (BUY/HOLD/SELL/UNKNOWN) with total_trades=0
- 2 BUY + 1 HOLD signals: correctly routed to respective buckets, SELL and UNKNOWN at 0
- NULL action signal (pre-Phase 7): routed to UNKNOWN bucket via COALESCE in engine SQL

**outperformance_vs_leader arithmetic (2 tests):**
- follower_return=0.05, leader_return=0.03 → outperformance_vs_leader = 0.02 (within 1e-6)
- follower_return=0.02, leader_return=0.04 → outperformance_vs_leader = -0.02 (within 1e-6)

## Test Results

- 20 new Phase 7 tests: all pass
- Pre-existing suite: 188 pass (same as before)
- Pre-existing failures in test_engine_detector.py: 2 (documented, unrelated to Phase 7)
- No regressions introduced

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- tests/test_signals_generator.py: modified (verified passing)
- tests/test_backtest_engine.py: modified (verified passing)
- Commit 8211067: task 1 signals tests
- Commit 6dc0496: task 2 backtest tests

## Self-Check: PASSED
