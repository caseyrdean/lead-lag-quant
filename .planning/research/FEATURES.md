# Feature Research

**Domain:** Serverless Quantitative Lead-Lag Equity Analytics Platform (Personal Trading)
**Researched:** 2026-02-18
**Confidence:** MEDIUM (training data only -- WebSearch/WebFetch unavailable; Polygon.io API knowledge from training data through May 2025 is well-established but should be verified against current docs before implementation)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that are non-negotiable for a functional personal lead-lag quant system. Without these, the platform produces unreliable signals or is simply unusable.

#### A. Data Ingestion & Polygon.io/Massive API Integration

| Feature | Why Expected | Complexity | MVP/Defer | Notes |
|---------|--------------|------------|-----------|-------|
| **Polygon.io REST client with retry + backoff** | API calls fail (rate limits, transient errors); without retry, ingestion is fragile | MEDIUM | MVP | Exponential backoff with jitter; respect 429 status and Retry-After header |
| **Cursor-based pagination (next_url)** | Polygon v3 endpoints return paginated results via `next_url` field; ignoring it means partial data | MEDIUM | MVP | Follow `next_url` until null; do NOT construct offsets manually -- Polygon controls cursor state |
| **Rate limiter (token bucket or leaky bucket)** | Polygon enforces per-minute and per-second limits by plan tier; exceeding = 429 errors and potential temp bans | MEDIUM | MVP | Basic plan: 5 req/min; Starter: unlimited/min but throttled; implement token bucket that respects plan tier |
| **Full raw JSON archival to S3** | System of record for reproducibility; re-processing from raw avoids re-querying Massive | LOW | MVP | Store with metadata: ingestion_timestamp, api_version, request_params, http_status |
| **Unadjusted aggregate bars ingestion** | Policy A requires unadjusted source data; adjusted=false parameter in /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to} | LOW | MVP | Always pass `adjusted=false`; verify response `adjusted` field matches |
| **Splits endpoint ingestion** | /v3/reference/splits -- required for Policy A split adjustment | LOW | MVP | Paginated via next_url; filter by ticker and date range |
| **Dividends endpoint ingestion** | /v3/reference/dividends -- stored for audit trail; never applied to returns per Policy A | LOW | MVP | Store but do not apply; mark with policy_id for future Policy B if needed |
| **Ticker metadata ingestion** | /v3/reference/tickers -- needed for market cap, sector, exchange, active status | LOW | MVP | Cache locally; refresh weekly or on-demand |
| **Timestamp normalization (Unix ms to UTC datetime)** | Polygon returns timestamps as Unix milliseconds in `t` field; inconsistent handling breaks time-series alignment | LOW | MVP | Normalize to UTC; store both raw Unix ms and ISO-8601; handle market timezone for session boundaries |
| **Idempotent ingestion (date-range deduplication)** | Re-running ingestion for overlapping date ranges must not create duplicate bars | MEDIUM | MVP | DynamoDB conditional writes or S3 key convention: `{ticker}/{date}/{timespan}.json` |
| **API key management** | Secure storage, rotation capability | LOW | MVP | AWS Secrets Manager or SSM Parameter Store; never in code/env vars |

#### B. Data Normalization & Adjustment

| Feature | Why Expected | Complexity | MVP/Defer | Notes |
|---------|--------------|------------|-----------|-------|
| **Split-adjustment engine (Policy A)** | Core data integrity requirement; unadjusted prices are meaningless for returns without split correction | HIGH | MVP | Apply cumulative split ratio retrospectively; handle reverse splits; propagate policy_id |
| **Canonical table schema** | bars_raw_massive, corporate_actions_splits, corporate_actions_dividends, normalized_bars, adjusted_bars_policy_a, returns_policy_a | MEDIUM | MVP | DynamoDB or Parquet-on-S3; schema must include adjustment_policy_id in every table |
| **Policy ID propagation** | Every derived value traces back to which adjustment policy produced it | LOW | MVP | String field "policy_a" on all computed tables; enables future policy variants without confusion |
| **Returns computation (adj_close only)** | returns_policy_a = (adj_close[t] - adj_close[t-1]) / adj_close[t-1]; must use adjusted series exclusively | LOW | MVP | Simple pct_change; compute 1d, 5d, 10d, 20d, 60d windows |
| **Corporate action effective date handling** | Splits have ex-date vs declaration date; must apply on correct date | MEDIUM | MVP | Use execution_date from Polygon; retrospective adjustment of all prior bars |

