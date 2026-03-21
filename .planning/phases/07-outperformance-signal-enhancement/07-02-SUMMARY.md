---
phase: 07-outperformance-signal-enhancement
plan: "02"
subsystem: signals
tags: [signals, classifier, buy-hold-sell, rs-acceleration, outperformance-margin, response-window, signal-transitions]

requires:
  - phase: 07-outperformance-signal-enhancement
    plan: "01"
    provides: 5 new nullable columns in signals table + signal_transitions audit table + updated upsert_signal

provides:
  - classify_action helper: BUY/HOLD/SELL classification from RS series with SELL priority over declining-positive RS
  - compute_rs_slope helper: pair RS slope normalized by RS std dev (follower momentum indicator)
  - compute_leader_baseline_return helper: mean lagged return for leader over 120-day window
  - compute_response_window helper: mean BUY-state duration in sessions (requires >= 2 complete cycles)
  - generate_signal: computes and persists all 5 outperformance fields; logs action transitions to signal_transitions

affects:
  - 07-03-PLAN.md (pipeline/backtest consume action column from signals)
  - 07-04-PLAN.md (tests for classify_action and new generate_signal behavior)

tech-stack:
  added:
    - numpy (added import to signals/generator.py — was already a transitive dep via pandas)
  patterns:
    - "SELL priority over BUY condition 1: declining positive RS is a warning, not a buy signal"
    - "Transition logging guards: new_action != existing_action before INSERT to signal_transitions"
    - "Inline leader_rs_deceleration computation (not a helper) — one-off 10-row polyfit on lag=1 returns"
    - "datetime.now(timezone.utc) for all timestamps — utcnow() deprecated in Python 3.12+"

key-files:
  created: []
  modified:
    - signals/generator.py

key-decisions:
  - "SELL checked before BUY condition 1 — positive-but-declining RS is a warning, BUY requires non-declining positive RS"
  - "classify_action is a pure function (no DB calls) — takes pre-computed rs_series, rs_std, rs_mean"
  - "leader_rs_deceleration computed inline in generate_signal (lag=1 forward return slope over 10 sessions)"
  - "Transition from_action may be None on first write — this is correct bootstrap behavior"

requirements-completed:
  - OUT-02
  - OUT-03

duration: 3min
completed: 2026-03-21
---

# Phase 7 Plan 02: BUY/HOLD/SELL Classifier + RS Acceleration + Outperformance Margin

**Four helper functions + full wiring in generate_signal: classify_action returns BUY/HOLD/SELL from RS series; compute_rs_slope, compute_leader_baseline_return, compute_response_window provide outperformance context; generate_signal now persists all 5 v1.1 fields and logs action transitions**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-21T22:34:20Z
- **Completed:** 2026-03-21T22:37:32Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- `compute_rs_slope`: queries `features_relative_strength`, computes polyfit slope over last 5 sessions, normalizes by RS std dev when >= 10 rows available; returns None when insufficient data
- `compute_leader_baseline_return`: queries `features_lagged_returns` for leader at optimal_lag over 120-day window; returns mean or None
- `compute_response_window`: scans `signal_transitions` for complete BUY→exit cycles, counts sessions via `normalized_bars`; returns mean or None when < 2 cycles
- `classify_action`: pure function — SELL fires first on declining RS (even when positive), then BUY condition 1 (all positive), BUY condition 2 (reversal with prior negative), HOLD otherwise
- `generate_signal`: computes all 5 fields post-gate, reads existing action from `signals` table, writes to `signal_transitions` only on state change, passes all fields to `upsert_signal`
- All 23 `test_signals_generator.py` tests pass; 1 pre-existing `test_engine_detector.py` failure unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Add RS slope, outperformance margin, and response window helpers** - `4e107e9` (feat)
2. **Task 2: Add classify_action and wire all 5 fields into generate_signal** - `ecb3ef1` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `signals/generator.py` — Added numpy import; 4 helper functions (compute_rs_slope, compute_leader_baseline_return, compute_response_window, classify_action + SELL_CONFIRMATION_SESSIONS constant); generate_signal rewritten to compute all 5 fields and log transitions

## Decisions Made

- SELL is checked before BUY condition 1: the plan text listed BUY first but the test expects SELL for `[0.05, 0.04, 0.03, 0.02]` — a positive-but-declining series. Declining takes priority.
- `classify_action` is a pure function with no DB calls; callers fetch RS series and pass stats in.
- `leader_rs_deceleration` is computed inline (not a separate helper) since it's a one-off 10-row query specific to generate_signal's context.
- `datetime.utcnow()` was replaced with `datetime.now(timezone.utc)` to avoid Python 3.12 deprecation warning.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SELL priority reordering — plan text vs test expectation mismatch**
- **Found during:** Task 2 (classify_action implementation)
- **Issue:** The plan listed logic steps as: BUY condition 1 → BUY condition 2 → SELL. With `pd.Series([0.05, 0.04, 0.03, 0.02])`, recent 3 = [0.04, 0.03, 0.02] — all positive, so BUY fires. But the plan's own `<verify>` block asserts `SELL` for that input.
- **Fix:** Moved SELL check before BUY condition 1. A positive-but-declining RS is correctly a SELL signal. BUY only fires when RS is positive AND not declining.
- **Files modified:** signals/generator.py (classify_action function)
- **Commit:** ecb3ef1

**2. [Rule 1 - Bug] Fixed datetime.utcnow() deprecation**
- **Found during:** Task 2 test run (DeprecationWarning in pytest output)
- **Issue:** `datetime.utcnow()` is deprecated in Python 3.12+ and generates warnings during tests.
- **Fix:** Changed to `datetime.now(timezone.utc).isoformat()` — consistent with the rest of the file.
- **Files modified:** signals/generator.py
- **Commit:** ecb3ef1

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Priority reordering is the correct behavior given the must-haves ("SELL fires only when RS has been declining") — declining overrides positive values. No scope creep.

## Issues Encountered

None — both tasks verified on first run after fixes.

## Next Phase Readiness

- Signal generator now produces non-null action values for pairs with RS history
- signal_transitions receives exactly one row per state change (no spam)
- All 5 outperformance fields are nullable-safe
- Ready for plan 07-03: pipeline/backtest integration with action column
- Ready for plan 07-04: test suite expansion for new behavior

---
*Phase: 07-outperformance-signal-enhancement*
*Completed: 2026-03-21*
