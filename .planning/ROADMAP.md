# Roadmap: Lead-Lag Quant

## Overview

This roadmap delivers a local Gradio-based quantitative analytics application that ingests unadjusted equity data from Polygon.io, applies deterministic split-adjustment (Policy A), computes rolling cross-correlation lead-lag signals for user-seeded ticker pairs, generates full position specs with strict confidence thresholds, and validates signal quality through paper trading simulation and stored-data backtesting. The six phases follow the pipeline's strict dependency chain: each phase produces the data the next phase consumes, and each phase delivers its corresponding Gradio UI panel so progress is immediately observable.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Data Ingestion Pipeline** - Project scaffolding, Polygon.io client, raw data to SQLite, pair management UI
- [ ] **Phase 2: Normalization & Returns** - Policy A split-adjustment, returns computation, adjustment policy propagation
- [ ] **Phase 3: Feature Engineering** - Rolling features, SPY residualization, cross-correlation, relative strength
- [ ] **Phase 4: Lead-Lag Engine, Regime & Signals** - Stability scoring, regime classification, signal generation with full position specs
- [ ] **Phase 5: Paper Trading Simulation** - Simulated trade execution, position tracking, P&L, signal dashboard and trading panels
- [x] **Phase 5.1: API Security & Data Integrity Fixes** (INSERTED) - Free-tier enforcement in FastAPI, missing DB commits, soft-delete signal filtering, concurrent execution guard, input validation, error handling
- [ ] **Phase 6: Backtest & Visualization** - Stored-data backtesting, lead-lag charts, regime state panel, backtest results panel

## Phase Details

### Phase 1: Data Ingestion Pipeline
**Goal**: User can add ticker pairs in the app and fetch complete, deduplicated raw market data from Polygon.io into SQLite
**Depends on**: Nothing (first phase)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06, INGEST-07, INGEST-08, INGEST-09, INGEST-10, UI-06
**Success Criteria** (what must be TRUE):
  1. User can type a leader ticker and follower ticker into the Gradio UI, system validates both against Polygon, and the pair is saved to SQLite
  2. User can trigger data fetch for a pair and see unadjusted aggregate bars, split records, and dividend records arrive in SQLite with full raw JSON preserved
  3. SPY data is automatically fetched alongside any pair fetch without user intervention
  4. Re-running ingestion for the same date range produces no duplicate records in SQLite
  5. Polygon API calls handle pagination, rate limiting, and 429 retries transparently -- user sees completed fetch, not HTTP errors
**Plans:** 3 plans

Plans:
- [ ] 01-01-PLAN.md -- Project scaffolding, SQLite schema, shared utilities (config, logging, date helpers)
- [ ] 01-02-PLAN.md -- Polygon.io REST client (pagination, rate limiter, backoff) and ingestion module
- [ ] 01-03-PLAN.md -- Gradio app shell with pair management panel (UI-06)

### Phase 2: Normalization & Returns
**Goal**: Raw ingested data is transformed into split-adjusted bars and policy-tagged return series that all downstream computation can trust
**Depends on**: Phase 1
**Requirements**: NORM-01, NORM-02, NORM-03, NORM-04, NORM-05, NORM-06
**Success Criteria** (what must be TRUE):
  1. Running normalization on ingested data produces adjusted bars where prices reflect cumulative split ratios and dividends are stored separately, never applied to prices
  2. Every normalized bar, return, and signal record carries `adjustment_policy_id = "policy_a"` -- verified by querying SQLite
  3. Returns (1d, 5d, 10d, 20d, 60d) are computed exclusively from `adj_close` and stored in SQLite
  4. All timestamps are UTC datetimes with NYSE trading day assignment; no raw Unix milliseconds leak into normalized tables
  5. Split records include `fetched_at` timestamp enabling future point-in-time backtest isolation
**Plans:** 2 plans

Plans:
- [ ] 02-01-PLAN.md -- Schema extension (4 new tables), normalization module (split adjuster, bar normalizer, dividend storer, timestamp utils, orchestrator), tests
- [ ] 02-02-PLAN.md -- Returns computation (multi-period pct_change from adj_close), Normalize tab in Gradio UI

