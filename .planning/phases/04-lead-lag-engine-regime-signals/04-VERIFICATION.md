---
phase: 04-lead-lag-engine-regime-signals
verified: 2026-02-18T20:30:00Z
status: passed
score: 17/17 must-haves verified
re_verification: false
gaps: []
human_verification: []
---

# Phase 4: Lead-Lag Engine and Regime Signals Verification Report

**Phase Goal:** Features are consumed to detect statistically stable lead-lag relationships, classify market regime, and generate full position specs that meet strict confidence thresholds
**Verified:** 2026-02-18T20:30:00Z
**Status:** PASSED
**Re-verification:** No - initial verification

---

## Goal Achievement

### Observable Truths - Plan 01

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | detect_optimal_lag() returns the lag with highest absolute median correlation and its strength given is_significant=1 rows | VERIFIED | detector.py lines 89-90: eligible median_corr abs idxmax and signed median_corr returned |
| 2 | detect_optimal_lag() returns None when fewer than 30 significant observations for any lag (NULL-not-zero) | VERIFIED | detector.py lines 78-87: eligible filtered by count >= _MIN_SIGNIFICANT_DAYS=30, returns None if empty |
| 3 | compute_stability_score() accepts five sub-score floats 0-100 and returns weighted scalar using weights 0.30/0.25/0.20/0.15/0.10 | VERIFIED | stability.py lines 23-29: WEIGHTS constant defined; line 222: sum(WEIGHTS[k] times sub_scores[k] for k in WEIGHTS) |
| 4 | Each RSI-v2 sub-score function handles empty DataFrames by returning 0.0, not raising an exception | VERIFIED | All five functions check for None anchor or empty df and return 0.0 explicitly |
| 5 | regime_states and distribution_events tables exist in the schema after init_schema() runs | VERIFIED | db.py lines 11-30 define both tables; utils/db.py line 188 calls init_engine_schema(conn) at end of init_schema() |
| 6 | signals and flow_map tables exist in the schema after init_schema() runs | VERIFIED | db.py lines 32-63 define both tables; same init_schema() call chain confirms both tables created |

### Observable Truths - Plan 02

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 7 | classify_regime() returns Bull when RS > +5% for 10+ sessions AND price above both 21d and 50d MA | VERIFIED | regime.py lines 152-160: bull_streak >= _BULL_RS_SESSIONS AND latest_price > ma_21 AND latest_price > ma_50 |
| 8 | classify_regime() returns Bear when RS < -7% for 5+ consecutive sessions | VERIFIED | regime.py lines 150-151: bear_streak >= _BEAR_RS_SESSIONS yields Bear |
| 9 | classify_regime() returns Failure when Bear RS condition AND ATR expanding > 130% of 20d ATR | VERIFIED | regime.py lines 148-149: atr_expanding and bear_streak >= _BEAR_RS_SESSIONS yields Failure; Wilder EWM span=39 at line 53 |
| 10 | classify_regime() returns Base as default when no other rule matches | VERIFIED | regime.py line 160: else regime = Base |
| 11 | Distribution events flagged when volume > 150% of 30d avg AND VWAP rejection streak >= 3 sessions | VERIFIED | distribution.py lines 57-75: is_distribution = high_vol_down AND (streak >= _VWAP_REJECTION_STREAK=3) |
| 12 | No signal generated when stability_score <= 70 OR abs(correlation_strength) <= 0.65 (hard gate) | VERIFIED | generator.py line 55: stability_score > STABILITY_THRESHOLD and abs(correlation_strength) > CORRELATION_THRESHOLD |
| 13 | Qualifying signals have adjustment_policy_id = policy_a on every record | VERIFIED | generator.py line 210: adjustment_policy_id hardcoded to policy_a |
| 14 | Signals stored with generated_at preserved on re-run (ON CONFLICT does not overwrite generated_at) | VERIFIED | db.py lines 90-101: ON CONFLICT SET list does not include generated_at; comment at line 101 confirms intentional exclusion |
| 15 | Full position spec generated: direction, expected_target, invalidation_threshold, sizing_tier, flow_map_entry | VERIFIED | generator.py lines 201-216: all five fields in signal dict; expected_target from features_lagged_returns; invalidation_threshold from returns_policy_a |
| 16 | Sizing tier: stability_score > 85 = full; 70 < score <= 85 = half | VERIFIED | generator.py lines 65-67: if stability_score > _SIZING_FULL_THRESHOLD return full else return half |
| 17 | run_engine_for_all_pairs() calls classify_regime() BEFORE compute_stability_score() | VERIFIED | pipeline.py line 75: classify_regime before line 88: compute_stability_score; ordering invariant confirmed |

