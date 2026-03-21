# Requirements: Lead-Lag Quant

**Defined:** 2026-02-18
**Core Value:** Any seeded equity pair produces a reproducible, auditable full position spec backed by statistically validated lead-lag relationships -- and a paper trading simulator to validate those signals against real prices before committing capital.

---

## v1 Requirements

### Data Ingestion

- [ ] **INGEST-01**: User can enter a ticker pair in the Gradio UI and trigger a data fetch from Polygon.io
- [ ] **INGEST-02**: System fetches unadjusted aggregate bars (`adjusted=false`) for all tickers in active pairs
- [ ] **INGEST-03**: System fetches split records via `/v3/reference/splits` for each ticker
- [ ] **INGEST-04**: System fetches dividend records via `/v3/reference/dividends` for each ticker (stored, never applied to returns)
- [ ] **INGEST-05**: All raw Polygon API responses stored to SQLite as JSON system of record with `retrieved_at`, `ticker`, `endpoint`, `request_params`
- [ ] **INGEST-06**: Re-running ingestion for an existing date range does not create duplicate records (idempotent)
- [ ] **INGEST-07**: Polygon client handles cursor-based pagination via `next_url` until exhausted
- [ ] **INGEST-08**: Polygon client implements token-bucket rate limiter configurable by plan tier
- [ ] **INGEST-09**: Polygon client retries on HTTP 429 with exponential backoff and jitter (max 5 retries)
- [ ] **INGEST-10**: System also fetches SPY aggregate bars automatically (required for residualization)

### Normalization

- [ ] **NORM-01**: System applies Adjustment Policy A: split-adjust OHLCV prices using cumulative split ratio from fetched split records
- [ ] **NORM-02**: Dividends are stored in their own table and never applied to price calculations under Policy A
- [ ] **NORM-03**: `adjustment_policy_id` field (value: `"policy_a"`) is stored on every normalized bar, return, and signal record
- [ ] **NORM-04**: `returns_policy_a` computed from `adj_close` exclusively (1d, 5d, 10d, 20d, 60d rolling)
- [ ] **NORM-05**: Split records stored with `fetched_at` timestamp to enable point-in-time backtest isolation
- [ ] **NORM-06**: Timestamps normalized from Polygon Unix milliseconds to UTC datetime; trading day assigned per NYSE calendar

### Feature Engineering

- [ ] **FEAT-01**: Rolling cross-correlation computed across lags -5 to +5 bars using `scipy.signal.correlate` on a minimum 60-day rolling window
- [ ] **FEAT-02**: Returns for both tickers residualized against SPY returns before cross-correlation computation
- [ ] **FEAT-03**: Bonferroni correction applied to significance testing across 11 lag offsets (threshold = 0.05/11 ≈ 0.0045)
- [ ] **FEAT-04**: Relative Strength (RS) computed as cumulative_return(leader, 10d) - cumulative_return(follower, 10d), rolling
- [ ] **FEAT-05**: Rolling volatility computed on 20-day window
- [ ] **FEAT-06**: Z-score standardized returns computed per ticker
- [ ] **FEAT-07**: Lagged returns computed at offsets ±1 through ±5 bars

### Lead-Lag Engine

- [ ] **ENGINE-01**: Optimal lag detected per pair as the lag offset with maximum stable cross-correlation
- [ ] **ENGINE-02**: RSI-v2 stability score computed as composite of: lag persistence consistency + regime stability + rolling window confirmation + walk-forward OOS validation (non-overlapping estimation/gap/validation windows) + lag drift penalty → scalar 0–100
- [ ] **ENGINE-03**: Hard threshold gate: signals only generated when stability_score > 70 AND correlation_strength > 0.65
- [ ] **ENGINE-04**: Signals stored immutably in SQLite with full explainability payload: optimal_lag, window_length, correlation_strength, stability_score, regime_state, adjustment_policy_id, generated_at

