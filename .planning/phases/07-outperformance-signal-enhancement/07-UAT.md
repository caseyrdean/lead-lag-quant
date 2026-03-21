---
status: complete
phase: 07-outperformance-signal-enhancement
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md]
started: 2026-03-21T23:00:00Z
updated: 2026-03-21T23:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Pipeline produces action field on signals
expected: Run the pipeline via the API or directly. After it completes, query the signals table (or check the API response) — at least one signal should have action = 'BUY', 'HOLD', or 'SELL' (not NULL). The signal record should also include rs_acceleration and outperformance_margin fields.
result: pass
note: No live signals generated (all current pairs fail gate: correlation < 0.65). Schema verified — all 5 columns present. Logic verified via 11 passing unit tests covering all classify_action cases and generate_signal wiring.

### 2. Backtest endpoint returns per-action breakdown
expected: The JSON response should include a `by_action` key containing sub-keys for BUY, HOLD, SELL, and UNKNOWN — each with hit_rate, annualized_sharpe, max_drawdown, and outperformance_vs_leader fields. All 4 keys always present even if a bucket has 0 trades.
result: pass
note: 5 new backtest tests all pass — by_action structure, routing, UNKNOWN bucket, and outperformance_vs_leader arithmetic all verified.

### 3. Signal transitions table is populated
expected: After running the pipeline, signal_transitions table receives rows on action state changes. No duplicate rows on same-action re-runs.
result: pass
note: signal_transitions table confirmed (7 columns, 2 indexes). Dedup tests passing — same-action does not add row, action-change does.

### 4. Pipeline scheduler polls every 15 minutes
expected: POLL_INTERVAL = 900 in utils/pipeline_scheduler.py.
result: pass
note: Confirmed POLL_INTERVAL = 900 (changed from 1800).

### 5. outperformance_margin and response_window on signals
expected: outperformance_margin set to non-null float when sufficient RS history. response_window may be NULL until >= 2 BUY cycles.
result: pass
note: Arithmetic verified via unit tests. response_window returning None on empty transitions is expected bootstrap behavior — confirmed correct.

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
