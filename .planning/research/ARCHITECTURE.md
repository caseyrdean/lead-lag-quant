# Architecture Research: Lead-Lag Quant

**Domain:** Serverless quantitative analytics pipeline (financial data)
**Researched:** 2026-02-18
**Confidence:** HIGH (verified against official AWS documentation)

## System Overview

```
+=====================================================================+
|                      SCHEDULING LAYER                                |
|  EventBridge Scheduler (daily cron)                                  |
|       |                                                              |
|       v                                                              |
+======================================================================+
|                      COMPUTE LAYER (Lambda)                          |
|  +-------------+  +---------------+  +-----------+  +-------------+  |
|  | Ingestion   |  | Normalization |  | Features  |  | Lead-Lag    |  |
|  | Lambda      |->| Lambda        |->| Lambda    |->| Engine      |  |
|  | (fn-ingest) |  | (fn-normalize)|  | (fn-feat) |  | Lambda      |  |
|  +------+------+  +-------+-------+  +-----+-----+  | (fn-engine) |  |
|         |                 |                |          +------+------+  |
|         v                 v                v                |          |
+======================================================================+
|                      STORAGE LAYER                                   |
|  +-------------------+  +-------------------+  +------------------+  |
|  | S3                |  | S3                |  | DynamoDB         |  |
|  | (raw JSON)        |  | (Parquet tables)  |  | (signal store)   |  |
|  | System of Record  |  | Queryable by      |  | Served via API   |  |
|  |                   |  | Athena            |  |                  |  |
|  +-------------------+  +-------------------+  +------------------+  |
+======================================================================+
|                      QUERY / API LAYER                               |
|  +-------------------+  +-------------------+                        |
|  | Athena            |  | API Gateway       |                        |
|  | (ad-hoc analysis) |  | + fn-api Lambda   |                        |
|  +-------------------+  +-------------------+                        |
+======================================================================+
|                      OBSERVABILITY LAYER                             |
|  +-------------------+  +-------------------+                        |
|  | CloudWatch Logs   |  | CloudWatch Alarms |                        |
|  | /aws/lambda/fn-*  |  | (error rate,      |                        |
|  |                   |  |  duration, DLQ)    |                        |
|  +-------------------+  +-------------------+                        |
+======================================================================+
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| **EventBridge Scheduler** | Triggers daily batch pipeline at configured time (e.g., 22:00 UTC, after US market close + data availability lag) | fn-ingest (invokes) |
| **fn-ingest** | Calls Polygon.io/Massive API for unadjusted bars, splits, dividends; writes raw JSON to S3 | Polygon.io API (reads), S3 raw/ (writes) |
| **fn-normalize** | Reads raw JSON from S3, validates schema, applies Policy A split-adjustment, writes normalized Parquet tables | S3 raw/ (reads), S3 normalized/ and S3 adjusted/ (writes) |
| **fn-features** | Reads adjusted bars, computes rolling features (returns, volatility, z-scores, correlations, RS) | S3 adjusted/ (reads), S3 features/ (writes) |
| **fn-engine** | Reads features, computes lead-lag relationships, stability scores, regime classification, generates position specs | S3 features/ (reads), DynamoDB signals (writes) |
| **fn-api** | Reads signals from DynamoDB, returns full explainability payload | DynamoDB signals (reads), API Gateway (serves) |
| **Athena** | Ad-hoc analytical queries against all S3 Parquet tables; not in the hot path | S3 normalized/, adjusted/, features/ (reads) |
| **CloudWatch** | Collects logs from all Lambda functions, surfaces alarms on failures | All Lambda functions (receives logs) |

## Recommended Project Structure

```
lead-lag-quant/
+-- terraform/                  # IaC for stateful resources
|   +-- main.tf                 # Provider, backend config
|   +-- s3.tf                   # S3 buckets, lifecycle rules
|   +-- dynamodb.tf             # DynamoDB tables, GSIs, TTL
|   +-- iam.tf                  # IAM roles and policies per Lambda
|   +-- eventbridge.tf          # Scheduled rules
|   +-- outputs.tf              # ARNs, bucket names for scripts
|   +-- variables.tf            # Environment, region, config
|   +-- cloudwatch.tf           # Alarms, dashboards
|   +-- api_gateway.tf          # REST API definition
|   +-- athena.tf               # Workgroup, named queries
|
+-- src/
|   +-- ingestion_massive/      # fn-ingest handler + Polygon client
|   |   +-- handler.py          # Lambda entry point
|   |   +-- polygon_client.py   # Massive/Polygon API wrapper
|   |   +-- schemas.py          # Raw data validation schemas
|   |
|   +-- normalization/          # fn-normalize handler + Policy A logic
|   |   +-- handler.py          # Lambda entry point
|   |   +-- policy_a.py         # Split-adjustment logic
|   |   +-- parsers.py          # Raw JSON -> canonical schema
|   |   +-- schemas.py          # Normalized table schemas
|   |
|   +-- features/               # fn-features handler + rolling computations
|   |   +-- handler.py          # Lambda entry point
|   |   +-- rolling.py          # Returns, vol, z-score calculations
|   |   +-- correlation.py      # Cross-correlation, RS computation
|   |   +-- schemas.py          # Feature table schemas
|   |
|   +-- leadlag_engine/         # fn-engine handler + signal generation
|   |   +-- handler.py          # Lambda entry point
|   |   +-- detector.py         # Lead-lag relationship detection
|   |   +-- stability.py        # stability_score (RSI-v2) computation
|   |   +-- regime.py           # Bull/Base/Bear/Failure classification
|   |   +-- position_spec.py    # Entry/target/invalidation/sizing generation
|   |   +-- flow_map.py         # Directed adjacency matrix construction
|   |
|   +-- signals/                # Signal data models and thresholds
|   |   +-- models.py           # Signal dataclass/schema
|   |   +-- thresholds.py       # Minimum stability, correlation gates
|   |
|   +-- api/                    # fn-api handler + response formatting
|   |   +-- handler.py          # Lambda entry point (API Gateway proxy)
|   |   +-- routes.py           # Route dispatch logic
|   |   +-- formatters.py       # Explainability payload construction
|   |
|   +-- backtest/               # Backtesting module (consumes stored data only)
|   |   +-- runner.py           # Backtest orchestration
|   |   +-- metrics.py          # Hit rate, Sharpe, mean return
|   |   +-- validators.py       # No look-ahead bias checks
|   |
|   +-- utils/                  # Shared utilities
|   |   +-- s3.py               # S3 read/write helpers (JSON + Parquet)
|   |   +-- dynamo.py           # DynamoDB read/write helpers
|   |   +-- config.py           # Environment config, bucket names, table names
|   |   +-- logging.py          # Structured logging setup
|   |   +-- dates.py            # Trading calendar, date helpers
|   |
|   +-- tests/                  # Test suite
|       +-- unit/               # Unit tests per module
|       +-- integration/        # S3/DynamoDB integration tests (localstack)
|       +-- fixtures/           # Sample raw JSON, expected outputs
|
+-- scripts/
|   +-- deploy_lambdas.sh       # Package and deploy Lambda functions
|   +-- run_pipeline.py         # Manual pipeline trigger for development
|   +-- seed_pairs.py           # Seed initial equity pairs
|
+-- layers/
|   +-- common_deps/            # Lambda layer: pandas, numpy, pyarrow
|       +-- requirements.txt    # Pinned dependency versions
|       +-- build_layer.sh      # Layer packaging script
|
+-- athena/
|   +-- create_tables.sql       # Athena external table DDL
|   +-- queries/                # Named analytical queries
|       +-- signal_audit.sql
|       +-- feature_drift.sql
|
+-- pyproject.toml              # Project metadata, dev dependencies
+-- README.md
```

### Structure Rationale

- **terraform/:** All stateful AWS resources in IaC. Separated by resource type for clarity. Lambda deployment stays in scripts/ because Lambda code changes frequently while infrastructure changes rarely -- this matches the stated constraint of "Terraform for storage IaC, Lambda via script."
- **src/ module-per-Lambda:** Each subdirectory maps 1:1 to a Lambda function with its own handler.py entry point. Shared code lives in utils/ and is included via a Lambda layer or bundled at deploy time.
- **layers/:** A single Lambda layer containing heavy dependencies (pandas, numpy, pyarrow). These libraries are too large for inline packaging and change infrequently. Lambda layers support up to 250 MB unzipped.
- **athena/:** SQL definitions kept in version control. These create external tables pointing at S3 Parquet data and provide named queries for analytical use.

## S3 Bucket and Prefix Structure

Use a **single bucket** with prefix-based separation. This simplifies IAM policies, lifecycle rules, and Athena table definitions while keeping a clean hierarchy.

**Confidence:** HIGH -- verified against AWS Athena partitioning docs and S3 best practices.

```
s3://leadlag-quant-{env}/
|
+-- raw/                                    # System of record (immutable)
|   +-- bars/
|   |   +-- ticker={TICKER}/
|   |       +-- date={YYYY-MM-DD}/
|   |           +-- bars.json               # Full Massive API response
|   |
|   +-- corporate_actions/
|   |   +-- splits/
|   |   |   +-- ticker={TICKER}/
|   |   |       +-- fetched={YYYY-MM-DD}/
|   |   |           +-- splits.json
|   |   +-- dividends/
|   |       +-- ticker={TICKER}/
|   |           +-- fetched={YYYY-MM-DD}/
|   |               +-- dividends.json
|   |
|   +-- tickers/
|       +-- fetched={YYYY-MM-DD}/
|           +-- tickers.json                # Reference ticker metadata
|
+-- normalized/                             # Policy-adjusted Parquet tables
|   +-- bars_raw_massive/
|   |   +-- ticker={TICKER}/
|   |       +-- year={YYYY}/
|   |           +-- data.parquet            # Canonical unadjusted bars
|   |
|   +-- normalized_bars/
|   |   +-- ticker={TICKER}/
|   |       +-- year={YYYY}/
|   |           +-- data.parquet            # Schema-normalized bars
|   |
|   +-- adjusted_bars_policy_a/
|   |   +-- adjustment_policy_id=policy_a/
|   |       +-- ticker={TICKER}/
|   |           +-- year={YYYY}/
|   |               +-- data.parquet        # Split-adjusted bars
|   |
|   +-- corporate_actions_splits/
|   |   +-- ticker={TICKER}/
|   |       +-- data.parquet
|   |
|   +-- corporate_actions_dividends/
|       +-- ticker={TICKER}/
|           +-- data.parquet
|
+-- features/                               # Computed feature tables
|   +-- features_daily/
|   |   +-- adjustment_policy_id=policy_a/
|   |       +-- ticker={TICKER}/
|   |           +-- year={YYYY}/
|   |               +-- data.parquet
|   |
|   +-- features_swing/
|       +-- adjustment_policy_id=policy_a/
|           +-- pair={LEADER}_{FOLLOWER}/
|               +-- year={YYYY}/
|                   +-- data.parquet
|
+-- athena-results/                         # Athena query output (auto-managed)
    +-- query_id=.../
