# Milestones

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