### Regime & Distribution

- [ ] **REGIME-01**: Regime classified as Bull / Base / Bear / Failure using hard rules: MA structure (price vs 21d and 50d MA), RS thresholds (Bull: RS > +5% for 10 sessions; Bear: RS < -7% for 5 sessions), ATR regime (expansion > 130% of 20d avg; compression < 80%)
- [ ] **REGIME-02**: Distribution detection: flags down days with volume > 150% of 30-day average AND VWAP rejection streaks ≥ 3 consecutive sessions

### Signal Generation

- [ ] **SIGNAL-01**: System generates full position spec for each qualifying signal: entry condition (date + direction), expected target (historical mean return during lag window), invalidation rule (leader reversal % threshold), sizing tier (full/half/quarter based on stability_score)
- [ ] **SIGNAL-02**: System generates directed flow map entry (A leads B notation) for each active pair

### Paper Trading Simulation

- [ ] **TRADE-01**: User can set starting paper capital amount in the app
- [ ] **TRADE-02**: System auto-executes simulated trades when a qualifying signal fires, sizing position per the signal's sizing tier
- [ ] **TRADE-03**: User can manually enter a Buy or Sell for any ticker with a custom share quantity at any time via Gradio UI
- [ ] **TRADE-04**: Open positions display entry price, current price (15-min delayed), and unrealized P&L per position, updated automatically
- [ ] **TRADE-05**: System polls Polygon snapshot endpoint every 15 minutes during market hours (9:30–16:00 ET) to refresh current prices
- [ ] **TRADE-06**: Realized P&L recorded and stored in SQLite when a position is closed
- [ ] **TRADE-07**: Position flagged for exit in UI when leader reversal exceeds the signal's invalidation threshold
- [ ] **TRADE-08**: Trade history (all opens and closes) stored in SQLite with timestamps and P&L

### Backtest

- [x] **BACKTEST-01**: Backtest module reads from SQLite stored data only — never calls Polygon API
- [x] **BACKTEST-02**: Backtest adjustment path filters split records to `fetched_at <= backtest_date` (no look-ahead bias)
- [x] **BACKTEST-03**: Backtest reports: hit rate, mean return per trade, annualized Sharpe ratio, maximum drawdown

### Gradio Application

- [ ] **UI-01**: Signal Dashboard panel — displays active signals with full position spec; includes auto-execute toggle for paper trading
- [x] **UI-02**: Lead-Lag Charts panel — cross-correlation heatmap across lags, rolling optimal correlation over time for selected pair
- [x] **UI-03**: Regime State panel — current Bull/Base/Bear/Failure classification with all indicator values (RS, MA position, ATR, volume) that produced the classification
- [ ] **UI-04**: Paper Trading panel — open positions table, total portfolio P&L, win rate, manual Buy/Sell inputs with ticker and quantity, closed trade history
- [x] **UI-05**: Backtest Results panel — hit rate, mean return, Sharpe, max drawdown for user-selected pair and date range
- [ ] **UI-06**: User can add a new ticker pair (leader + follower) via text inputs in the app; system validates tickers against Polygon before saving

---

## v2 Requirements

### AWS Deployment

- **AWS-01**: Modular Python codebase wrapped in AWS Lambda functions (fn-ingest, fn-normalize, fn-features, fn-engine, fn-api)
- **AWS-02**: S3 replaces local SQLite for raw JSON system of record and Parquet feature tables
- **AWS-03**: DynamoDB replaces SQLite signal store (PK: pair_id, SK: signal_date, TTL: 365 days)
- **AWS-04**: API Gateway exposes signal endpoints publicly
- **AWS-05**: Terraform IaC for S3 bucket, DynamoDB tables, IAM roles (one per Lambda, least-privilege)
- **AWS-06**: EventBridge Scheduler daily cron replaces local scheduler
- **AWS-07**: Docker container images for compute Lambdas (fn-normalize, fn-features, fn-engine)
- **AWS-08**: CloudWatch structured logging, alarms, and SQS DLQ for failed invocations