```

### S3 Structure Rationale

- **Hive-style partitioning** (`key=value/`) enables automatic Athena partition discovery via `MSCK REPAIR TABLE` (verified in AWS docs). This eliminates manual `ALTER TABLE ADD PARTITION` calls.
- **ticker as partition key** because the primary access pattern is per-ticker reads during normalization and feature computation. Year as secondary partition prevents unbounded partition scans.
- **adjustment_policy_id in the path** for adjusted and feature tables ensures that if Policy B is added later, both coexist without path conflicts or data migration.
- **raw/ is immutable JSON** -- never overwritten, never deleted. This is the system of record for reproducibility. Apply S3 lifecycle to transition raw/ objects older than 90 days to S3 Standard-IA (still Athena-queryable, lower cost).
- **normalized/ and features/ use Parquet** for columnar compression (typically 5-10x smaller than JSON) and Athena predicate pushdown. Use snappy compression (Parquet default) for good compression-to-speed ratio.
- **Single bucket** keeps Terraform simple and IAM policies scoped by prefix rather than by bucket. For production, consider separate buckets if cross-account access is needed.

### S3 Lifecycle Rules

| Prefix | Transition | Rationale |
|--------|-----------|-----------|
| `raw/` | Standard -> Standard-IA after 90 days | Infrequently accessed after normalization, but must remain Athena-queryable |
| `normalized/` | No transition | Actively queried by Athena and feature computation |
| `features/` | No transition | Actively queried by engine and backtest |
| `athena-results/` | Expire after 7 days | Transient query output |

**Do NOT transition to Glacier** -- Athena cannot query Glacier objects directly (verified in AWS docs). Use Standard-IA as the cold tier.

## DynamoDB Signal Store Design

**Confidence:** HIGH -- verified against DynamoDB core components docs, partition key best practices, sort key best practices, TTL docs.

### Table: `signals`

| Attribute | Type | Role | Description |
|-----------|------|------|-------------|
| `pair_id` | String | Partition Key | `{LEADER}_{FOLLOWER}` (e.g., `NVDA_CRWV`) |
| `signal_date` | String | Sort Key | ISO date `YYYY-MM-DD` of the signal generation |
| `adjustment_policy_id` | String | Attribute (GSI PK) | `policy_a` -- propagated through entire pipeline |
| `signal_type` | String | Attribute | `lead_lag_daily`, `lead_lag_swing` |
| `stability_score` | Number | Attribute | 0-100 composite score |
| `correlation_strength` | Number | Attribute | Cross-correlation coefficient |
| `optimal_lag` | Number | Attribute | Number of sessions lag |
| `regime` | String | Attribute | `bull`, `base`, `bear`, `failure` |
| `entry_condition` | Map | Attribute | `{date, price, direction}` |
| `expected_target` | Map | Attribute | `{price, return_pct, window_bars}` |
| `invalidation_rule` | Map | Attribute | `{threshold, condition}` |
| `sizing_tier` | String | Attribute | `full`, `half`, `quarter` based on stability |
| `explainability` | Map | Attribute | Full audit payload (lag, window, correlation, stability, regime, policy) |
| `created_at` | String | Attribute | ISO timestamp |
| `ttl` | Number | Attribute (TTL) | Unix epoch seconds for auto-expiry |

### Access Patterns

| Pattern | Key Condition | Use Case |
|---------|--------------|----------|
| Get latest signal for a pair | PK=`NVDA_CRWV`, SK descending, Limit 1 | API: "What's the current signal for NVDA/CRWV?" |
| Get signal history for a pair | PK=`NVDA_CRWV`, SK between dates | API: "Show me all signals for this pair in January" |
| Get all signals for a date | GSI: PK=`signal_date` | Dashboard: "What signals fired today?" |
| Get all signals by policy | GSI: PK=`adjustment_policy_id`, SK=`signal_date` | Audit: "All Policy A signals" |

### Global Secondary Indexes

**GSI-1: `by-date`**
- Partition key: `signal_date` (String)
- Sort key: `pair_id` (String)
- Projection: ALL
- Purpose: Query all signals generated on a specific date

**GSI-2: `by-policy`**
- Partition key: `adjustment_policy_id` (String)
- Sort key: `signal_date` (String)
- Projection: KEYS_ONLY (fetch full item from base table if needed)
- Purpose: Audit trail by adjustment policy

### TTL Strategy

- Set `ttl` attribute to Unix epoch timestamp = `signal_date + 365 days`
- Signals older than 1 year auto-expire from DynamoDB (zero WCU cost for deletion, verified in AWS docs)
- Historical signals for backtest are in S3 features/ tables, not DynamoDB -- DynamoDB is the hot serving store only
- DynamoDB TTL deletes items "within a few days" of expiry (not instant) -- acceptable for this use case

### Capacity Mode

Use **on-demand (PAY_PER_REQUEST)** for MVP. With fewer than 100 tickers and daily batch writes, the volume is low (tens to low hundreds of writes per day). On-demand avoids capacity planning entirely and costs less than provisioned at this scale.

### Table: `pipeline_state` (operational metadata)

| Attribute | Type | Role | Description |
|-----------|------|------|-------------|
| `pipeline_run_id` | String | Partition Key | `{date}_{run_number}` |
| `stage` | String | Sort Key | `ingestion`, `normalization`, `features`, `engine` |
| `status` | String | Attribute | `running`, `completed`, `failed` |
| `started_at` | String | Attribute | ISO timestamp |
| `completed_at` | String | Attribute | ISO timestamp |
| `items_processed` | Number | Attribute | Count of tickers/pairs processed |
| `error_detail` | String | Attribute | Error message if failed |
| `ttl` | Number | Attribute (TTL) | Expire after 90 days |

This table enables pipeline observability: "Did today's run complete? Which stage failed? How many tickers were processed?"

## Lambda Function Decomposition

**Recommendation: Multiple focused Lambda functions, not one monolith.**

**Confidence:** HIGH -- based on AWS Lambda limits (15-min timeout, 10 GB memory), Lambda best practices, and the natural stage boundaries of this pipeline.

### Why Multiple Functions

1. **Timeout safety.** Each stage has different execution profiles. Ingestion depends on external API latency (Polygon.io); normalization is CPU-bound (Parquet conversion); feature computation scales with number of tickers x lookback windows. A single Lambda risks hitting the 15-minute timeout as the ticker universe grows.

2. **Memory right-sizing.** Feature computation with pandas/numpy on 60-day rolling windows needs more memory than ingestion (which is mostly HTTP I/O). Separate functions allow independent memory configuration: fn-ingest at 512 MB, fn-normalize and fn-features at 2048 MB (>1 vCPU equivalent), fn-engine at 1024 MB.

3. **Independent failure isolation.** If feature computation fails, you do not re-run ingestion. Each stage can be retried independently, and S3 acts as a checkpoint between stages.

4. **Independent deployment.** Changing the lead-lag detection algorithm does not require redeploying the ingestion Lambda. Faster iteration cycles.

5. **Clear IAM boundaries.** fn-ingest needs S3 PutObject on `raw/*` but never DynamoDB write. fn-engine needs DynamoDB PutItem but never Polygon API access. Least-privilege is natural when functions are decomposed.

### Function Specifications

| Function | Trigger | Memory | Timeout | Key Dependencies |
|----------|---------|--------|---------|------------------|
| `fn-ingest` | EventBridge schedule | 512 MB | 300s (5 min) | requests/httpx, boto3 |
| `fn-normalize` | Invoked by fn-ingest on completion | 2048 MB | 600s (10 min) | pandas, pyarrow, boto3 |
| `fn-features` | Invoked by fn-normalize on completion | 2048 MB | 600s (10 min) | pandas, numpy, scipy, boto3 |
| `fn-engine` | Invoked by fn-features on completion | 1024 MB | 300s (5 min) | pandas, numpy, boto3 |
| `fn-api` | API Gateway (HTTP request) | 256 MB | 10s | boto3 |

### Orchestration Pattern: Chained Invocation via Lambda Invoke

For MVP, use **direct Lambda-to-Lambda asynchronous invocation**. At the end of fn-ingest's handler, it calls `lambda_client.invoke(FunctionName='fn-normalize', InvocationType='Event', Payload=...)`. This chains the pipeline without additional infrastructure.

```python
# End of fn-ingest handler.py
import boto3
import json

lambda_client = boto3.client('lambda')

def trigger_next_stage(tickers_processed, run_id):
    lambda_client.invoke(
        FunctionName='fn-normalize',
        InvocationType='Event',  # Asynchronous -- fire and forget
        Payload=json.dumps({
            'run_id': run_id,
            'tickers': tickers_processed,
            'source_prefix': f'raw/bars/',
            'trigger_date': '2026-02-18'
        })
    )
```

**Why not Step Functions for MVP:**
- Step Functions adds infrastructure complexity (state machine definition, IAM for SFN, Terraform resources) for a 4-stage linear pipeline
- The pipeline is sequential, not branching -- Step Functions' value is in complex control flow (parallel branches, map states, error handling with retries)
- Direct invocation is simpler to debug locally and costs nothing beyond Lambda invocations
- **Phase 2 upgrade path:** When adding intraday 5-min processing, the pipeline becomes more complex (parallel ticker processing, fan-out/fan-in). At that point, migrate to Step Functions Distributed Map for parallel processing. The modular Lambda decomposition makes this migration straightforward.

### Lambda Layer Strategy

Use a **single shared layer** containing heavy scientific Python dependencies:

```
layers/common_deps/
+-- python/
    +-- lib/
        +-- python3.12/
            +-- site-packages/
                +-- pandas/
                +-- numpy/
                +-- pyarrow/
                +-- scipy/
```

- **Layer size constraint:** Up to 250 MB unzipped (verified in AWS docs). pandas + numpy + pyarrow + scipy fits within this limit when built against Amazon Linux 2023.
- **Max 5 layers per function** (verified). One shared layer is well within limits.
- **Build process:** Use a Docker container matching Lambda's Amazon Linux 2023 runtime to pip install dependencies, then zip the result. This avoids architecture mismatches (arm64 vs x86_64).
- **fn-api does NOT need the layer** -- it only reads from DynamoDB via boto3 (included in Lambda runtime). Keep fn-api lightweight for fast cold starts.

## Data Flow: Ingestion to Signal (Complete Path)

```
[EventBridge Scheduler]
    | (cron: 0 22 ? * MON-FRI *)  -- 22:00 UTC weekdays
    v
[fn-ingest]
    | 1. Read seeded pairs from config (DynamoDB or env var)
    | 2. For each ticker in universe:
    |      GET /v2/aggs/ticker/{T}/range/1/day/{from}/{to} (Massive API)
    |      -> s3://bucket/raw/bars/ticker={T}/date={YYYY-MM-DD}/bars.json
    | 3. GET /v3/reference/splits?ticker={T} (if needed)
    |      -> s3://bucket/raw/corporate_actions/splits/ticker={T}/...
    | 4. GET /v3/reference/dividends?ticker={T} (if needed)
    |      -> s3://bucket/raw/corporate_actions/dividends/ticker={T}/...
    | 5. Write pipeline_state: stage=ingestion, status=completed
    | 6. Invoke fn-normalize asynchronously
    v
[fn-normalize]
    | 1. Read raw JSON from s3://bucket/raw/bars/ticker={T}/...
    | 2. Validate against expected schema (detect API changes)
    | 3. Parse into bars_raw_massive canonical form
    | 4. Read splits from s3://bucket/raw/corporate_actions/splits/...
    | 5. Apply Policy A: multiply historical prices by cumulative split ratio
    |    (dividends stored separately, never baked into returns)
    | 6. Write Parquet:
    |      -> s3://bucket/normalized/bars_raw_massive/ticker={T}/year={YYYY}/data.parquet
    |      -> s3://bucket/normalized/normalized_bars/ticker={T}/year={YYYY}/data.parquet
    |      -> s3://bucket/normalized/adjusted_bars_policy_a/adjustment_policy_id=policy_a/ticker={T}/year={YYYY}/data.parquet
    |      -> s3://bucket/normalized/corporate_actions_splits/ticker={T}/data.parquet
    |      -> s3://bucket/normalized/corporate_actions_dividends/ticker={T}/data.parquet
    | 7. Write pipeline_state: stage=normalization, status=completed
    | 8. Invoke fn-features asynchronously
    v
[fn-features]
    | 1. Read adjusted bars from s3://bucket/normalized/adjusted_bars_policy_a/...
    | 2. Compute returns_policy_a from adj_close (5d/10d/20d/60d windows)
    | 3. Compute lagged returns (+/-1 to +/-5 bars)
    | 4. Compute rolling volatility (20d window)
    | 5. Compute z-score standardized returns
    | 6. For each seeded pair:
    |      Compute rolling cross-correlation across lags
    |      Compute Relative Strength (leader - follower return, 10-session rolling)
    | 7. Write Parquet:
    |      -> s3://bucket/features/features_daily/adjustment_policy_id=policy_a/ticker={T}/year={YYYY}/data.parquet
    |      -> s3://bucket/features/features_swing/adjustment_policy_id=policy_a/pair={L}_{F}/year={YYYY}/data.parquet
    | 8. Write pipeline_state: stage=features, status=completed
    | 9. Invoke fn-engine asynchronously
    v
[fn-engine]
    | 1. Read features from s3://bucket/features/...
    | 2. For each seeded pair:
    |      a. Detect lead-lag relationship (optimal lag, correlation strength)
    |      b. Compute stability_score (RSI-v2):
    |         lag persistence + regime stability + rolling confirmation
    |         + out-of-sample validation + lag drift penalty -> 0-100
    |      c. Classify regime: Bull/Base/Bear/Failure
    |         (MA structure, RS thresholds, ATR regime, volume/VWAP)
    |      d. Apply thresholds: stability_score > 70 AND correlation > 0.65
    |      e. If thresholds met, generate position spec:
    |         entry condition, expected target, invalidation rule, sizing tier
    |      f. Detect distribution signals (volume > 150% of 30d avg, VWAP rejection)
    |      g. Build directed flow map entry (adjacency matrix)
    | 3. Write qualifying signals to DynamoDB `signals` table
    | 4. Write pipeline_state: stage=engine, status=completed
    v
[DynamoDB signals table]
    |
    v
[fn-api] (invoked by API Gateway on HTTP request)
    | 1. Parse request: GET /signals/{pair_id}?date=...
    | 2. Query DynamoDB: PK=pair_id, SK=signal_date
    | 3. Format explainability payload:
    |    {lag, window, correlation, stability, regime,
    |     entry, target, invalidation, sizing, policy_id}
    | 4. Return JSON response
    v
[API Gateway] -> HTTP response to client
```

### Data Contracts Between Modules

Each Lambda reads/writes well-defined schemas. The S3 Parquet files and DynamoDB items serve as the contract boundary.

| Producer | Consumer | Contract Location | Format |
|----------|----------|-------------------|--------|
| fn-ingest | fn-normalize | `s3://raw/bars/ticker={T}/date={D}/bars.json` | JSON (Polygon API schema) |
| fn-ingest | fn-normalize | `s3://raw/corporate_actions/splits/ticker={T}/...` | JSON (Polygon API schema) |
| fn-normalize | fn-features | `s3://normalized/adjusted_bars_policy_a/.../data.parquet` | Parquet: columns = [date, open, high, low, close, adj_close, volume, vwap, adjustment_policy_id] |
| fn-normalize | Athena | `s3://normalized/*/...` | Parquet (all normalized tables) |
| fn-features | fn-engine | `s3://features/features_daily/.../data.parquet` | Parquet: columns = [date, ticker, returns_5d, returns_10d, returns_20d, returns_60d, lagged_returns_*, rolling_vol_20d, zscore_returns, adjustment_policy_id] |
| fn-features | fn-engine | `s3://features/features_swing/.../data.parquet` | Parquet: columns = [date, leader, follower, rolling_correlation_*, relative_strength_10d, adjustment_policy_id] |
| fn-engine | fn-api | DynamoDB `signals` table | DynamoDB item (schema above) |
| fn-engine | Athena | S3 features + DynamoDB (export) | Parquet (features), DynamoDB JSON (signals) |

