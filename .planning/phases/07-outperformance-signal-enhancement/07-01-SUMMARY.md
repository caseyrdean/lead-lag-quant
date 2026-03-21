---
phase: 07-outperformance-signal-enhancement
plan: "01"
subsystem: database
tags: [sqlite, schema-migration, signals, signal-transitions]

requires:
  - phase: 04-lead-lag-engine-regime-signals
    provides: signals table and upsert_signal helper this plan extends

provides:
  - signals table with 5 new nullable columns: action, response_window, rs_acceleration, leader_rs_deceleration, outperformance_margin
  - signal_transitions audit table with pair and signal indexes
  - Updated upsert_signal that writes all 5 new fields on insert and conflict update

affects:
  - 07-02-PLAN.md (signal generator reads/writes action, rs_acceleration, response_window, outperformance_margin)
  - 07-03-PLAN.md (pipeline/backtest consume action column)
  - 07-04-PLAN.md (tests exercise new schema)

tech-stack:
  added: []
  patterns:
    - "Idempotent ALTER TABLE migration via try/except — matches existing data_warning pattern"
    - "generated_at immutability anchor — excluded from ON CONFLICT SET clause"
    - "New nullable outperformance columns default to None in generator dict until 07-02 classifier populates them"

key-files:
  created: []
  modified:
    - leadlag_engine/db.py
    - signals/generator.py

key-decisions:
  - "All 5 new signals columns are nullable — sparse data from short-history pairs must not crash on insert"
  - "signal_transitions table uses separate CREATE TABLE IF NOT EXISTS block, not inline with signals — allows independent migration ordering"
  - "generator.py signal dict gets None defaults for new fields now (Rule 2) — prevents ProgrammingError when upsert_signal uses named params; plan 07-02 will populate real values"

patterns-established:
  - "Idempotent migration pattern: second try/except block after existing data_warning block"

requirements-completed:
  - OUT-01

duration: 2min
completed: 2026-03-21
---

# Phase 7 Plan 01: Schema Migration — 5 New Signals Columns + signal_transitions Table

**Idempotent SQLite migration adds action/response_window/rs_acceleration/leader_rs_deceleration/outperformance_margin to signals table and creates signal_transitions audit table; upsert_signal extended to persist all 5 new fields**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-21T22:30:44Z
- **Completed:** 2026-03-21T22:32:12Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Signals table has 5 new nullable columns for v1.1 outperformance signal enhancement
- signal_transitions audit table created with pair and signal composite indexes
- Migration is idempotent — running init_engine_schema() twice raises no error
- upsert_signal INSERT and ON CONFLICT SET clauses include all 5 new fields; generated_at immutability preserved
- generator.py signal dict defaults new fields to None (prevents ProgrammingError; plan 07-02 will populate real values)

## Task Commits

Each task was committed atomically:

1. **Task 1: Schema migration — 5 new signals columns + signal_transitions table** - `b490fab` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `leadlag_engine/db.py` - Added signal_transitions table + indexes, idempotent ALTER TABLE for 5 columns, extended upsert_signal
- `signals/generator.py` - Added None defaults for 5 new fields in signal dict (Rule 2 auto-fix)

## Decisions Made
- All 5 new columns are nullable (no NOT NULL) — sparse data from short-history pairs must not crash
- signal_transitions table placed in a separate executescript block immediately after the main table block for clean migration ordering
- generator.py None defaults added now rather than waiting for 07-02 to avoid breaking existing upsert_signal callers

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added None defaults for new fields in generator.py signal dict**
- **Found during:** Task 1 (schema migration + upsert_signal update)
- **Issue:** upsert_signal uses named SQL parameters (:action, :response_window, etc.). The existing signal dict in generator.py did not include these keys, which would cause a ProgrammingError on every signal write after the schema change.
- **Fix:** Added 5 keys with `None` default values to the signal dict in signals/generator.py, with a comment indicating plan 07-02 will populate real values.
- **Files modified:** signals/generator.py
- **Verification:** Full test suite ran — 168 passed, 2 pre-existing failures only (test_engine_detector.py)
- **Committed in:** b490fab (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Auto-fix required for correctness — upsert_signal would have broken on every signal write without it. No scope creep.

## Issues Encountered
None — migration verification passed on first attempt.

## Next Phase Readiness
- Schema ready for plan 07-02: BUY/HOLD/SELL classifier + RS acceleration + outperformance margin computation
- signal_transitions table ready for transition logging
- All 168 tests still passing (2 pre-existing test_engine_detector.py failures unchanged)

---
*Phase: 07-outperformance-signal-enhancement*
*Completed: 2026-03-21*