#### C. Signal Computation Engine

| Feature | Why Expected | Complexity | MVP/Defer | Notes |
|---------|--------------|------------|-----------|-------|
| **Rolling cross-correlation (Pearson)** | Core signal: measures strength of lead-lag at each lag offset | MEDIUM | MVP | Compute across lags -5 to +5; rolling window 20-60 bars; output correlation matrix per pair |
| **Optimal lag detection** | Identify which lag offset has maximum stable correlation | MEDIUM | MVP | Peak detection on cross-correlation curve; filter by significance threshold |
| **Relative Strength (RS) computation** | Leader-vs-follower return differential, rolling 10-session | LOW | MVP | RS = cumulative_return(leader, 10d) - cumulative_return(follower, 10d) |
| **Stability score (RSI-v2)** | Composite: lag persistence + regime stability + rolling confirmation + OOS validation + lag drift penalty | HIGH | MVP | 0-100 score; this is the key quality gate -- must be >70 to surface signal |
| **Regime classification** | Bull / Base / Bear / Failure using MA structure + RS thresholds + ATR + volume signals | HIGH | MVP | Hard rules from project spec; no ML, pure rule-based |
| **Distribution detection** | Down days with volume >150% of 30d avg, VWAP rejection streaks >=3 | MEDIUM | MVP | Requires VWAP computation or ingestion; volume analysis straightforward |
| **Strict threshold enforcement** | stability_score > 70, correlation_strength > 0.65 hard gates | LOW | MVP | Config-driven but defaults are non-negotiable |

#### D. Signal Output & API

| Feature | Why Expected | Complexity | MVP/Defer | Notes |
|---------|--------------|------------|-----------|-------|
| **Full position spec generation** | Entry condition, expected target, invalidation rule, sizing tier | HIGH | MVP | Historical mean return during lag window = target; leader reversal threshold = invalidation |
| **Signal explainability payload** | Every signal includes: lag, window, correlation, stability, regime, adjustment_policy | MEDIUM | MVP | JSON response with full derivation chain; critical for trust and debugging |
| **REST API (API Gateway + Lambda)** | Access signals programmatically | MEDIUM | MVP | GET /signals/{pair}, GET /signals/active, GET /pairs/{pair}/diagnostics |
| **Signal history storage** | Past signals stored for backtest validation and performance tracking | MEDIUM | MVP | DynamoDB or S3; immutable once generated |

#### E. Infrastructure & Operations

| Feature | Why Expected | Complexity | MVP/Defer | Notes |
|---------|--------------|------------|-----------|-------|
| **Terraform for S3/DynamoDB** | Stateful resources need IaC; prevents drift, enables teardown/rebuild | MEDIUM | MVP | Storage-only IaC per project spec; Lambda deployed via script |
| **Daily batch orchestration** | Scheduled Lambda (EventBridge cron) triggers daily pipeline | MEDIUM | MVP | Market-close + buffer (e.g., 6:30 PM ET); handles holidays/weekends |
| **Pipeline error handling & dead letter queue** | Failed ingestion/computation must not silently drop data | MEDIUM | MVP | SQS DLQ for failed Lambda invocations; CloudWatch alarms |
| **Logging with correlation IDs** | Trace a signal back through every computation step | LOW | MVP | Structured JSON logging; pair_id + run_date + step_name |