## Architectural Patterns

### Pattern 1: S3 as Checkpoint (Stage Isolation)

**What:** Each pipeline stage writes its complete output to S3 before triggering the next stage. S3 acts as a durable checkpoint boundary.

**When to use:** Always, for every stage transition.

**Trade-offs:**
- PRO: Any stage can be re-run independently without re-running upstream stages
- PRO: Enables debugging by inspecting intermediate S3 outputs
- PRO: Backtest module can consume any intermediate table without running the pipeline
- CON: Additional S3 write latency (typically <100ms for small Parquet files, negligible for batch)

**Example:**
```python
# fn-normalize writes checkpoint before triggering fn-features
def handler(event, context):
    raw_data = read_raw_from_s3(event['tickers'], event['trigger_date'])
    normalized = normalize_and_adjust(raw_data)

    # Checkpoint: write output to S3
    write_parquet_to_s3(normalized, prefix='normalized/adjusted_bars_policy_a/')

    # Record pipeline state
    record_stage_completion('normalization', event['run_id'])

    # Trigger next stage
    trigger_next_stage('fn-features', event)
```

### Pattern 2: Immutable Raw Layer

**What:** Raw API responses stored as-is in S3, never modified or overwritten. All transformations produce new objects in different prefixes.

**When to use:** Always, for the `raw/` prefix.