### Analytics

- **ANALYTICS-01**: Athena external tables over S3 Parquet for ad-hoc SQL analysis
- **ANALYTICS-02**: Directed flow map (adjacency matrix) endpoint once 5+ active pairs exist

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real broker integration (Alpaca, TD Ameritrade, etc.) | Regulatory risk; paper trading validates the signal logic first |
| Automated stop-loss execution | Flagged only; human makes the final exit decision |
| Intraday 5-minute bars | Different Lambda architecture and signal characteristics; deferred to v2 |
| Sentiment / options skew data | Separate data pipeline; v2+ after core price/volume lead-lag is validated |
| All-pairs exhaustive discovery | O(n^2) explosion + multiple testing nightmare; pairs are always user-seeded |
| ML-based signals | Violates explainability requirement; insufficient training data at this scale |
| Dynamic threshold auto-adjustment | Introduces hidden state; makes signals non-reproducible |
| Web dashboard (non-Gradio) | API-first in v2; UI is a separate project |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 1 | Pending |
| INGEST-02 | Phase 1 | Pending |
| INGEST-03 | Phase 1 | Pending |
| INGEST-04 | Phase 1 | Pending |
| INGEST-05 | Phase 1 | Pending |
| INGEST-06 | Phase 1 | Pending |
| INGEST-07 | Phase 1 | Pending |
| INGEST-08 | Phase 1 | Pending |
| INGEST-09 | Phase 1 | Pending |
| INGEST-10 | Phase 1 | Pending |
| NORM-01 | Phase 2 | Pending |
| NORM-02 | Phase 2 | Pending |
| NORM-03 | Phase 2 | Pending |
| NORM-04 | Phase 2 | Pending |
| NORM-05 | Phase 2 | Pending |
| NORM-06 | Phase 2 | Pending |
| FEAT-01 | Phase 3 | Pending |
| FEAT-02 | Phase 3 | Pending |
| FEAT-03 | Phase 3 | Pending |
| FEAT-04 | Phase 3 | Pending |
| FEAT-05 | Phase 3 | Pending |
| FEAT-06 | Phase 3 | Pending |
| FEAT-07 | Phase 3 | Pending |
| ENGINE-01 | Phase 4 | Pending |
| ENGINE-02 | Phase 4 | Pending |
| ENGINE-03 | Phase 4 | Pending |
| ENGINE-04 | Phase 4 | Pending |
| REGIME-01 | Phase 4 | Pending |
| REGIME-02 | Phase 4 | Pending |
| SIGNAL-01 | Phase 4 | Pending |
| SIGNAL-02 | Phase 4 | Pending |
| TRADE-01 | Phase 5 | Pending |
| TRADE-02 | Phase 5 | Pending |
| TRADE-03 | Phase 5 | Pending |
| TRADE-04 | Phase 5 | Pending |
| TRADE-05 | Phase 5 | Pending |
| TRADE-06 | Phase 5 | Pending |
| TRADE-07 | Phase 5 | Pending |
| TRADE-08 | Phase 5 | Pending |
| BACKTEST-01 | Phase 6 | Complete |
| BACKTEST-02 | Phase 6 | Complete |
| BACKTEST-03 | Phase 6 | Complete |
| UI-01 | Phase 5 | Pending |
| UI-02 | Phase 6 | Complete |
| UI-03 | Phase 6 | Complete |
| UI-04 | Phase 5 | Pending |
| UI-05 | Phase 6 | Complete |
| UI-06 | Phase 1 | Pending |

**Coverage:**
- v1 requirements: 48 total
- Mapped to phases: 48
- Unmapped: 0

---
*Requirements defined: 2026-02-18*
*Last updated: 2026-02-18 after roadmap creation*