**Score:** 17/17 truths verified

---
## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| lead-lag-quant/leadlag_engine/__init__.py | Package marker + public API exports | VERIFIED | Exports run_engine_for_all_pairs, detect_optimal_lag, compute_stability_score, classify_regime via __all__ |
| lead-lag-quant/leadlag_engine/db.py | init_engine_schema() + upsert_signal() (immutable) + upsert_flow_map() | VERIFIED | All three functions present; upsert_signal ON CONFLICT excludes generated_at |
| lead-lag-quant/leadlag_engine/detector.py | detect_optimal_lag() returning dict or None | VERIFIED | Full implementation with MIN_SIGNIFICANT_DAYS=30, MAX(trading_day) anchoring, signed correlation_strength |
| lead-lag-quant/leadlag_engine/stability.py | Five RSI-v2 sub-score functions + compute_stability_score() + WEIGHTS constant | VERIFIED | All seven exports present; WEIGHTS sums to 1.0 (0.30+0.25+0.20+0.15+0.10) |
| lead-lag-quant/leadlag_engine/regime.py | classify_regime() with Wilder EWM ATR + RS streaks + 4-state priority | VERIFIED | Full implementation; ewm(span=39, min_periods=20); persists to regime_states table |
| lead-lag-quant/leadlag_engine/distribution.py | detect_distribution_events() with VWAP streak + volume ratio | VERIFIED | Full implementation; pandas groupby streak idiom; upserts to distribution_events table |
| lead-lag-quant/leadlag_engine/pipeline.py | run_engine_for_all_pairs() orchestrator with correct ordering | VERIFIED | classify_regime at line 75 before compute_stability_score at line 88 |
| lead-lag-quant/signals/__init__.py | Empty package marker | VERIFIED | Exists as package marker for signals module |
| lead-lag-quant/signals/generator.py | passes_gate() + build_flow_map_entry() + generate_signal() + threshold constants | VERIFIED | All exports + STABILITY_THRESHOLD=70.0 + CORRELATION_THRESHOLD=0.65 present |
| lead-lag-quant/utils/db.py | init_engine_schema() called from init_schema() | VERIFIED | Line 6: from leadlag_engine.db import init_engine_schema; line 188: init_engine_schema(conn) |
| lead-lag-quant/tests/test_engine_detector.py | 7 ENGINE-01 tests | VERIFIED | All 7 tests: empty DB, insufficient days, lag selection, negative corr, NULL filtering, anchor stability, multi-lag |
| lead-lag-quant/tests/test_engine_stability.py | 17+ ENGINE-02 tests | VERIFIED | 18 test functions covering weights, all five sub-scores empty and populated |
| lead-lag-quant/tests/test_engine_regime.py | 9 regime + distribution tests | VERIFIED | 9 test functions: all four regime states, ATR expansion, distribution flagging, streak edge case |
| lead-lag-quant/tests/test_signals_generator.py | 13+ signal generator tests | VERIFIED | 18 test functions: gate boundaries, sizing, flow map lag convention, direction, policy, immutability |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| detector.py | features_cross_correlation | is_significant=1 AND correlation IS NOT NULL filters | WIRED | Lines 44-47 and 54-60: both filters present in anchor query and main query |
| stability.py | features_cross_correlation | MAX(trading_day) anchoring | WIRED | _get_anchor() queries MAX(trading_day); all sub-score functions call _get_anchor() before any DB read |
| utils/db.py | leadlag_engine/db.py | init_schema() calls init_engine_schema(conn) | WIRED | Line 6: from leadlag_engine.db import init_engine_schema; line 188: init_engine_schema(conn) |
| pipeline.py | regime.py | classify_regime() before compute_stability_score() - mandatory ordering | WIRED | pipeline.py line 75 (classify_regime) precedes line 88 (compute_stability_score) |
| generator.py | features_lagged_returns (SQLite) | compute_expected_target() queries return_value at optimal_lag | WIRED | Lines 106-116: SELECT return_value FROM features_lagged_returns WHERE ticker=? AND lag=? |
| generator.py | returns_policy_a (SQLite) | compute_invalidation_threshold() queries return_1d for leader | WIRED | Lines 141-154: SELECT return_1d FROM returns_policy_a WHERE ticker=? |
| regime.py | normalized_bars (SQLite) | ATR from high/low/adj_close via Wilder EWM span=39 min_periods=20 | WIRED | Lines 88-96: SELECT from normalized_bars; line 53: tr.ewm(span=39, min_periods=20).mean() |
| pipeline.py | leadlag_engine/db.py upsert_signal() | qualifying signals persisted after gate passes | WIRED | generator.py lines 219-221: from leadlag_engine.db import upsert_signal; upsert_signal(conn, signal) |