**Trade-offs:**
- PRO: Complete audit trail -- can always reprocess from source if normalization logic changes
- PRO: Reproducibility guarantee -- signals traceable back to exact API response
- PRO: Schema evolution protection -- if Polygon changes their API format, historical data is preserved
- CON: Storage cost for duplicate data (mitigated by S3-IA lifecycle transition)

### Pattern 3: Policy ID Propagation

**What:** The `adjustment_policy_id` is embedded in S3 paths and carried as a column in every Parquet table and DynamoDB signal item. This enables future Policy B without path conflicts.

**When to use:** Every table from adjusted_bars onward.

**Trade-offs:**
- PRO: Multiple adjustment policies can coexist simultaneously
- PRO: Signals are self-documenting -- the policy that produced them is always visible
- PRO: Athena queries can filter by policy
- CON: Slight verbosity in paths and schemas

### Pattern 4: Thin API Lambda

**What:** fn-api is a lightweight read-only function that queries DynamoDB and formats responses. It contains zero business logic, zero computation.

**When to use:** For the API Gateway-backed Lambda function.

**Trade-offs:**
- PRO: Fast cold starts (no heavy dependencies, ~256 MB memory)
- PRO: Clear separation -- computation happens in batch Lambdas, serving happens in fn-api
- PRO: API availability is independent of pipeline health
- CON: Signals must be pre-computed and stored (cannot compute on-demand)