---

### Polygon.io/Massive API-Specific Requirements

This section consolidates all Polygon-specific integration concerns in one place. **Confidence: MEDIUM** -- based on well-established Polygon REST API patterns from training data; specific rate limits should be verified against current plan documentation before implementation.

#### API Endpoints Required

| Endpoint | Purpose | Pagination | Notes |
|----------|---------|------------|-------|
| `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}` | Aggregate bars (OHLCV) | `next_url` cursor (if result exceeds limit) | Pass `adjusted=false`, `sort=asc`, `limit=50000` (max) |
| `GET /v3/reference/splits` | Stock splits | `next_url` cursor | Filter by `ticker` and `execution_date` range; results ordered by execution_date |
| `GET /v3/reference/dividends` | Cash dividends | `next_url` cursor | Filter by `ticker` and `ex_dividend_date` range |
| `GET /v3/reference/tickers` | Ticker metadata | `next_url` cursor | Active status, market cap, sector, exchange |
| `GET /v3/reference/tickers/{ticker}` | Single ticker detail | No pagination | Useful for validation |

#### Pagination Handling

| Aspect | Requirement | Implementation |
|--------|-------------|----------------|
| **Mechanism** | Cursor-based via `next_url` field in response | Loop: fetch -> process -> if `next_url` exists, fetch `next_url` -> repeat until null |
| **Do NOT** | Construct pagination manually (no offset/page params) | Polygon controls cursor state; manually constructed URLs may skip or duplicate data |
| **Rate limit between pages** | Respect rate limits between paginated requests | Insert delay between paginated fetches; treat each page as a counted request |
| **Error on pagination** | Retry from last successful `next_url`, not from start | Store last successful `next_url` for resumability |
| **Empty results** | `results` array may be empty or absent for no-data ranges | Handle gracefully; distinguish "no data" from "error" |
| **Result count** | Response includes `resultsCount` or `count` field | Use for validation; compare against len(results) |

#### Rate Limiting

| Plan Tier | Rate Limit (training data -- verify) | Strategy |
|-----------|--------------------------------------|----------|
| **Basic (free)** | 5 API calls/minute | Aggressive throttling; batch date ranges to minimize calls |
| **Starter** | Unlimited calls/min but practical throttle ~100/min | Token bucket with configurable rate |
| **Developer** | Higher limits, websocket access | Less throttling needed |
| **Advanced/Business** | Highest limits | Minimal throttling |

| Rate Limit Feature | Requirement | Notes |
|--------------------|-------------|-------|
| **HTTP 429 handling** | Respect `Retry-After` header; exponential backoff | Never retry 429 immediately |
| **Token bucket rate limiter** | Pre-request throttle, not just post-429 reactive | Prevents hitting limits rather than recovering from them |
| **Plan-tier configuration** | Rate limit params in config, not hardcoded | Allows upgrading plan without code changes |
| **Concurrent request limiting** | Max parallel requests (suggest: 1 for Basic, 3-5 for Starter+) | Lambda concurrency + in-process semaphore |
| **Daily request budgeting** | Track daily API call count; alert at 80% of budget | For cost control on paid plans |

#### Timestamp & Data Normalization

| Aspect | Polygon Behavior | Required Handling |
|--------|-----------------|-------------------|
| **Timestamp format** | Unix milliseconds in `t` field | Convert to UTC datetime; store both raw and normalized |
| **Market hours** | Bars may include pre/post market depending on params | Default to regular market hours only (`adjusted=false` does not filter hours) |
| **Missing bars** | No bar returned for days with no trading (holidays, halts) | Do NOT interpolate; mark gaps; align pair data by date, not index |
| **VWAP field** | `vw` field = volume-weighted average price per bar | Use directly for VWAP rejection detection |
| **Volume field** | `v` field = trading volume | Integer; use for distribution detection |
| **Bar boundaries** | Aggregation boundaries depend on timespan | For `day` timespan: one bar per trading day; `from`/`to` are inclusive dates |

