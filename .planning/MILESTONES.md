# Milestones

## v1.1 Outperformance Signals — Shipped 2026-03-21

**Phases:** 7 (1 phase, 4 plans)
**Requirements:** 6/6 satisfied (OUT-01 through OUT-06)

**Delivered:** BUY/HOLD/SELL action classification, RS acceleration, outperformance margin, and response window added to every gate-passing signal; backtest disaggregated by action with outperformance_vs_leader; pipeline polls every 15 minutes; signal_transitions audit table tracks all state changes.

**Key Accomplishments:**
1. `classify_action` pure function: SELL fires first on declining RS, BUY on consistent positive or reversal (3+ sessions), HOLD within ±1 std dev RS band
2. 5 new nullable signal fields wired end-to-end: schema → generator → upsert → backtest
3. `signal_transitions` audit table: one row per action state change, timestamped, no duplicates
4. `run_backtest()` returns `by_action` dict — BUY/HOLD/SELL/UNKNOWN each with hit_rate, Sharpe, drawdown, outperformance_vs_leader
5. 20 new tests; full suite 183 passing, 0 regressions

**Archives:**
- [v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md) — phase details and decisions
- [v1.1-REQUIREMENTS.md](milestones/v1.1-REQUIREMENTS.md) — all 6 OUT-* requirements with traceability

## v1.0 MVP — Shipped 2026-03-21

**Phases:** 1–6.1 (8 phases, 18 plans)
**Timeline:** 2026-01-22 → 2026-03-21 (58 days)
**LOC:** ~10,527 Python + ~2,534 TypeScript
**Requirements:** 48/48 satisfied

**Delivered:** A local FastAPI + React quantitative analytics application that ingests unadjusted equity data from Polygon.io, applies Policy A split-adjustment, detects statistically stable lead-lag relationships, generates auditable full position specs with hard confidence thresholds, validates signals through paper trading simulation, and exposes stored-data backtesting with lead-lag charts and regime state visualization.

**Key Accomplishments:**
1. Full SQLite-backed data pipeline: Polygon.io ingestion (pagination, rate-limiting, idempotency) → Policy A split-adjustment → rolling feature engineering (cross-correlation, RS, volatility, z-scores, lagged returns)
2. Lead-lag engine with RSI-v2 stability scoring (5-component composite 0–100) and hard-gate signal generation (stability > 70, correlation > 0.65)
3. Regime classifier (Bull/Base/Bear/Failure) + distribution event detection via MA structure, RS streaks, ATR, volume/VWAP rules
4. Paper trading simulator: auto-execution from signals, 15-min Polygon price polling, average-cost P&L tracking, WebSocket-pushed position updates
5. FastAPI backend replacing Gradio: free-tier limits, input validation, soft-delete filtering, concurrent execution mutex, run_coroutine_threadsafe WebSocket reliability
6. React/Vite frontend: Backtest Results, Lead-Lag Charts, Regime State pages with full component library

**Archives:**
- [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) — full phase details and decisions
- [v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md) — all 48 requirements with traceability
- [v1.0-MILESTONE-AUDIT.md](milestones/v1.0-MILESTONE-AUDIT.md) — pre-completion audit (gap ENGINE-03 closed in Phase 6.1)