## Anti-Patterns to Avoid

### Anti-Pattern 1: Monolith Lambda

**What people do:** Put all pipeline stages (ingestion, normalization, features, engine) into a single Lambda function with conditional branching.

**Why it's wrong:** Hits 15-minute timeout as ticker universe grows. Cannot right-size memory per stage. A bug in feature computation forces redeployment of ingestion. IAM permissions become a union of all stages (over-privileged).

**Do this instead:** One Lambda per pipeline stage with S3 checkpoints between them.

### Anti-Pattern 2: S3 Event-Driven Chaining

**What people do:** Trigger fn-normalize via S3 PutObject event on the raw/ prefix, then trigger fn-features via S3 PutObject event on normalized/, etc.

**Why it's wrong:** S3 events fire per-object, not per-batch. If fn-ingest writes 100 ticker files, fn-normalize gets triggered 100 times (once per file), not once after all files are written. This causes race conditions, duplicate processing, and explosion of Lambda invocations.

**Do this instead:** Use direct Lambda-to-Lambda invocation at the end of each stage's handler, passing the list of processed tickers as payload. The upstream function knows when the batch is complete.

### Anti-Pattern 3: Storing Computed Features in DynamoDB

**What people do:** Put feature tables (rolling returns, correlations, z-scores) in DynamoDB because "it's fast."