#### Metadata Capture

| Metadata | Where to Store | Why |
|----------|---------------|-----|
| `request_id` from response headers | S3 metadata on raw JSON | Polygon support debugging |
| `status` field in response | S3 metadata | Detect partial/degraded responses |
| `adjusted` field in response | Validate matches request | Catch API behavior changes |
| `queryCount` / `resultsCount` | S3 metadata | Validate completeness |
| Ingestion timestamp | S3 metadata + DynamoDB | Audit trail |
| API version (path-derived) | S3 metadata | Track which API version produced data |
| HTTP response headers | S3 metadata (selected) | Rate limit remaining, content type |

---

### Differentiators (Competitive Advantage)

Features that make this more than a correlation calculator. Not required for basic function, but create the value proposition.

| Feature | Value Proposition | Complexity | MVP/Defer | Notes |
|---------|-------------------|------------|-----------|-------|
| **Stability score (RSI-v2) composite metric** | Goes beyond raw correlation; measures persistence, regime stability, out-of-sample validity, and drift penalty in a single 0-100 score | HIGH | MVP (core differentiator) | This IS the product -- without it, signals are just correlations |
| **Full position spec (not just direction)** | Produces actionable trade plan: entry, target, invalidation, sizing -- not just "A leads B" | HIGH | MVP (core differentiator) | Sizing tier weighted by stability_score; invalidation from leader reversal threshold |
| **Regime-aware signal gating** | Signals are only valid within a regime context; Bull/Bear/Base changes invalidate prior signals | HIGH | MVP | Prevents trading stale correlations in changed market conditions |
| **Directed flow map (adjacency matrix)** | Visualizes which tickers lead which; reveals cluster structure in seeded universe | MEDIUM | Defer to v1.x | Requires enough pairs to be meaningful; nice for portfolio-level view |
| **Distribution detection overlay** | Volume + VWAP rejection signals warn of regime deterioration before RS flips | MEDIUM | MVP | Early warning system for active positions |
| **Backtest module (stored data only)** | Validates signal quality using historical data without re-querying Massive | HIGH | MVP | Hit rate, mean return, Sharpe, stability persistence; proves the system works |
| **Lag drift detection** | Detects when the optimal lag between a pair is shifting over time | MEDIUM | Defer to v1.x | Penalty factor in stability score; full drift tracking is v1.x |
| **Signal versioning & audit trail** | Every signal is immutable, versioned, traceable to source data + computation params | MEDIUM | MVP | Enables "why did the system say X on date Y?" forensics |
| **Multi-window correlation analysis** | Compute correlation across multiple rolling windows (20d, 40d, 60d) simultaneously | MEDIUM | MVP | Reveals whether lead-lag is persistent or window-dependent |
| **Out-of-sample validation in stability score** | Train on window A, validate on window B within the stability_score computation | HIGH | MVP | Prevents overfitting to specific lookback periods |

### Anti-Features (Explicitly NOT Building)

Features that seem appealing but create scope creep, complexity, or unreliable behavior for a personal trading system.

