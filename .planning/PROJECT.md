# Lead-Lag Quant

## What This Is

A serverless AWS quantitative analytics platform for personal trading that detects statistically stable lead-lag relationships between equities and generates full actionable position specs. The system ingests unadjusted price data from Polygon.io/Massive, applies deterministic split-adjustment (Policy A), computes rolling cross-correlation and relative strength metrics, classifies regime state using hard quant rules, and exposes signals via API. MVP targets daily and swing timeframes; intraday (5-min) is Phase 2.

## Core Value

Any seeded equity pair should produce a complete, reproducible, auditable position spec — entry condition, expected target, invalidation rule, and sizing tier — backed by statistically validated lead-lag relationships and strict confidence thresholds.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Ingest unadjusted aggregate bars from Polygon.io/Massive and store full raw JSON in S3 (system of record)
- [ ] Pull corporate actions (splits, dividends) from Massive reference endpoints
- [ ] Apply Adjustment Policy A: split-adjust prices only; dividends stored separately, never baked into returns
- [ ] Normalize to canonical internal tables: bars_raw_massive, corporate_actions_splits, corporate_actions_dividends, normalized_bars, adjusted_bars_policy_a
- [ ] Compute returns_policy_a from adj_close exclusively; all downstream features consume this series
- [ ] Compute rolling features: returns (5d/10d/20d/60d), lagged returns (±1–5 bars), rolling volatility, z-score standardized returns, rolling correlation, cross-correlation across lags
- [ ] Compute Relative Strength (RS) — leader vs follower return differential, rolling 10-session
- [ ] Detect statistically significant lead-lag relationships for user-defined (seeded) equity pairs
- [ ] Compute stability_score (RSI-v2): lag persistence + regime stability + rolling confirmation + out-of-sample validation + lag drift penalty → 0–100 score
- [ ] Classify regime state: Bull / Base / Bear / Failure using hard quant rules (MA structure, RS thresholds, ATR regime, volume/VWAP signals)
- [ ] Apply strict signal thresholds: stability_score > 70, correlation_strength > 0.65 before surfacing any signal
- [ ] Generate full position spec: entry condition (date/price), expected target (historical mean return during lag window), invalidation rule (leader reversal threshold), sizing tier (weighted by stability_score)
- [ ] Detect distribution signals: down days with volume > 150% of 30-day average, VWAP rejection streaks ≥ 3 sessions
- [ ] Expose signals via API Gateway with full explainability payload (lag, window, correlation, stability, regime, adjustment policy)
- [ ] Construct directed flow map (adjacency matrix): A→B if A statistically leads B
- [ ] Backtest module: consumes normalized stored data only, never re-queries Massive; evaluates hit rate, mean return, Sharpe ratio, stability persistence
- [ ] Terraform IaC for core storage: S3 buckets and DynamoDB tables; Lambda deployed via script
- [ ] Modular Python project structure per spec (/ingestion_massive, /normalization, /features, /leadlag_engine, /signals, /api, /utils, /tests)
- [ ] Versioned parsers with adjustment_policy_id propagation throughout the pipeline

### Out of Scope

- Intraday / 5-minute variant — Phase 2, not MVP
- Sentiment data (options skew, social/news tone) — v2
- All-pairs exhaustive computation — pairs are seeded by user, not auto-discovered
- OAuth / multi-user auth — personal use, single-user API
- Mobile interface — API-only for MVP
- Real-time streaming — daily batch Lambda for MVP

## Context

- **Data provider:** Polygon.io/Massive — unadjusted aggregate bars + /v3/reference/splits + /v3/reference/dividends + /v3/reference/tickers
- **Primary validated pair:** CoreWeave (CRWV) / Nvidia (NVDA) — CoreWeave lags Nvidia momentum turns by several sessions; used as the MVP pipeline validation case
- **Regime rules (from CoreWeave framework):** Bullish RS > +5% for 10 sessions; Bearish RS < -7% for 5 sessions; ATR expansion > 130% of 20-day avg; distribution = down day volume > 150% of 30-day avg or VWAP rejection × 3
- **Ticker universe:** < 100 tickers; pairs are user-seeded (not computed exhaustively)
- **AWS accounts and Massive API key:** both active and ready
- **Backtest integrity rules:** no look-ahead bias, no future split leakage, returns_policy_a exclusively, backtest never re-queries Massive

## Constraints

- **Tech stack:** Python (modular), AWS serverless (Lambda/S3/DynamoDB/API Gateway/Athena), Terraform for storage IaC only
- **Adjustment policy:** Policy A is canonical default — split-adjust only, dividends never in returns; policy ID propagated through all tables and signals
- **Signal quality:** Hard minimums — stability_score > 70, correlation_strength > 0.65; no exceptions
- **Reproducibility:** Every signal must be reproducible from stored S3 data alone; raw JSON is the system of record
- **Execution model:** Daily batch Lambda for MVP; no real-time or streaming infrastructure

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Unadjusted ingestion + internal Policy A adjustment | Reproducibility, audit trail, schema evolution protection | — Pending |
| Seeded pairs (not exhaustive) | Avoids O(n²) pair explosion on < 100 ticker universe; user controls which relationships to validate | — Pending |
| Terraform for S3/DynamoDB only | Balances IaC discipline for stateful resources with MVP deployment speed; Lambda via script | — Pending |
| Price/volume only (no sentiment) | Keeps MVP scope clean; sentiment inputs (options skew, news tone) deferred to v2 | — Pending |
| Strict thresholds (stability > 70, correlation > 0.65) | Personal trading use — prefer fewer high-confidence signals over high volume | — Pending |
| Full position spec output (entry + target + invalidation + sizing) | Actionable signals for discretionary trading; system produces a complete trade plan, not just a direction | — Pending |

---
*Last updated: 2026-02-18 after initialization*
