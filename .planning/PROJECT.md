# Lead-Lag Quant

## What This Is

A local quantitative analytics application that ingests unadjusted equity data from Polygon.io, applies deterministic split-adjustment (Policy A), computes rolling cross-correlation lead-lag signals for user-seeded ticker pairs, generates full actionable position specs with strict confidence thresholds, validates signal quality through paper trading simulation and stored-data backtesting, and exposes a FastAPI backend with a React/Vite frontend dashboard.

## Core Value

Any seeded equity pair produces a complete, reproducible, auditable position spec — entry condition, expected target, invalidation rule, and sizing tier — backed by statistically validated lead-lag relationships and strict confidence thresholds.

## Requirements

### Validated (v1.0)

- ✓ Ingest unadjusted aggregate bars from Polygon.io with pagination, rate limiting, and idempotent re-runs — v1.0
- ✓ Apply Policy A split-adjustment; dividends stored separately, never baked into returns — v1.0
- ✓ Compute rolling features: returns (1d/5d/10d/20d/60d), lagged returns (±1–5 bars), volatility, z-scores, cross-correlation, RS — v1.0
- ✓ Bonferroni-corrected significance testing across 11 lag offsets — v1.0
- ✓ RSI-v2 stability score: lag persistence + regime stability + rolling confirmation + OOS validation + lag drift penalty → 0–100 — v1.0
- ✓ Regime classification: Bull/Base/Bear/Failure via hard quant rules (MA structure, RS thresholds, ATR, volume/VWAP) — v1.0
- ✓ Hard signal gate: stability_score > 70 AND correlation_strength > 0.65; no exceptions — v1.0
- ✓ Full position spec per signal: entry condition, expected target, invalidation rule, sizing tier — v1.0
- ✓ Paper trading simulation with auto-execution, 15-min price polling, P&L tracking — v1.0
- ✓ FastAPI backend with WebSocket broadcasts, auth, input validation, concurrent execution guard — v1.0
- ✓ Backtest engine: stored-data only, no look-ahead bias, hit rate / Sharpe / drawdown metrics — v1.0
- ✓ React/Vite frontend: Backtest, Lead-Lag Charts, Regime State, Signal Dashboard, Trading panels — v1.0

### Active

(None yet — planning v1.1)

### Out of Scope

| Feature | Reason |
|---------|--------|
| Real broker integration (Alpaca, TD Ameritrade, etc.) | Regulatory risk; paper trading validates the signal logic first |
| Automated stop-loss execution | Flagged only; human makes the final exit decision |
| Intraday 5-minute bars | Different architecture and signal characteristics; deferred to v2 |
| Sentiment / options skew data | Separate data pipeline; v2+ after core price/volume lead-lag is validated |
| All-pairs exhaustive discovery | O(n²) explosion + multiple testing nightmare; pairs are always user-seeded |
| ML-based signals | Violates explainability requirement; insufficient training data at this scale |
| Dynamic threshold auto-adjustment | Introduces hidden state; makes signals non-reproducible |
| AWS Lambda / S3 / DynamoDB / Terraform | Descoped from v1.0 — local SQLite is sufficient for MVP validation |
| Gradio UI | Removed in Phase 5.1-04; FastAPI + React is the production stack |

## Context

- **Data provider:** Polygon.io — unadjusted aggregate bars + /v3/reference/splits + /v3/reference/dividends
- **Primary validated pair:** CoreWeave (CRWV) / Nvidia (NVDA) — CoreWeave lags Nvidia momentum turns by several sessions
- **Tech stack:** Python (FastAPI, SQLite, scipy, statsmodels, pandas), React/Vite/TypeScript
- **Regime rules:** Bullish RS > +5% for 10 sessions; Bearish RS < -7% for 5 sessions; ATR expansion > 130% of 20-day avg; distribution = down day volume > 150% 30-day avg or VWAP rejection × 3
- **Current state:** v1.0 shipped 2026-03-21 — 48/48 requirements satisfied, 18 plans, ~10,500 Python LOC + ~2,500 TypeScript LOC
- **Known issues:** 2 pre-existing test failures in test_engine_detector.py (insufficient days / null correlation edge cases) — documented, not blocking

## Constraints

- **Tech stack:** Python + FastAPI + SQLite backend; React/Vite frontend
- **Adjustment policy:** Policy A is canonical default — split-adjust only, dividends never in returns; policy ID propagated through all tables and signals
- **Signal quality:** Hard minimums — stability_score > 70, correlation_strength > 0.65; no exceptions
- **Reproducibility:** Every signal must be reproducible from stored SQLite data alone
- **Execution model:** Local application; no cloud infrastructure in v1.0

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Unadjusted ingestion + internal Policy A adjustment | Reproducibility, audit trail, schema evolution protection | ✓ Good — clean separation maintained throughout |
| Seeded pairs (not exhaustive) | Avoids O(n²) pair explosion on < 100 ticker universe | ✓ Good — manageable scope |
| SQLite for all storage (not AWS) | v1.0 is local MVP; AWS deferred to v2 | ✓ Good — dramatically simplified deployment |
| FastAPI + React (not Gradio) | Gradio removed in Phase 5.1 after frontend was built; FastAPI/React is production stack | ✓ Good — proper API/UI separation |
| Strict thresholds (stability > 70, correlation > 0.65) | Personal trading — prefer fewer high-confidence signals | ✓ Good — ENGINE-03 gap closed in Phase 6.1 |
| Average-cost basis for paper trading | Simpler than FIFO; appropriate for paper trading validation | ✓ Good |
| threading.Lock for auto-execute serialization | Prevent double-spend in concurrent signal execution | ✓ Good |
| reload=False in uvicorn.run | Background threads (PipelineScheduler, BackgroundPricePoller) incompatible with reload | ✓ Good — critical for stability |
| run_coroutine_threadsafe for WebSocket broadcast | Thread-safe cross-thread coroutine scheduling from background threads | ✓ Good |
| INNER JOIN ticker_pairs WHERE is_active=1 as standard signal query pattern | Soft-deleted pairs must never appear in signal results | ✓ Good — standard pattern enforced |

---
*Last updated: 2026-03-21 after v1.0 milestone*