**Why it's wrong:** Feature tables are wide (many columns per row), append-heavy, and queried by date range during backtest. DynamoDB excels at key-value lookups, not analytical scans. Parquet on S3 + Athena is 10-100x cheaper for this access pattern and supports SQL.

**Do this instead:** Store features in S3 as Parquet. Reserve DynamoDB for the signal store (narrow items, key-value access pattern via API).

### Anti-Pattern 4: Re-querying Massive in Backtest

**What people do:** Have the backtest module call Polygon.io/Massive API to get historical data for backtesting.

**Why it's wrong:** Violates reproducibility (API data may change with corrections). Introduces look-ahead bias risk (API may return data not available at historical date). Wastes API quota. The project constraints explicitly forbid this.

**Do this instead:** Backtest module reads exclusively from S3 stored data (normalized/ and features/ prefixes). Never imports from ingestion_massive module.

## IAM Role Structure

**Principle: One IAM role per Lambda function, least-privilege permissions scoped by S3 prefix.**

**Confidence:** HIGH -- verified against AWS Lambda permissions documentation.

### Role Definitions

```
role: fn-ingest-execution-role
  +-- AWSLambdaBasicExecutionRole (managed)     # CloudWatch Logs
  +-- inline: ingest-s3-write
      Action: s3:PutObject
      Resource: arn:aws:s3:::leadlag-quant-{env}/raw/*
  +-- inline: ingest-lambda-invoke
      Action: lambda:InvokeFunction
      Resource: arn:aws:lambda:{region}:{account}:function:fn-normalize
  +-- inline: ingest-pipeline-state
      Action: dynamodb:PutItem
      Resource: arn:aws:dynamodb:{region}:{account}:table/pipeline_state

role: fn-normalize-execution-role
  +-- AWSLambdaBasicExecutionRole (managed)
  +-- inline: normalize-s3-read
      Action: s3:GetObject
      Resource: arn:aws:s3:::leadlag-quant-{env}/raw/*
  +-- inline: normalize-s3-write
      Action: s3:PutObject
      Resource: arn:aws:s3:::leadlag-quant-{env}/normalized/*
  +-- inline: normalize-lambda-invoke
      Action: lambda:InvokeFunction
      Resource: arn:aws:lambda:{region}:{account}:function:fn-features
  +-- inline: normalize-pipeline-state
      Action: dynamodb:PutItem
      Resource: arn:aws:dynamodb:{region}:{account}:table/pipeline_state

role: fn-features-execution-role
  +-- AWSLambdaBasicExecutionRole (managed)
  +-- inline: features-s3-read
      Action: s3:GetObject
      Resource: arn:aws:s3:::leadlag-quant-{env}/normalized/*
  +-- inline: features-s3-write
      Action: s3:PutObject
      Resource: arn:aws:s3:::leadlag-quant-{env}/features/*
  +-- inline: features-lambda-invoke
      Action: lambda:InvokeFunction
      Resource: arn:aws:lambda:{region}:{account}:function:fn-engine
  +-- inline: features-pipeline-state
      Action: dynamodb:PutItem
      Resource: arn:aws:dynamodb:{region}:{account}:table/pipeline_state

role: fn-engine-execution-role
  +-- AWSLambdaBasicExecutionRole (managed)
  +-- inline: engine-s3-read
      Action: s3:GetObject
      Resource: arn:aws:s3:::leadlag-quant-{env}/features/*
  +-- inline: engine-dynamo-write
      Action: dynamodb:PutItem, dynamodb:BatchWriteItem
      Resource: arn:aws:dynamodb:{region}:{account}:table/signals
  +-- inline: engine-pipeline-state
      Action: dynamodb:PutItem
      Resource: arn:aws:dynamodb:{region}:{account}:table/pipeline_state

role: fn-api-execution-role
  +-- AWSLambdaBasicExecutionRole (managed)
  +-- inline: api-dynamo-read
      Action: dynamodb:GetItem, dynamodb:Query
      Resource:
        - arn:aws:dynamodb:{region}:{account}:table/signals
        - arn:aws:dynamodb:{region}:{account}:table/signals/index/*
```