### Phase 3: Feature Engineering
**Goal**: Normalized return series are transformed into statistically rigorous features: residualized cross-correlations, relative strength, volatility, and standardized metrics
**Depends on**: Phase 2
**Requirements**: FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05, FEAT-06, FEAT-07
**Success Criteria** (what must be TRUE):
  1. Cross-correlation is computed across lags -5 to +5 on SPY-residualized returns with a minimum 60-day rolling window, and results are stored in SQLite
  2. Bonferroni-corrected significance testing rejects spurious correlations at the 0.0045 threshold across 11 lag offsets
  3. Relative Strength (leader minus follower cumulative return, rolling 10-session) is computed and stored for each pair
  4. Rolling volatility (20d), z-score standardized returns, and lagged returns (offsets +/-1 through +/-5) are computed and available in SQLite
**Plans:** 2 plans

Plans:
- [ ] 03-01-PLAN.md -- Add scipy/statsmodels, extend SQLite schema with 5 feature tables, SPY residualization and rolling cross-correlation with Bonferroni (FEAT-01, FEAT-02, FEAT-03)
- [ ] 03-02-PLAN.md -- Relative strength, volatility, z-scores, lagged returns, and pipeline orchestrator (FEAT-04, FEAT-05, FEAT-06, FEAT-07)

### Phase 4: Lead-Lag Engine, Regime & Signals
**Goal**: Features are consumed to detect statistically stable lead-lag relationships, classify market regime, and generate full position specs that meet strict confidence thresholds
**Depends on**: Phase 3
**Requirements**: ENGINE-01, ENGINE-02, ENGINE-03, ENGINE-04, REGIME-01, REGIME-02, SIGNAL-01, SIGNAL-02
**Success Criteria** (what must be TRUE):
  1. System identifies the optimal lag for a pair as the offset with maximum stable cross-correlation, and computes a stability_score (0-100) incorporating lag persistence, regime stability, rolling confirmation, walk-forward OOS validation, and lag drift penalty
  2. Regime state (Bull / Base / Bear / Failure) is classified using hard rules (MA structure, RS thresholds, ATR expansion/compression) and distribution events are flagged (volume spikes > 150% of 30d avg, VWAP rejection streaks >= 3)
  3. Signals are generated ONLY when stability_score > 70 AND correlation_strength > 0.65 -- no exceptions, no overrides
  4. Each qualifying signal produces a complete position spec: entry condition (date + direction), expected target (historical mean return during lag window), invalidation rule (leader reversal threshold), and sizing tier (full/half/quarter)
  5. Signals are stored immutably in SQLite with full explainability payload and directed flow map entry (A leads B)
**Plans:** 2 plans

Plans:
- [x] 04-01-PLAN.md -- leadlag_engine package: SQLite schema (4 new tables), optimal lag detector (ENGINE-01), RSI-v2 stability scorer (ENGINE-02) with tests
- [x] 04-02-PLAN.md -- Regime classifier (REGIME-01), distribution detector (REGIME-02), signal generator with hard gate (ENGINE-03, SIGNAL-01/02), pipeline orchestrator

### Phase 5: Paper Trading Simulation
**Goal**: Users can validate signal quality with simulated trades -- auto-executed from signals or manually entered -- with live-ish price tracking and full P&L accounting
**Depends on**: Phase 4
**Requirements**: TRADE-01, TRADE-02, TRADE-03, TRADE-04, TRADE-05, TRADE-06, TRADE-07, TRADE-08, UI-01, UI-04
**Success Criteria** (what must be TRUE):
  1. User can set starting paper capital and see it reflected in the portfolio; system auto-executes simulated trades when qualifying signals fire (with auto-execute toggle in the signal dashboard)
  2. User can manually enter Buy or Sell for any ticker with a custom share quantity at any time via the Gradio paper trading panel
  3. Open positions display entry price, current price (15-min delayed via Polygon snapshot), and unrealized P&L, with automatic refresh during market hours
  4. Closed positions record realized P&L in SQLite; full trade history (all opens and closes with timestamps and P&L) is visible in the UI
  5. Positions are flagged for exit in the UI when the leader reversal exceeds the signal's invalidation threshold
**Plans:** 2 plans

Plans:
- [x] 05-01-PLAN.md -- Paper trading engine: SQLite schema (3 tables), trading engine (set capital, open/close positions, auto-execute), Polygon price poller with market hours guard, tests
- [x] 05-02-PLAN.md -- Signal Dashboard tab (UI-01) and Paper Trading tab (UI-04) integrated into existing Gradio app with gr.Timer price refresh