| Anti-Feature | Why Requested | Why Problematic | What to Do Instead |
|--------------|---------------|-----------------|-------------------|
| **All-pairs exhaustive discovery** | "Find all lead-lag relationships automatically" | O(n^2) pair explosion; most pairs are spurious; enormous compute cost on Lambda; statistical multiple-testing problem creates false positives | User-seeded pairs only; < 100 tickers means manageable pair count when curated |
| **Real-time / streaming WebSocket pipeline** | "Get signals as fast as possible" | Massive infrastructure complexity (WebSocket connection management, state, reconnection); daily/swing timeframe doesn't need sub-second data; Lambda cold starts make real-time unreliable | Daily batch Lambda at market close + buffer; intraday (5-min bars) is Phase 2 but still batch, not streaming |
| **ML-based signal generation** | "Use machine learning to find patterns" | Black-box signals violate explainability requirement; small ticker universe provides insufficient training data; overfitting risk extreme on financial time series | Rule-based regime classification and hard-coded thresholds; transparent, auditable, reproducible |
| **Multi-user / OAuth authentication** | "Share signals with others" | Auth infrastructure complexity; regulatory implications of distributing trading signals; personal system by definition | Single-user API key in API Gateway; no user management |
| **Mobile app or web dashboard** | "Nice UI for checking signals" | UI development is a separate project; premature optimization; API-first means any UI can be built later | API-only for MVP; consume via curl/Postman/custom script; dashboard is a separate future project |
| **Options / derivatives data integration** | "Options skew predicts equity moves" | Different data model, different API endpoints, different pricing considerations; massive scope expansion | Price/volume only for MVP; options skew as v2 sentiment layer |
| **Sentiment / news / social data** | "Add NLP sentiment signals" | Separate data pipeline, separate API providers, separate validation framework; does not strengthen core lead-lag thesis | Defer to v2; core system must prove value on price/volume alone first |
| **Automated order execution** | "Auto-trade the signals" | Regulatory risk, broker API complexity, error handling for real money, slippage modeling; personal system should produce specs for discretionary execution | Position specs are the output; human makes the final trading decision |
| **Historical data backfill beyond Polygon availability** | "Get data from before Polygon's coverage" | Multiple data sources create reconciliation nightmares; different adjustment methodologies; data quality issues | Use Polygon's available history only; if a ticker's history is short, that limits its statistical validity (which is correct behavior) |
| **Dynamic threshold adjustment** | "Let the system adapt thresholds based on market conditions" | Introduces hidden state that makes signals non-reproducible; threshold creep leads to lower quality signals over time | Hard thresholds (stability > 70, correlation > 0.65) are features, not bugs; if market conditions make signals rare, that's correct behavior |
| **Portfolio optimization / Kelly sizing** | "Optimize across all active signals" | Requires covariance estimation across pairs, which is a separate research problem; over-engineering for < 100 ticker personal system | Sizing tiers (small/medium/large) based on stability_score; discretionary allocation |

---

## Feature Dependencies

```
[Polygon API Client (retry, pagination, rate limit)]
    |
    v
[Raw JSON Archival to S3]
    |
    +---> [Splits Ingestion] --+
    |                          |
    +---> [Dividends Ingestion]+---> [Split-Adjustment Engine (Policy A)]
    |                          |         |
    +---> [Bars Ingestion]  ---+         v
    |                          [Adjusted Bars (Policy A)]
    v                                    |
[Ticker Metadata]                        v
                                 [Returns Computation (Policy A)]
                                         |
                    +--------------------+--------------------+
                    |                    |                    |
                    v                    v                    v
            [Rolling Features]   [Cross-Correlation]   [Relative Strength]
                    |                    |                    |
                    +--------------------+--------------------+
                                         |
                                         v
                                 [Optimal Lag Detection]
                                         |
                          +--------------+----------------+
                          |              |                |
                          v              v                v
                  [Regime Classification] [Distribution Detection] [Stability Score]
                          |              |                |
                          +--------------+----------------+
                                         |
                                         v
                                 [Signal Threshold Gate (>70 stability, >0.65 corr)]
                                         |
                                         v
                                 [Position Spec Generation]
                                         |
                          +--------------+--------------+
                          |                             |
                          v                             v
                  [REST API (signals)]          [Signal History Storage]
                          |                             |
                          v                             v
                  [Explainability Payload]       [Backtest Module]

    [Directed Flow Map] <--- requires multiple pairs with valid signals
    [Lag Drift Detection] <--- requires historical stability score series
```

### Dependency Notes