---
## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| ENGINE-01: Optimal lag detection from features_cross_correlation | SATISFIED | detect_optimal_lag() with 30-day minimum and signed correlation_strength |
| ENGINE-02: RSI-v2 five-component stability score | SATISFIED | compute_stability_score() with WEIGHTS {lag_persistence:0.30, walk_forward_oos:0.25, rolling_confirmation:0.20, regime_stability:0.15, lag_drift:0.10} |
| ENGINE-03: Hard gate enforcement | SATISFIED | passes_gate() with strict > inequalities; abs() on correlation allows short signals |
| REGIME-01: Four-state regime classifier | SATISFIED | classify_regime() with Wilder EWM ATR, priority order Failure > Bear > Bull > Base |
| REGIME-02: Distribution event detection | SATISFIED | detect_distribution_events() with VWAP rejection streak and volume ratio |
| SIGNAL-01: Full position spec | SATISFIED | generate_signal() with direction, expected_target, invalidation_threshold, sizing_tier |
| SIGNAL-02: Flow map entry with correct lag sign | SATISFIED | build_flow_map_entry() maps positive lag to b-leads-a, negative to a-leads-b |
| Schema: Four new tables | SATISFIED | regime_states, distribution_events, signals, flow_map all created by init_engine_schema() |
| Immutability: generated_at preserved on conflict | SATISFIED | ON CONFLICT SET list explicitly excludes generated_at in upsert_signal() |

---

## Anti-Patterns Found

No blocking anti-patterns found across all phase 4 production files.

- No TODO/FIXME/PLACEHOLDER comments in any production file
- No stub implementations (no return null, no empty handlers, no static returns passing fake data)
- No disconnected wiring (all imports used, all DB calls return results that drive subsequent logic)
- The only return [] in pipeline.py (line 54) is a legitimate early-exit guard for no active pairs

Documented deviation (INFO only, does not block goal):

| File | Detail | Severity | Impact |
|------|--------|----------|--------|
| lead-lag-quant/signals/generator.py line 55 | Uses abs(correlation_strength) instead of raw value in passes_gate() | INFO | Intentional auto-fix documented in 04-02-SUMMARY.md; enables short signal generation; direction handled separately by sign; all gate boundary tests pass |

---

## Human Verification Required

None. All critical behaviors are verifiable programmatically. The phase involves no UI rendering, no external service calls, and no real-time behavior.

---

## Gaps Summary

No gaps. Phase goal is fully achieved.

All 17 must-have truths verified. All 14 required artifacts exist, are substantive (not stubs), and are wired end-to-end. All 8 key links confirmed wired.

The phase goal is achieved: features from Phase 3 (features_cross_correlation, features_relative_strength, normalized_bars) are consumed; statistically stable lead-lag relationships are detected via detect_optimal_lag() with a 30-day minimum filter; market regime is classified via classify_regime() with four hard-rule states (Failure > Bear > Bull > Base priority order); full position specs meeting strict confidence thresholds (stability_score > 70, abs(correlation_strength) > 0.65) are generated via generate_signal() and stored immutably in the signals table with the complete explainability payload.

The Phase 4 pipeline is end-to-end functional: features in, run_engine_for_all_pairs() out, qualifying position specs stored.

---

_Verified: 2026-02-18T20:30:00Z_
_Verifier: Claude (gsd-verifier)_