### Phase 5.1: API Security & Data Integrity Fixes (INSERTED)
**Goal**: All critical and high-priority bugs from the API/frontend code review are fixed — free-tier pair limits enforced in FastAPI, database writes are committed atomically, soft-deleted pairs are filtered from signals, concurrent trade execution is serialized, and API inputs are validated with proper error responses
**Depends on**: Phase 5
**Requirements**: BUGFIX-01, BUGFIX-02, BUGFIX-03, BUGFIX-04, BUGFIX-05, BUGFIX-06, BUGFIX-07, BUGFIX-08
**Success Criteria** (what must be TRUE):
  1. A FREE-tier user cannot exceed 5 active pairs via the FastAPI endpoint — the limit is enforced server-side in api/routes/pairs.py, not only in the Gradio UI
  2. Pair soft-delete via the FastAPI DELETE endpoint commits to SQLite — pairs removed via API are visible as inactive immediately on next read
  3. Signals displayed in the Signal Dashboard and returned by the API never include signals for soft-deleted (is_active=0) pairs
  4. Signals from a deactivation period are not auto-executed when a pair is reactivated — only signals generated after reactivation are eligible
  5. Concurrent buy/sell operations cannot double-spend cash — signal execution uses a database-level exclusive lock or application-level mutex
  6. POST /api/trading/buy and /api/trading/sell reject shares <= 0 and price <= 0 with a 422 validation error
  7. All analytics endpoints (stats, risk, equity) return a structured JSON error response instead of a raw 500 traceback when an exception occurs
  8. broadcast_sync() delivers WebSocket messages reliably from background threads using run_coroutine_threadsafe instead of create_task
**Plans:** 3/4 plans executed

**Architecture decision:** The FastAPI backend (api/) + React/Vite frontend (frontend/) is the production stack. The Gradio UI (ui/) is being removed in Plan 05.1-04. Plans 05.1-01 through 05.1-03 fix only FastAPI and shared data-layer code — no Gradio files are touched.

Plans:
- [x] 05.1-01-PLAN.md -- Free-tier limit (BUGFIX-01), commit verify (BUGFIX-02), input validation (BUGFIX-06), analytics error handling (BUGFIX-07)
- [x] 05.1-02-PLAN.md -- Soft-delete signal filtering in FastAPI/shared layer (BUGFIX-03), reactivated_at schema + API reactivation guard (BUGFIX-04), concurrent execution mutex (BUGFIX-05)
- [x] 05.1-03-PLAN.md -- WebSocket broadcast reliability via run_coroutine_threadsafe (BUGFIX-08)
- [x] 05.1-04-PLAN.md -- Remove Gradio UI (delete ui/, remove gradio dep, repurpose main.py to launch FastAPI via uvicorn)

### Phase 6: Backtest & Visualization
**Goal**: Users can validate historical signal quality through stored-data backtesting and explore lead-lag relationships, regime state, and backtest results through dedicated visualization panels
**Depends on**: Phase 4 (backtest needs signals and features; visualization needs all upstream data)
**Requirements**: BACKTEST-01, BACKTEST-02, BACKTEST-03, UI-02, UI-03, UI-05
**Success Criteria** (what must be TRUE):
  1. Backtest runs exclusively from SQLite stored data -- never calls Polygon API -- and filters split records to `fetched_at <= backtest_date` to prevent look-ahead bias
  2. Backtest produces hit rate, mean return per trade, annualized Sharpe ratio, and maximum drawdown for a user-selected pair and date range, displayed in the Backtest Results panel (UI-05)
  3. Lead-Lag Charts panel (UI-02) displays cross-correlation heatmap across lags and rolling optimal correlation over time for a selected pair
  4. Regime State panel (UI-03) shows current Bull/Base/Bear/Failure classification with all indicator values (RS, MA position, ATR, volume) that produced the classification
**Plans**: TBD

Plans:
- [ ] 06-01: Backtest module (SQLite-only reads, look-ahead bias prevention, performance metrics)
- [ ] 06-02: Lead-Lag Charts panel (UI-02), Regime State panel (UI-03), and Backtest Results panel (UI-05)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 --> 2 --> 3 --> 4 --> 5 --> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Ingestion Pipeline | 3/3 | Complete | 2026-02-18 |
| 2. Normalization & Returns | 2/2 | Complete | 2026-02-18 |
| 3. Feature Engineering | 2/2 | Complete | 2026-02-18 |
| 4. Lead-Lag Engine, Regime & Signals | 2/2 | Complete | 2026-02-18 |
| 5. Paper Trading Simulation | 2/2 | Complete | 2026-02-19 |
| 5.1. API Security & Data Integrity Fixes | 4/4 | Complete | 2026-03-21 |
| 6. Backtest & Visualization | 0/2 | Not started | - |