- **Polygon API Client requires nothing** -- it is the foundation layer; must be built first
- **Split-Adjustment Engine requires both raw bars AND splits data** -- cannot compute adjusted prices without both
- **Returns computation requires adjusted bars** -- returns_policy_a uses adj_close exclusively
- **Cross-correlation requires returns from BOTH tickers in a pair** -- pair-level computation
- **Stability score requires cross-correlation + regime + OOS validation** -- composite metric, depends on multiple upstream features
- **Position spec requires stability score + regime + lag detection** -- the terminal output depends on nearly everything upstream
- **Backtest module requires signal history + stored normalized data** -- retrospective evaluation; cannot exist without prior signal generation
- **Directed flow map requires multiple pairs** -- adjacency matrix only meaningful with >2 pairs; defer until pair count grows
- **Regime classification requires MA structure + RS + ATR + volume** -- multiple rolling features must be computed first

---

## MVP Definition

### Launch With (v1 -- Core Pipeline)

Minimum viable pipeline that produces one valid position spec for CRWV/NVDA.

- [ ] **Polygon API client with retry, pagination, rate limiting** -- cannot ingest data without it
- [ ] **Raw JSON archival to S3** -- system of record; everything downstream depends on this
- [ ] **Aggregate bars ingestion (unadjusted)** -- primary data source
- [ ] **Splits + dividends ingestion** -- required for Policy A adjustment
- [ ] **Split-adjustment engine (Policy A)** -- converts raw bars to adjusted bars
- [ ] **Returns computation (adj_close)** -- 1d/5d/10d/20d/60d from adjusted series
- [ ] **Rolling cross-correlation** -- core lead-lag signal across lag offsets -5 to +5
- [ ] **Relative Strength computation** -- leader vs follower differential
- [ ] **Optimal lag detection** -- which lag has max stable correlation
- [ ] **Stability score (RSI-v2)** -- composite quality metric (0-100)
- [ ] **Regime classification (Bull/Base/Bear/Failure)** -- context for signal validity
- [ ] **Distribution detection** -- volume + VWAP early warning
- [ ] **Signal threshold enforcement** -- hard gates at stability >70, correlation >0.65
- [ ] **Position spec generation** -- entry, target, invalidation, sizing tier
- [ ] **REST API with explainability payload** -- programmatic access to signals
- [ ] **Signal history storage** -- immutable record of generated signals
- [ ] **Daily batch orchestration** -- EventBridge cron triggers pipeline
- [ ] **Terraform for S3/DynamoDB** -- IaC for stateful resources
- [ ] **Backtest module** -- validates signal quality from stored data
- [ ] **Structured logging with correlation IDs** -- operational observability

### Add After Validation (v1.x)

Features to add once CRWV/NVDA pipeline is producing valid signals consistently.

- [ ] **Directed flow map (adjacency matrix)** -- add when 5+ pairs are active and producing signals
- [ ] **Lag drift detection & tracking** -- add when signal history spans 60+ trading days for a pair
- [ ] **Multi-pair dashboard / summary endpoint** -- add when pair count exceeds easy mental tracking (~5+)
- [ ] **Alerting (SNS/email on new signal or regime change)** -- add after daily pipeline proves reliable for 2+ weeks
- [ ] **Backtest performance reporting** -- structured hit rate, Sharpe, max drawdown per pair
- [ ] **Pipeline health dashboard** -- CloudWatch dashboard with ingestion success rate, Lambda duration, error counts
- [ ] **Pair onboarding automation** -- streamlined process to add new ticker pairs with validation

### Future Consideration (v2+)

Features to defer until the core lead-lag thesis is validated through live trading.

