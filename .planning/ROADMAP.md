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
**Plans**: TBD

Plans:
- [ ] 02-01: Policy A split-adjustment engine and normalization pipeline
- [ ] 02-02: Returns computation and timestamp normalization

### Phase 3: Feature Engineering
**Goal**: Normalized return series are transformed into statistically rigorous features: residualized cross-correlations, relative strength, volatility, and standardized metrics
**Depends on**: Phase 2
**Requirements**: FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05, FEAT-06, FEAT-07
**Success Criteria** (what must be TRUE):
  1. Cross-correlation is computed across lags -5 to +5 on SPY-residualized returns with a minimum 60-day rolling window, and results are stored in SQLite
  2. Bonferroni-corrected significance testing rejects spurious correlations at the 0.0045 threshold across 11 lag offsets
  3. Relative Strength (leader minus follower cumulative return, rolling 10-session) is computed and stored for each pair
  4. Rolling volatility (20d), z-score standardized returns, and lagged returns (offsets +/-1 through +/-5) are computed and available in SQLite
**Plans**: TBD

Plans:
- [ ] 03-01: SPY residualization and rolling cross-correlation module
- [ ] 03-02: Relative strength, volatility, z-scores, and lagged returns

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
**Plans**: TBD

Plans:
- [ ] 04-01: Optimal lag detection and RSI-v2 stability score engine
- [ ] 04-02: Regime classification, distribution detection, and signal generation

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
**Plans**: TBD

Plans:
- [ ] 05-01: Paper trading engine (auto-execute, manual trades, position tracking, P&L)
- [ ] 05-02: Signal Dashboard panel (UI-01) and Paper Trading panel (UI-04)

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
| 1. Data Ingestion Pipeline | 0/3 | Not started | - |
| 2. Normalization & Returns | 0/2 | Not started | - |
| 3. Feature Engineering | 0/2 | Not started | - |
| 4. Lead-Lag Engine, Regime & Signals | 0/2 | Not started | - |
| 5. Paper Trading Simulation | 0/2 | Not started | - |
| 6. Backtest & Visualization | 0/2 | Not started | - |
