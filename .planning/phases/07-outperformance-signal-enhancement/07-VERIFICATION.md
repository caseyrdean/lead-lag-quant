---
phase: 07-outperformance-signal-enhancement
verified: 2026-03-21T22:46:00Z
status: passed
score: 13/13 must-haves verified
re_verification: false
gaps: []
human_verification: []
---

# Phase 7: Outperformance Signal Enhancement — Verification Report

**Phase Goal:** Signals indicate not just that a follower moves with the leader, but whether it is likely to outpace it — BUY/HOLD/SELL action classification, RS acceleration, response window, and outperformance margin added to signals. Backtest engine updated to validate outperformance by action. No UI changes.

**Verified:** 2026-03-21T22:46:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | signals table has 5 new nullable columns: action, response_window, rs_acceleration, leader_rs_deceleration, outperformance_margin | VERIFIED | `db.py` lines 90-97: idempotent ALTER TABLE migration; PRAGMA table_info confirms all 5 present |
| 2 | signal_transitions table exists with correct schema and indexes | VERIFIED | `db.py` lines 66-80: CREATE TABLE IF NOT EXISTS with all required columns + 2 indexes |
| 3 | Migration is idempotent — running init_engine_schema twice raises no error | VERIFIED | try/except wraps ALTER TABLE block; runtime test confirmed |
| 4 | upsert_signal SET clause includes all 5 new fields | VERIFIED | `db.py` lines 138-142: action, response_window, rs_acceleration, leader_rs_deceleration, outperformance_margin all in ON CONFLICT DO UPDATE SET |
| 5 | generate_signal computes and returns action (BUY/HOLD/SELL) for every signal that passes the gate | VERIFIED | `generator.py` lines 462-480: RS series loaded, classify_action called, new_action set |
| 6 | classify_action implements BUY/HOLD/SELL with SELL checked before BUY (declining-positive is a warning) | VERIFIED | `generator.py` lines 299-318: SELL diffs checked first, then BUY condition 1, then BUY condition 2 reversal |
| 7 | rs_acceleration, leader_rs_deceleration, outperformance_margin, response_window are all computed and wired into generate_signal | VERIFIED | `generator.py` lines 432-459: all 4 fields computed; lines 523-527: all passed to signal dict and upsert_signal |
| 8 | Action transitions logged in signal_transitions only when action changes (no HOLD→HOLD duplicates) | VERIFIED | `generator.py` lines 483-503: reads existing_action, guards with `if new_action != existing_action` |
| 9 | Pipeline scheduler polls every 15 minutes | VERIFIED | `pipeline_scheduler.py` line 28: `POLL_INTERVAL = 900` |
| 10 | run_backtest returns by_action with BUY/HOLD/SELL/UNKNOWN keys, each containing outperformance_vs_leader | VERIFIED | `engine.py` lines 227-229: assembles all 4 keys; _compute_action_metrics returns outperformance_vs_leader |
| 11 | Pre-Phase 7 signals with null action appear in UNKNOWN bucket | VERIFIED | `engine.py` line 139: COALESCE(action, 'UNKNOWN') |
| 12 | Test suite covers all Phase 7 logic with no regressions | VERIFIED | 47 tests pass in test_signals_generator.py + test_backtest_engine.py; 183 total (excluding 2 pre-existing detector failures) |
| 13 | No UI changes introduced | VERIFIED | No frontend files modified; phase scope limited to db.py, generator.py, pipeline_scheduler.py, backtest/engine.py, tests/ |