- [ ] **Intraday 5-minute bars** -- different data volume, different Lambda architecture, different signal characteristics
- [ ] **Sentiment layer (options skew, news tone)** -- separate data pipeline and validation framework
- [ ] **Cross-asset lead-lag (equity vs commodity, equity vs rates)** -- different data sources, different normalization
- [ ] **Web dashboard** -- separate frontend project; API-first means this can be built independently
- [ ] **Dynamic lookback window optimization** -- automatically finding optimal correlation window per pair
- [ ] **Regime transition probability modeling** -- Markov chain or similar for regime change prediction
- [ ] **Multi-timeframe confluence** -- combining daily and weekly signals for higher conviction

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority | Phase |
|---------|------------|---------------------|----------|-------|
| Polygon API client (retry/pagination/rate limit) | HIGH | MEDIUM | **P1** | 1 |
| Raw JSON archival to S3 | HIGH | LOW | **P1** | 1 |
| Bars + splits + dividends ingestion | HIGH | MEDIUM | **P1** | 1 |
| Split-adjustment engine (Policy A) | HIGH | HIGH | **P1** | 1 |
| Returns computation | HIGH | LOW | **P1** | 1 |
| Canonical table schema + policy ID propagation | HIGH | MEDIUM | **P1** | 1 |
| Timestamp normalization | HIGH | LOW | **P1** | 1 |
| Idempotent ingestion | HIGH | MEDIUM | **P1** | 1 |
| Rolling cross-correlation | HIGH | MEDIUM | **P1** | 2 |
| Relative Strength | HIGH | LOW | **P1** | 2 |
| Optimal lag detection | HIGH | MEDIUM | **P1** | 2 |
| Stability score (RSI-v2) | HIGH | HIGH | **P1** | 2 |
| Regime classification | HIGH | HIGH | **P1** | 2 |
| Distribution detection | HIGH | MEDIUM | **P1** | 2 |
| Signal threshold enforcement | HIGH | LOW | **P1** | 2 |
| Position spec generation | HIGH | HIGH | **P1** | 3 |
| REST API + explainability | HIGH | MEDIUM | **P1** | 3 |
| Signal history storage | HIGH | LOW | **P1** | 3 |
| Daily batch orchestration | HIGH | MEDIUM | **P1** | 3 |
| Backtest module | HIGH | HIGH | **P1** | 3 |
| Terraform IaC | MEDIUM | MEDIUM | **P1** | 1 |
| Structured logging | MEDIUM | LOW | **P1** | 1 |
| Directed flow map | MEDIUM | MEDIUM | **P2** | v1.x |
| Lag drift tracking | MEDIUM | MEDIUM | **P2** | v1.x |
| Alerting (SNS) | MEDIUM | LOW | **P2** | v1.x |
| Pipeline health dashboard | LOW | MEDIUM | **P2** | v1.x |
| Intraday 5-min bars | MEDIUM | HIGH | **P3** | v2 |
| Sentiment layer | LOW | HIGH | **P3** | v2 |
| Web dashboard | LOW | HIGH | **P3** | v2 |

**Priority key:**
- **P1:** Must have for launch -- the pipeline is broken without it
- **P2:** Should have; add once core pipeline validates with CRWV/NVDA
- **P3:** Nice to have; defer until lead-lag thesis is proven through live trading

---

## Competitor / Reference Feature Analysis

| Feature | QuantConnect | Zipline/Alphalens | Simple Correlation Script | Lead-Lag Quant (Our Approach) |
|---------|-------------|-------------------|---------------------------|-------------------------------|
| Data ingestion | Built-in multi-provider | Manual CSV/API | Manual API call | Dedicated Polygon client with full archival |
| Adjustment handling | Provider-adjusted (opaque) | Provider-adjusted | Usually adjusted data | Unadjusted + explicit Policy A (transparent) |
| Cross-correlation | User-implemented | Factor analysis (different paradigm) | Basic numpy.correlate | Rolling multi-lag with stability scoring |
| Regime classification | Not built-in | Not built-in | None | Hard-rule regime engine (Bull/Base/Bear/Failure) |
| Signal quality scoring | Sharpe/sortino post-hoc | IC/quantile-based | None | Stability score (RSI-v2) pre-signal gate |
| Position sizing | Kelly/equal weight | Not built-in | None | Stability-weighted tiers |
| Explainability | Backtest results | Factor tear sheets | None | Full derivation chain in every signal |
| Reproducibility | Depends on data snapshot | Depends on data snapshot | Not reproducible | S3 raw JSON = system of record; deterministic |
| Infrastructure | Cloud-hosted platform | Local Python | Local script | Serverless AWS (Lambda/S3/DynamoDB) |
| Target user | Algo traders building strategies | Quant researchers | Hobbyists | Personal discretionary trader with quant edge |

