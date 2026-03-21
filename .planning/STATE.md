# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-21 after v1.0 milestone)

**Core value:** Any seeded equity pair produces a reproducible, auditable full position spec backed by statistically validated lead-lag relationships -- and a paper trading simulator to validate those signals against real prices before committing capital.
**Current focus:** v1.0 milestone complete — planning next milestone

## Current Position

Phase: 07-outperformance-signal-enhancement
Status: Complete — all 4 plans done
Last activity: 2026-03-21 — 07-04 Phase 7 test suite: classify_action, helper None-safety, transition dedup, by_action/outperformance_vs_leader

Progress: [####################] v1.1 complete (4/4 plans complete)

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 18
- Timeline: 58 days (2026-01-22 → 2026-03-21)
- Files modified: 155 files, 30,757 insertions
- LOC: ~10,527 Python + ~2,534 TypeScript

**By Phase:**

| Phase | Plans | Status |
|-------|-------|--------|
| 01-data-ingestion-pipeline | 3 | Complete 2026-02-18 |
| 02-normalization-returns | 2 | Complete 2026-02-18 |
| 03-feature-engineering | 2 | Complete 2026-02-18 |
| 04-lead-lag-engine-regime-signals | 2 | Complete 2026-02-18 |
| 05-paper-trading-simulation | 2 | Complete 2026-02-19 |
| 05.1-api-security-data-integrity-fixes | 4 | Complete 2026-03-21 |
| 06-backtest-visualization | 2 | Complete 2026-03-21 |
| 06.1-signal-gate-threshold-fix | 1 | Complete 2026-03-21 |
| 07-outperformance-signal-enhancement | 4/4 | Complete 2026-03-21 |

## Accumulated Context

### Decisions

All decisions logged in PROJECT.md Key Decisions table.

**07-01 (2026-03-21):**
- All 5 new signals columns are nullable — sparse data from short-history pairs must not crash on insert
- signal_transitions table uses separate executescript block for clean migration ordering
- generator.py signal dict gets None defaults for new fields now; plan 07-02 will populate real values

**07-02 (2026-03-21):**
- SELL checked before BUY condition 1 — positive-but-declining RS is a warning signal, not a buy
- classify_action is a pure function (no DB calls) — takes pre-computed rs_series, rs_std, rs_mean
- leader_rs_deceleration computed inline in generate_signal (lag=1 forward return slope over 10 sessions)
- Transition logging: write to signal_transitions only on action state change (no HOLD->HOLD spam)

**07-03 (2026-03-21):**
- by_action is additive — all existing flat aggregate keys in run_backtest() unchanged for backward compatibility
- outperformance_vs_leader falls back to 0.0 (not None) when no leader return data available for a group
- Leader return uses same (leader, signal_date, optimal_lag) key as follower — consistent with BACKTEST-01 (SQLite-only)

**07-04 (2026-03-21):**
- Transition logging tests use generate_signal directly with tmp_db fixture (avoids mocking the dedup path)
- classify_action edge cases tested as standalone functions; parametrize covers standard cases only
- by_action NULL action test omits action column on INSERT; COALESCE in engine SQL maps NULL to UNKNOWN

### Pending Todos

None.

### Blockers/Concerns

None — v1.0 complete at 48/48 requirements.

## Session Continuity

Last session: 2026-03-21
Stopped at: Completed 07-04-PLAN.md — Phase 7 test suite complete; all 4 plans done.
Resume file: none