### IAM Rationale

- **fn-ingest cannot read from normalized/ or features/** -- it only produces raw data. This prevents accidental circular dependencies.
- **fn-engine cannot write to S3** -- it only produces DynamoDB signals. If engine output needs to be in S3 (e.g., for Athena analysis of signals), add a separate export step.
- **fn-api is read-only** -- it cannot modify signals, cannot access S3, cannot invoke other Lambdas. This is the most exposed function (internet-facing via API Gateway) so it has the tightest permissions.
- **Pipeline state table** gets PutItem only from pipeline Lambdas -- fn-api does not need pipeline state access.

## Athena Integration

### External Table Definitions

Athena queries S3 Parquet data via external tables. Define these in `athena/create_tables.sql`:

```sql
-- Example: adjusted bars table
CREATE EXTERNAL TABLE IF NOT EXISTS adjusted_bars_policy_a (
    date         DATE,
    open         DOUBLE,
    high         DOUBLE,
    low          DOUBLE,
    close        DOUBLE,
    adj_close    DOUBLE,
    volume       BIGINT,
    vwap         DOUBLE
)
PARTITIONED BY (
    adjustment_policy_id STRING,
    ticker               STRING,
    year                 STRING
)
STORED AS PARQUET
LOCATION 's3://leadlag-quant-prod/normalized/adjusted_bars_policy_a/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');

-- Discover partitions automatically (Hive-style paths)
MSCK REPAIR TABLE adjusted_bars_policy_a;
```

### Athena Best Practices for This Pipeline

1. **Use partition projection** instead of `MSCK REPAIR TABLE` for tables with predictable partition patterns. Partition projection calculates partition values in-memory, eliminating metadata store lookups (verified in AWS Athena docs). This is faster for queries against known ticker/date ranges.

2. **Always include partition columns in WHERE clause.** `WHERE ticker = 'NVDA' AND year = '2025'` scans only that partition. Omitting partition columns triggers a full table scan across all tickers and years.

3. **Parquet + Snappy compression** is the default and recommended combination. Athena leverages Parquet's columnar predicate pushdown (min/max statistics per column chunk) to skip irrelevant data blocks.

4. **Athena workgroup** with query result location set to `s3://bucket/athena-results/` and cost controls (per-query data scan limit) prevents runaway queries.

5. **Named queries** stored in `athena/queries/` for repeatable analytical tasks: signal audit, feature drift detection, backtest data extraction.

## Scaling Considerations

| Concern | MVP (<100 tickers) | Growth (100-500 tickers) | Large Scale (500+ tickers) |
|---------|---------------------|--------------------------|----------------------------|
| **Ingestion time** | Serial ticker loop in fn-ingest, <5 min | Parallelize with ThreadPoolExecutor within single Lambda | Fan-out: Step Functions Distributed Map, one invocation per ticker |
| **Normalization** | Single Lambda processes all tickers, <10 min | Acceptable if within 15-min timeout | Fan-out: one Lambda per ticker, orchestrated by Step Functions |
| **Feature computation** | Single Lambda, <10 min | Memory pressure increases with ticker count | Fan-out: per-ticker Lambda for single-ticker features, per-pair for cross-features |
| **DynamoDB writes** | On-demand, tens of items | On-demand, hundreds of items | On-demand auto-scales; consider BatchWriteItem |
| **S3 storage** | ~10 GB/year | ~50 GB/year | ~250 GB/year; lifecycle rules become important |
| **Athena cost** | Negligible | Partition pruning critical | Consider AWS Glue Data Catalog for metadata management |
| **API latency** | Single-digit ms DynamoDB reads | Same | DynamoDB DAX cache if read volume justifies it |

### Scaling Priorities

1. **First bottleneck: Lambda timeout on fn-features.** As the ticker universe grows, rolling feature computation (especially cross-correlation across lag windows) is O(tickers x pairs x lags x lookback). Mitigation: parallelize within Lambda using concurrent.futures, or fan-out to per-pair Lambdas.

2. **Second bottleneck: Polygon.io API rate limits.** Massive API has per-second and per-minute rate limits. Mitigation: implement exponential backoff in polygon_client.py, and batch date ranges to minimize API calls.

3. **Third bottleneck: Lambda cold starts on fn-api.** If API is called infrequently, cold starts add 1-3 seconds. Mitigation: use provisioned concurrency (1 instance) or accept cold start latency for personal use.

## Build Order (Critical Path)

The architecture has clear dependencies that dictate build order. Each phase builds on the previous.

```
Phase 1: Foundation
  terraform/ (S3 bucket, DynamoDB tables, IAM roles)
  +-- utils/ (S3 helpers, config, logging)
  +-- Lambda layer (pandas, numpy, pyarrow)
  Must exist first: everything depends on storage and shared utilities

Phase 2: Ingestion
  ingestion_massive/ (Polygon client, raw JSON writer)
  +-- EventBridge scheduled rule
  Depends on: Phase 1 (S3 bucket, IAM role for fn-ingest)
  Validates: API connectivity, raw data lands in correct S3 paths

Phase 3: Normalization
  normalization/ (Policy A, schema parsing, Parquet writer)
  Depends on: Phase 2 (raw data must exist in S3)
  Validates: Raw JSON -> canonical Parquet, split-adjustment correctness

Phase 4: Features
  features/ (rolling computations, cross-correlation, RS)
  Depends on: Phase 3 (adjusted bars must exist)
  Validates: Feature tables correct against manual calculation

Phase 5: Engine + Signals
  leadlag_engine/ (detection, stability, regime, position spec)
  +-- signals/ (models, thresholds)
  Depends on: Phase 4 (features must exist)
  Validates: End-to-end pipeline produces signals in DynamoDB

Phase 6: API
  api/ (fn-api, API Gateway)
  Depends on: Phase 5 (signals must exist in DynamoDB)
  Validates: HTTP request returns correct signal with explainability

Phase 7: Observability + Hardening
  CloudWatch alarms, pipeline_state table, error handling, retries
  Depends on: Phase 5 (pipeline must run end-to-end)

Phase 8: Backtest
  backtest/ (runner, metrics, validators)
  Depends on: Phase 3-4 (needs normalized + feature data in S3)
  Can start in parallel with Phase 5 once feature data exists

Phase 9: Athena Analytics
  athena/ (table DDL, named queries)
  Depends on: Phase 3 (needs Parquet data in S3)
  Can start in parallel with Phase 4+ once normalized data exists
```

### Critical Path: Phase 1 -> 2 -> 3 -> 4 -> 5 -> 6

The main pipeline is strictly sequential. You cannot build normalization without raw data, cannot compute features without normalized data, etc. Phases 7-9 are parallelizable once their dependencies are met.

### Build Order Rationale

- **Infrastructure first** (Phase 1) because every Lambda needs S3 buckets, IAM roles, and the shared layer to exist.
- **Ingestion before normalization** because normalization needs real raw data to test against (fixtures are insufficient for validating Polygon API schema handling).
- **Features before engine** because the lead-lag detection algorithms need real feature data to verify statistical correctness.
- **API last in the main path** because it is pure read-only and the simplest Lambda -- the value is in the pipeline, not the API.
- **Backtest parallelizable with engine** because it reads from the same S3 feature data but does not depend on DynamoDB signals.

## Integration Points

### External Services

| Service | Integration Pattern | Gotchas |
|---------|---------------------|---------|
| **Polygon.io/Massive** | REST API via httpx/requests in fn-ingest | Rate limits (5 calls/min on free tier, higher on paid); API may return partial data for recent dates; pagination needed for splits/dividends |
| **EventBridge Scheduler** | Cron expression triggers fn-ingest | Use EventBridge Scheduler (not legacy scheduled rules, per AWS recommendation); minimum granularity is 1 minute; all times UTC |
| **API Gateway** | REST API with Lambda proxy integration | 29-second timeout on API Gateway (independent of Lambda timeout); 10 MB response size limit; consider HTTP API (cheaper) over REST API for single-user personal use |

### Internal Boundaries

| Boundary | Communication | Contract |
|----------|---------------|----------|
| fn-ingest -> fn-normalize | Async Lambda invoke with payload `{run_id, tickers, trigger_date}` | Payload must include complete ticker list for the run |
| fn-normalize -> fn-features | Async Lambda invoke with payload `{run_id, tickers, trigger_date}` | fn-features reads from known S3 prefix, does not parse the payload for data |
| fn-features -> fn-engine | Async Lambda invoke with payload `{run_id, pairs, trigger_date}` | fn-engine reads from known S3 prefix; pairs list tells it which pair directories to read |
| fn-api -> DynamoDB | boto3 Query with PK + SK conditions | fn-api trusts DynamoDB item schema; schema validation happens at write time in fn-engine |
| All Lambdas -> pipeline_state | boto3 PutItem after stage completion | Schema: {pipeline_run_id, stage, status, started_at, completed_at, items_processed} |

## Sources

- AWS Lambda Invocation Documentation: https://docs.aws.amazon.com/lambda/latest/dg/lambda-invocation.html (HIGH confidence)
- AWS Lambda Limits: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html (HIGH confidence)
- AWS Lambda Layers: https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html (HIGH confidence)
- AWS Lambda Python Runtime: https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html (HIGH confidence)
- AWS Lambda Permissions: https://docs.aws.amazon.com/lambda/latest/dg/lambda-permissions.html (HIGH confidence)
- AWS Lambda S3 Integration: https://docs.aws.amazon.com/lambda/latest/dg/with-s3.html (HIGH confidence)
- AWS Lambda API Gateway Integration: https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html (HIGH confidence)
- DynamoDB Partition Key Design: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html (HIGH confidence)
- DynamoDB Sort Key Best Practices: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-sort-keys.html (HIGH confidence)
- DynamoDB Time-Series Best Practices: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-time-series.html (HIGH confidence)
- DynamoDB Core Components: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html (HIGH confidence)
- DynamoDB TTL: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html (HIGH confidence)
- Athena Partitioning: https://docs.aws.amazon.com/athena/latest/ug/partitions.html (HIGH confidence)
- Athena Columnar Storage: https://docs.aws.amazon.com/athena/latest/ug/columnar-storage.html (HIGH confidence)
- S3 Lifecycle Management: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html (HIGH confidence)
- EventBridge Scheduled Rules: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html (HIGH confidence)
- Step Functions Standard vs Express: https://docs.aws.amazon.com/step-functions/latest/dg/concepts-standard-vs-express.html (HIGH confidence)
- CloudWatch Lambda Logging: https://docs.aws.amazon.com/lambda/latest/dg/monitoring-cloudwatchlogs.html (HIGH confidence)

---
*Architecture research for: Lead-Lag Quant serverless quantitative analytics pipeline*
*Researched: 2026-02-18*