**Key differentiators vs. the field:**
1. **Transparent adjustment policy** -- most platforms use provider-adjusted data; you can never reproduce the adjustment. Policy A gives full control and audit trail.
2. **Pre-signal quality gate** -- stability_score filters before surfacing, not just Sharpe ratio after-the-fact.
3. **Full position spec** -- most quant tools output signals (long/short); this outputs a complete trade plan.
4. **Deterministic reproducibility** -- raw JSON in S3 means any signal can be re-derived from scratch.

---

## Polygon.io API Integration Complexity Assessment

This section maps the Polygon integration work into concrete engineering tasks with estimated effort.

| Task | Effort | Risk | Notes |
|------|--------|------|-------|
| Basic REST client (requests + auth) | 2-4 hours | Low | Standard HTTP client with API key header |
| Cursor pagination loop | 4-8 hours | Medium | Must handle: empty pages, malformed next_url, mid-pagination failures |
| Rate limiter (token bucket) | 4-8 hours | Medium | Must be configurable per plan tier; shared across Lambda invocations via DynamoDB or in-memory per invocation |
| Retry with exponential backoff + jitter | 2-4 hours | Low | Standard pattern; handle 429, 500, 502, 503, 504 |
| S3 archival with metadata | 2-4 hours | Low | Key convention, metadata headers, JSON serialization |
| Idempotent ingestion logic | 4-8 hours | Medium | DynamoDB conditional writes or S3 key existence checks |
| Timestamp normalization | 2-4 hours | Low | Unix ms to UTC; market session boundary handling |
| Multi-endpoint orchestration (bars + splits + dividends) | 4-8 hours | Medium | Sequencing, error handling per endpoint, partial success handling |
| Response validation | 2-4 hours | Low | Verify `adjusted=false`, check `resultsCount`, validate schema |
| **Total Polygon integration estimate** | **26-52 hours** | **Medium overall** | The pagination + rate limiting combination is where most complexity lives |

---

## Sources

- Polygon.io REST API documentation (training data, May 2025 -- **verify current docs before implementation**)
  - /v2/aggs/ endpoint for aggregate bars
  - /v3/reference/ endpoints for splits, dividends, tickers
  - Pagination via next_url cursor pattern
  - Rate limiting by plan tier
- Quantitative finance pipeline patterns (training data)
  - Cross-correlation for lead-lag detection
  - Split-adjustment methodologies
  - Regime classification approaches
- AWS serverless architecture patterns (training data)
  - Lambda + S3 + DynamoDB + API Gateway + EventBridge

**Confidence notes:**
- Polygon API structure (endpoints, pagination via next_url, timestamp format): **MEDIUM** -- well-established API that rarely changes fundamentally, but specific rate limits and field names should be verified against current documentation
- Quant pipeline features (cross-correlation, regime detection, stability scoring): **MEDIUM** -- based on established quantitative finance practices; the specific RSI-v2 composite metric is project-specific and custom-designed
- AWS serverless patterns: **HIGH** -- mature, well-documented, stable patterns
- Rate limit specific numbers by plan tier: **LOW** -- Polygon may have changed plan tiers and limits; verify before hardcoding

---
*Feature research for: Serverless Quantitative Lead-Lag Equity Analytics Platform*
*Researched: 2026-02-18*