**Score:** 13/13 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `leadlag_engine/db.py` | Schema migration + updated upsert_signal | VERIFIED | 5 new columns, signal_transitions table, idempotent try/except, full upsert SET clause |
| `signals/generator.py` | classify_action, compute_rs_slope, compute_leader_baseline_return, compute_response_window + wiring | VERIFIED | All 4 helpers present; generate_signal computes and passes all 5 fields; transition logging wired |
| `utils/pipeline_scheduler.py` | POLL_INTERVAL = 900 | VERIFIED | Line 28 confirms 900 |
| `backtest/engine.py` | by_action breakdown + outperformance_vs_leader | VERIFIED | _compute_action_metrics helper + by_action loop always produces all 4 keys |
| `tests/test_signals_generator.py` | Phase 7 test coverage for classify_action, helpers, transitions | VERIFIED | 38 tests (28 pre-existing + 10 new Phase 7) all pass |
| `tests/test_backtest_engine.py` | Phase 7 test coverage for by_action and outperformance | VERIFIED | 9 tests (3 pre-existing + 6 new Phase 7) all pass |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `leadlag_engine/db.py` | signals table | `init_engine_schema() ALTER TABLE` | WIRED | ALTER TABLE signals ADD COLUMN action (line 90) present and confirmed at runtime |
| `leadlag_engine/db.py` | signal_transitions table | `CREATE TABLE IF NOT EXISTS signal_transitions` | WIRED | Lines 67-79; table creation confirmed at runtime |
| `signals/generator.py` | features_relative_strength | compute_rs_slope and classify_action RS series queries | WIRED | Line 195: pd.read_sql_query on features_relative_strength; line 462-469: second RS query in generate_signal |
| `signals/generator.py` | signal_transitions table | transition logging inside generate_signal | WIRED | Lines 483-503: read existing action + conditional INSERT INTO signal_transitions |
| `signals/generator.py` | leadlag_engine/db.py upsert_signal | generate_signal passes all 5 new fields | WIRED | Lines 523-527: action, response_window, rs_acceleration, leader_rs_deceleration, outperformance_margin in signal dict; upsert_signal called line 531 |
| `backtest/engine.py` | signals table | SQL query fetches action column | WIRED | Line 139: `COALESCE(action, 'UNKNOWN') as action` in SELECT |
| `backtest/engine.py` | features_lagged_returns | second query per signal for outperformance_vs_leader | WIRED | Lines 190-197: leader_row query on features_lagged_returns |
| `tests/test_signals_generator.py` | signals/generator.py | direct unit test imports | WIRED | Lines 16-26: imports classify_action, compute_rs_slope, compute_leader_baseline_return, compute_response_window |
| `tests/test_backtest_engine.py` | backtest/engine.py | run_backtest invocation | WIRED | Line 16: `from backtest.engine import run_backtest` |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| OUT-01 | 07-01 | Schema migration — 5 new signals columns + signal_transitions table | SATISFIED | db.py migration block + upsert_signal updated with all 5 fields |
| OUT-02 | 07-02 | BUY/HOLD/SELL action classification via classify_action | SATISFIED | classify_action in generator.py; wired in generate_signal |
| OUT-03 | 07-02 | RS acceleration, leader deceleration, outperformance margin, response window helpers | SATISFIED | compute_rs_slope, compute_leader_baseline_return, compute_response_window all present; leader_rs_deceleration inline in generate_signal |
| OUT-04 | 07-03 | Pipeline scheduler poll interval reduced to 15 minutes | SATISFIED | POLL_INTERVAL = 900 in pipeline_scheduler.py line 28 |
| OUT-05 | 07-03 | Backtest by_action breakdown with outperformance_vs_leader | SATISFIED | _compute_action_metrics + by_action loop in engine.py; COALESCE ensures UNKNOWN bucket |
| OUT-06 | 07-04 | Test suite coverage for all Phase 7 logic | SATISFIED | 47 Phase 7 tests pass; covers classify_action cases, helper None-safety, transition duplicate prevention, by_action structure, outperformance arithmetic |

---

## Implementation Note: classify_action Evaluation Order

The plan (07-02 Task 2) described the logic order as: insufficient data → BUY1 → BUY2 → SELL → HOLD-band → default HOLD.

The implementation reverses BUY and SELL: insufficient data → **SELL** → BUY1 → BUY2 → HOLD-band → default HOLD.

This is intentional and correctly aligned. The code comment notes "a positive-but-declining series is a warning signal, not a buy." The test contract in 07-04 expects `SELL` for `rs=[0.05, 0.04, 0.03, 0.02]` (declining-positive), which the implementation produces correctly. This is a deliberate improvement on the plan spec, not a gap.

---

## Anti-Patterns Found

None. No TODO/FIXME/placeholder comments, no stub implementations, no empty handlers in any of the 6 modified files.

---

## Test Run Summary

```
tests/test_signals_generator.py   38 passed
tests/test_backtest_engine.py      9 passed
Total (Phase 7 files):            47 passed

Full suite (excluding test_engine_detector.py):  183 passed
test_engine_detector.py:  2 pre-existing failures (documented, not introduced by Phase 7)
```

Pre-existing failures in `test_engine_detector.py` are unrelated to Phase 7: they test the `detect_optimal_lag` insufficient-days guard which was modified in a prior phase and tracked separately (ENGINE-03 gap, Phase 06.1).

---

## Human Verification Required

None. All Phase 7 deliverables are verifiable programmatically. The phase explicitly excluded UI changes, so there are no visual or interactive elements to verify manually.

---

## Gaps Summary

No gaps. All 13 observable truths verified, all 6 requirements satisfied, all artifacts substantive and wired, full test coverage passing.

---

_Verified: 2026-03-21T22:46:00Z_
_Verifier: Claude (gsd-verifier)_
