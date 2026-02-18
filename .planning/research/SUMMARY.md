# Project Research Summary

**Project:** Lead-Lag Quant — Serverless Quantitative Lead-Lag Equity Analytics Platform
**Domain:** Serverless quantitative analytics pipeline (AWS Lambda / Python / financial time-series)
**Researched:** 2026-02-18
**Confidence:** MEDIUM (stack versions need validation with `pip index versions`; AWS architecture patterns HIGH; statistical pitfalls HIGH)

## Executive Summary

This is a serverless quantitative analytics pipeline that ingests unadjusted equity data from Polygon.io/Massive, applies a deterministic split-adjustment policy (Policy A), computes rolling cross-correlation lead-lag signals across user-seeded ticker pairs, and serves actionable position specs via a REST API. Experts build this class of system as a staged batch pipeline — ingestion, normalization, feature computation, signal generation — with each stage checkpointed to S3 so any stage can be rerun without re-querying external APIs. The compute-intensive stages (cross-correlation, rolling windows) run in heavy Lambdas at 1024-2048 MB; the API-serving Lambda is a thin DynamoDB reader with no scientific dependencies. DynamoDB holds the hot signal store; S3 Parquet holds all intermediate and feature tables for Athena-queryable analytical access.

The recommended approach is Docker-based Lambda container images (10 GB limit) rather than zip-based Lambda layers (250 MB unzipped limit). The full scientific Python stack — numpy, scipy, pandas, pyarrow — routinely exceeds the zip limit when uncompressed, which causes deployment failures before a single line of business logic runs. A stripped Docker image containing these four libraries lands at 400-500 MB, well within the container limit. All other stack choices are conventional for this domain: Python 3.12 (mature AL2023 wheel support), `requests` over `polygon-api-client` (architectural control, no unused WebSocket deps), DynamoDB on-demand for signals (key-value access pattern, zero idle cost), S3 + Athena for features (analytical access pattern, columnar Parquet).

The critical risks are data-quality and statistical validity risks, not infrastructure risks. Dividend contamination in returns (requesting Polygon `adjusted=true` instead of `adjusted=false`) silently poisons every downstream computation. Look-ahead bias from future split data leaking into historical backtests overstates strategy performance. Spurious cross-correlation from common market-factor exposure produces false lead-lag signals. All three of these are correctness failures that require architectural decisions in Phase 1 (data ingestion) to prevent — they cannot be patched later. Build the data layer correctly before writing signal logic.

## Key Findings

### Recommended Stack

The scientific Python stack (numpy >=2.1, scipy >=1.14, pandas >=2.2, pyarrow >=15) is the correct and only viable choice for this domain. There are no worthwhile alternatives: numpy.correlate lacks the lag semantics of `scipy.signal.correlate`; polars has weaker scipy/numpy interop; TA-Lib is notoriously painful to compile on Lambda. The mathematical core — rolling normalized cross-correlation via `scipy.signal.correlate` + `correlation_lags` — is a ~200-300 line module, not a library selection problem.

The packaging decision resolves to Docker container images. The STACK researcher proposed two Lambda zip layers (~45-48 MB zipped each), but the PITFALLS and ARCHITECTURE researchers both flagged that the 250 MB UNZIPPED limit is the binding constraint — zipped size is irrelevant once Lambda extracts the layers into `/opt`. numpy + scipy + pandas + pyarrow together consistently exceed 250 MB unzipped. Docker images remove this constraint entirely and allow a clean `pip install` workflow. See conflict resolution note below.

**Packaging conflict resolution — use Docker, not zip layers:**
The STACK researcher recommended two zip Lambda layers; the PITFALLS researcher recommended Docker container images; the ARCHITECTURE researcher flagged the layer size concern. The correct recommendation is Docker container images (`public.ecr.aws/lambda/python:3.12` base). The 250 MB unzipped zip limit is effectively a hard blocker for the full scientific Python stack. Docker's 10 GB limit is not. Use zip layers only if Docker build infrastructure is not available — and treat that as a known technical risk requiring validation before Phase 1 begins.

**Core technologies:**
- Python 3.12: Lambda runtime — broadest scientific wheel support on Amazon Linux 2023; avoid 3.13 until wheels mature
- numpy >=2.1: Array operations, rolling windows — foundation; v2.x ships manylinux_2_17 wheels for AL2023
- scipy >=1.14: `scipy.signal.correlate` + `correlation_lags` — the only viable cross-correlation primitive
- pandas >=2.2: Time-series DataFrames, rolling windows, `shift()` for lag offsets — industry standard for financial time-series
- pyarrow >=15: Parquet read/write for S3 — required for Athena-queryable columnar storage
- requests >=2.31: Polygon.io REST client — raw requests over polygon-api-client (no unused WebSocket deps, full parser control)
- pydantic >=2.6: Signal schema validation — all internal data contracts between modules
- boto3: AWS SDK — use Lambda-bundled version; do NOT package it in the container
- DynamoDB (on-demand): Signal store — key-value lookups, zero idle cost, single-digit ms reads for API serving
- S3 + Athena: Raw JSON system of record + Parquet feature tables — cheap, durable, analytical access via SQL
- uv: Dependency management — already initialized (uv.lock present); 10-100x faster than pip
- Terraform >=1.7: IaC for stateful resources (S3, DynamoDB, IAM) only; Lambda deployed via script

**What NOT to use:**
- `polygon-api-client` — adds WebSocket deps for 4-5 trivial REST calls; use raw `requests`
- `tsfresh` — extracts 700+ features; you need one; blows Lambda layer budget
- `TA-Lib` — painful C compilation on Lambda; all needed indicators are trivial in pandas
- `numpy.correlate` — missing `mode='full'` lag semantics; use `scipy.signal.correlate`
- Python 3.13 — scientific wheel ecosystem not yet mature on AL2023

### Expected Features

The pipeline has a strict sequential dependency chain: raw bars cannot be normalized without splits data; returns cannot be computed without adjusted bars; cross-correlation requires returns from both tickers in a pair; stability score requires cross-correlation + regime + out-of-sample validation; position specs require all of the above. Building any component before its upstream dependency is validated wastes effort.

**Must have (table stakes — MVP v1):**
- Polygon.io REST client with cursor-based pagination (`next_url`), exponential backoff, and token-bucket rate limiter
- Raw JSON archival to S3 (system of record; immutable; everything downstream depends on this)
- Aggregate bars ingestion (`adjusted=false`), splits ingestion, dividends ingestion (stored but never used in returns)
- Split-adjustment engine, Policy A — deterministic cumulative ratio application; `adjustment_policy_id` on every record
- Returns computation from `adj_close` only — 1d/5d/10d/20d/60d windows
- Rolling cross-correlation across lags -5 to +5 with SPY residualization
- Stability score (RSI-v2) — lag persistence + regime stability + rolling confirmation + OOS validation + lag drift penalty
- Regime classification (Bull/Base/Bear/Failure) — hard rules, no ML
- Hard threshold gates: stability_score > 70 AND correlation_strength > 0.65
- Full position spec: entry condition, expected target, invalidation rule, sizing tier
- REST API (API Gateway + lightweight fn-api Lambda) with explainability payload
- Signal history storage — immutable once written
- Daily batch orchestration via EventBridge cron
- Terraform IaC for S3 and DynamoDB
- Backtest module reading from stored S3 data only (never re-queries Polygon)
- Structured logging with correlation IDs

**Should have (differentiators — v1.x after CRWV/NVDA validates):**
- Directed flow map (adjacency matrix) — meaningful only with 5+ active pairs
- Lag drift detection and tracking — requires 60+ trading days of signal history
- Multi-pair summary API endpoint
- SNS alerting on new signal or regime change
- Pipeline health CloudWatch dashboard
- Pair onboarding automation

**Defer (v2+):**
- Intraday 5-minute bars — different Lambda architecture, different signal characteristics
- Sentiment / options skew layer — separate data pipeline
- Web dashboard — separate frontend project; API-first means this can be built independently
- WebSocket streaming — Lambda cold starts make real-time unreliable; daily batch is correct for swing timeframe

**Explicit anti-features (never build):**
- All-pairs exhaustive discovery — O(n^2) explosion, statistical multiple-testing nightmare
- ML-based signal generation — violates explainability requirement; insufficient training data
- Automated order execution — regulatory risk; position specs are the output
- Dynamic threshold adjustment — introduces hidden state, makes signals non-reproducible

### Architecture Approach

The architecture is a linear staged batch pipeline with five Lambda functions decomposed by stage: fn-ingest (Polygon API, raw S3 writes), fn-normalize (Policy A adjustment, Parquet writes), fn-features (rolling computations, cross-correlation), fn-engine (lead-lag detection, stability scoring, signal generation), fn-api (lightweight DynamoDB reader, no scientific stack). Each stage is triggered by the previous stage via async Lambda-to-Lambda invocation (fire-and-forget), with S3 acting as the durable checkpoint between stages. This avoids S3-event-driven chaining, which would trigger per-object (100 files = 100 invocations) rather than per-batch. The orchestration upgrades to Step Functions when intraday processing is added in v2.

**Major components:**
1. EventBridge Scheduler — daily cron at 22:00 UTC (market close + data lag buffer); triggers fn-ingest
2. fn-ingest — Polygon client, pagination, rate limiting, S3 raw/ writes; 512 MB, 300s timeout
3. fn-normalize — Policy A split adjustment, schema validation, Parquet writes to S3 normalized/; 2048 MB, 600s timeout
4. fn-features — rolling returns, volatility, z-scores, cross-correlation per pair; writes S3 features/; 2048 MB, 600s timeout
5. fn-engine — lead-lag detection, stability score, regime classification, position spec generation, DynamoDB writes; 1024 MB, 300s timeout
6. fn-api — read-only DynamoDB queries, explainability payload formatting; 256 MB, 10s timeout; NO scientific Python layer
7. S3 (single bucket, prefix-separated) — raw/ (immutable JSON), normalized/ (Parquet), features/ (Parquet), athena-results/
8. DynamoDB — signals table (PK: pair_id, SK: signal_date) + pipeline_state table; on-demand capacity
9. Athena — ad-hoc SQL queries over S3 Parquet via Hive-partitioned external tables; not in hot path
10. CloudWatch — structured logs from all functions; alarms on error rate, duration, DLQ depth

**Key patterns:**
- S3 as checkpoint: each stage writes complete output before triggering next; enables independent stage reruns
- Immutable raw layer: raw/ is never overwritten; all transformations produce new objects in new prefixes
- Policy ID propagation: `adjustment_policy_id` embedded in every S3 path and every DynamoDB attribute
- Thin API Lambda: fn-api contains zero business logic; fast cold starts (~256 MB, no scipy)
- One IAM role per Lambda with least-privilege S3 prefix scoping

### Critical Pitfalls

1. **Lambda deployment package exceeds 250 MB unzipped limit** — Use Docker container images (10 GB limit), not zip Lambda layers. Build the Docker image in CI on the correct architecture (linux/amd64). Validate cold start < 10 seconds before writing business logic. Address in Phase 0 (infrastructure setup) before any other work begins.

2. **Dividend contamination in returns (Policy A violation)** — Always request `adjusted=false` from Polygon. Fetch splits from `/v3/reference/splits` and apply deterministically in the normalization layer. Never use Polygon's `adjusted=true`. Store dividends separately; never include them in returns computation. Add assertion: `adjustment_policy_id == "policy_a"` in the normalization path. Validate in an integration test that returns_policy_a differs from Polygon adjusted=true returns for any dividend-paying ticker. Must be correct from day one — every downstream signal depends on it.

3. **Spurious cross-correlation from common factor exposure** — Residualize returns against SPY before computing cross-correlation. Use minimum 60-day rolling window (not 20). Apply Bonferroni correction for multiple lag testing (threshold = 0.05/11 = 0.0045 with lags -5 to +5). Require p-value < 0.01. The stability_score's OOS validation component is the right approach but must use a non-overlapping estimation-validation window with a gap period (dead zone) to prevent look-ahead contamination.

4. **Look-ahead bias from future split data in backtests** — Store `fetched_at` timestamp alongside every split record at ingestion time. Backtest adjustment path must filter splits to `execution_date <= backtest_date AND fetched_at <= backtest_date`. Live pipeline uses all known splits. These must be two separate code paths: `adjust_for_backtest(bars, as_of_date)` vs `adjust_for_live(bars)`. Design this in Phase 1 even though the backtest module is built in a later phase.

5. **Backtest module re-querying Polygon** — The backtest module must never import from the ingestion layer. Enforce with import linting in CI. Define a `BacktestDataProvider` interface that reads exclusively from S3. Add a CI check that verifies no Polygon API calls appear in backtest CloudWatch logs.

## Implications for Roadmap

Based on the strict dependency chain identified in research, 6 phases are required for a functioning MVP, with 2 additional phases (observability hardening and analytics) that can run in parallel once the core pipeline is working.

### Phase 0: Infrastructure Foundation
**Rationale:** Every Lambda needs S3 buckets, IAM roles, and a deployable Docker image before a single line of business logic can be tested. The Docker packaging decision must be validated (cold start < 10s, numpy/scipy/pandas import successfully) before writing anything else. Failing to solve this first wastes all subsequent effort.
**Delivers:** Terraform-provisioned S3 bucket (with Hive-partitioned prefix structure), DynamoDB tables (signals + pipeline_state), IAM roles (one per Lambda, least-privilege), Docker build pipeline, EventBridge scheduled rule, shared utilities (S3 helpers, config, structured logging, date helpers)
**Addresses:** FEATURES.md — Terraform IaC, structured logging; ARCHITECTURE.md — project structure, IAM roles, S3 prefix design
**Avoids:** Pitfall 5 (Lambda packaging), Pitfall 14 (S3 partitioning), security mistakes (API keys, bucket public access)
**Research flag:** This phase has well-documented patterns. Docker Lambda deployment is thoroughly documented in AWS official docs. Skip deeper research; execute directly.

### Phase 1: Data Ingestion and Normalization
**Rationale:** Every downstream computation depends on correctly adjusted price data. The adjustment policy (Policy A: split-only, no dividends) and the `adjustment_policy_id` propagation must be built correctly from day one. A schema error here invalidates all signals. Real raw data from Polygon must be in S3 before normalization logic can be validated against it — fixtures alone are insufficient for catching API schema quirks.
**Delivers:** Polygon.io REST client (cursor pagination, token-bucket rate limiter, exponential backoff, idempotent ingestion), raw JSON archival to S3, aggregate bars + splits + dividends ingestion, Policy A split-adjustment engine, canonical Parquet tables (bars_raw_massive, normalized_bars, adjusted_bars_policy_a, corporate_actions_splits/dividends), timestamp normalization (UTC + NYSE trading day), policy_id on every record
**Addresses:** FEATURES.md — all P1 Phase 1 features; complete Polygon integration (26-52 hours estimated)
**Avoids:** Pitfall 1 (dividend contamination), Pitfall 2 (look-ahead bias from splits — `fetched_at` column designed here), Pitfall 6 (DynamoDB hot partition — pair_id PK not date), Pitfall 7 (rate limiting/pagination), Pitfall 9 (timezone normalization), Pitfall 12 (policy_id propagation), Pitfall 14 (S3 partitioning), Pitfall 15 (parser versioning)
**Research flag:** Polygon.io rate limits by plan tier and exact field names should be verified against current official documentation before implementation. MEDIUM confidence on specifics.

### Phase 2: Feature Engineering and Lead-Lag Engine
**Rationale:** This is the statistical heart of the system. Spurious correlations from common factor exposure and insufficient windows produce false signals that look credible. The stability score (RSI-v2) is the primary differentiator and the quality gate — it must be built correctly, not quickly. Features must exist in S3 before the engine can be validated. The engine cannot be tested with random test data alone; it needs real market time-series to validate statistical properties.
**Delivers:** Returns computation (adj_close, 1d/5d/10d/20d/60d), rolling volatility, z-score standardized returns, SPY factor residualization, rolling cross-correlation across lags -5 to +5, Relative Strength (leader - follower, 10-session), optimal lag detection, stability_score (RSI-v2) with non-overlapping estimation + gap + validation windows, regime classification (Bull/Base/Bear/Failure), distribution detection (volume + VWAP), S3 feature Parquet tables (features_daily, features_swing)
**Addresses:** FEATURES.md — all P1 Phase 2 features; ARCHITECTURE.md — fn-features and fn-engine components
**Avoids:** Pitfall 3 (spurious cross-correlation — SPY residualization, 60-day minimum window, Bonferroni correction), Pitfall 4 (OOS contamination — gap period between estimation and validation windows), Pitfall 11 (memory explosion — pair-based computation, not all-pairs), Pitfall 13 (regime overfitting — parameterize thresholds, validate on 3+ pairs)
**Research flag:** The SPY residualization approach and Bonferroni correction thresholds for this specific lag range (-5 to +5) should be reviewed for the project's specific signal frequency. MEDIUM confidence on statistical tuning parameters.

### Phase 3: Signal Generation and REST API
**Rationale:** With features validated, the final signal threshold gates, position spec generation, and API delivery are straightforward. The API Lambda must be kept thin (no scipy, fast cold starts) — this is an architectural constraint from Phase 0, not an afterthought. Signal history must be written immutably: once generated, a signal is never modified.
**Delivers:** Hard threshold enforcement (stability > 70, correlation > 0.65), full position spec (entry, target, invalidation, sizing tier), signal history storage in DynamoDB (immutable), explainability payload (lag, window, correlation, stability, regime, policy_id), REST API endpoints (GET /signals/{pair}, GET /signals/active, GET /pairs/{pair}/diagnostics), fn-api Lambda with no scientific stack, daily pipeline wired end-to-end (EventBridge -> fn-ingest -> fn-normalize -> fn-features -> fn-engine -> DynamoDB -> fn-api)
**Addresses:** FEATURES.md — all P1 Phase 3 features
**Avoids:** Pitfall 6 (DynamoDB schema validated: pair_id PK, signal_date SK, adjustment_policy_id GSI), security mistakes (API Gateway auth, no raw data in API response)

### Phase 4: Backtest Validation
**Rationale:** The backtest module must be architecturally isolated from the ingestion layer before any results are treated as meaningful. Running a backtest that touches Polygon produces results that look valid but are not reproducible. This phase proves the system works by verifying signal hit rate, mean return, and stability persistence on stored historical data.
**Delivers:** BacktestDataProvider interface (reads S3 only, never Polygon), look-ahead bias prevention (splits filtered to fetched_at <= backtest_date), performance metrics (hit rate, mean return, annualized Sharpe with IID caveat, max drawdown), no-look-ahead assertion suite, import-linting CI check (backtest module cannot import ingestion module)
**Addresses:** FEATURES.md — backtest module; ARCHITECTURE.md — anti-pattern 4 (no re-querying Massive in backtest)
**Avoids:** Pitfall 2 (look-ahead bias from splits), Pitfall 8 (backtest re-querying Polygon), Pitfall 16 (Sharpe inflation)
**Research flag:** This phase has well-documented patterns. Standard walk-forward backtest design. Skip deeper research.

### Phase 5: Observability and Hardening
**Rationale:** Once the pipeline runs end-to-end, operational visibility becomes the priority. CloudWatch alarms, the pipeline_state table, DLQ for failed invocations, and error handling prevent silent failures where a bad ingestion day produces no signals with no alert.
**Delivers:** CloudWatch alarms (error rate, Lambda duration, DLQ depth), pipeline_state table population at each stage, SQS DLQ for failed invocations, retry logic hardening, data completeness validation (bar count vs expected NYSE trading days), cross-reference split records against price jumps
**Addresses:** FEATURES.md — pipeline error handling, DLQ, logging with correlation IDs
**Avoids:** Pitfall 7 (incomplete data detection), integration gotchas (DynamoDB unprocessed batch write items)

### Phase 6: Athena Analytics (parallel with Phase 4+)
**Rationale:** Can begin once normalized Parquet data exists in S3 (after Phase 1). Athena provides SQL access to all intermediate tables for debugging, auditing, and ad-hoc analysis without modifying production Lambdas.
**Delivers:** External table DDL for all Parquet tables (adjusted_bars, features_daily, features_swing), Hive-partition discovery (MSCK REPAIR TABLE or partition projection), named queries (signal audit, feature drift, backtest data extraction), Athena workgroup with cost controls
**Addresses:** ARCHITECTURE.md — Athena integration; Parquet + Snappy best practices

### Phase Ordering Rationale

- Infrastructure (Phase 0) is a hard prerequisite: Docker image must build and deploy before writing any business logic; S3 prefix structure must be finalized before data lands in it.
- Ingestion before normalization (Phase 1) because normalization needs real Polygon data to validate schema handling; fixtures do not catch API schema edge cases.
- Features before engine (Phase 2) because the lead-lag detection algorithms need real market data to verify statistical correctness; unit tests with random time series verify math but not market behavior.
- Backtest (Phase 4) after the engine (Phase 3) because it needs signal history in DynamoDB and feature data in S3 — both produced by the pipeline.
- Phases 5 and 6 are intentionally parallelizable once their dependencies exist.
- The `fetched_at` timestamp on split records (required by Phase 4's backtest) must be designed in Phase 1 even though the backtest is built in Phase 4 — this is the single most important cross-phase design dependency.

### Research Flags

Phases needing deeper research during planning:
- **Phase 1:** Polygon.io rate limits by current plan tier, exact `next_url` field behavior, and `adjusted` parameter semantics should be verified against current Polygon API documentation. MEDIUM confidence — API specifics change; structural patterns are stable.
- **Phase 2:** Statistical tuning parameters (SPY residualization approach, Bonferroni threshold with -5 to +5 lag range, OOS gap period length) warrant review before implementation. These are principled choices but project-specific calibration will be needed with real CRWV/NVDA data.

Phases with standard patterns (skip deeper research):
- **Phase 0:** Docker Lambda deployment is thoroughly documented in AWS official docs. Well-established pattern.
- **Phase 3:** REST API with API Gateway + Lambda is a standard pattern. DynamoDB key-value reads are well-documented.
- **Phase 4:** Walk-forward backtesting with architectural isolation is standard. Patterns are well-established.
- **Phase 5:** CloudWatch alarms and SQS DLQ patterns are standard AWS operational practices.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Library version numbers are training-data knowledge (May 2025 cutoff). Validate with `pip index versions <pkg>` before adoption. AWS Lambda runtimes and limits are HIGH confidence. |
| Features | MEDIUM | Polygon.io endpoint structure and pagination behavior are well-established and stable; specific rate limits by plan tier are LOW confidence and must be verified against current docs. |
| Architecture | HIGH | All architectural patterns verified against official AWS documentation (Lambda limits, DynamoDB design, S3 Athena partitioning, IAM). Patterns are stable. |
| Pitfalls | HIGH | Statistical pitfalls (look-ahead bias, spurious correlation, multiple testing) are academic/practitioner consensus — HIGH confidence. AWS packaging and DynamoDB design pitfalls are well-established — HIGH confidence. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Polygon.io current rate limits by plan tier:** Research used training data through May 2025. Exact rate limits, plan tier names, and current field names in API responses must be verified against Polygon's live documentation before writing the polygon_client.py implementation. Treat as LOW confidence.
- **Docker image size for stripped scientific Python:** The estimate of 400-500 MB for a stripped numpy + scipy + pandas + pyarrow Docker image should be validated with a test build before committing to this approach. If the image exceeds 1 GB, cold start times increase significantly.
- **arm64 vs x86_64 architecture decision:** STACK.md recommends arm64 (Graviton2, 20% cheaper). PITFALLS.md notes Docker build architecture mismatch as a common mistake. Decide on architecture before building the Docker image; do not change it after data is in S3 (the Lambda architecture affects nothing in S3, but it must be consistent across all Lambda functions).
- **stability_score (RSI-v2) formula specifics:** The composite metric is project-specific. The weights between lag persistence, regime stability, rolling confirmation, OOS validation, and lag drift penalty are not defined in research. These must be defined in the requirements document and validated empirically on CRWV/NVDA before expanding to additional pairs.
- **Exchange calendar for NYSE trading day alignment:** PITFALLS.md recommends `exchange_calendars` Python library for NYSE trading day boundaries. This library was not included in STACK.md. Verify it is available as a wheel for Lambda (AL2023 / Python 3.12) and add it to the dependency list.

## Sources

### Primary (HIGH confidence)
- AWS Lambda documentation — limits, runtimes, layers, container images, IAM, EventBridge
- AWS DynamoDB documentation — partition key design, sort key patterns, TTL, GSI design
- AWS Athena documentation — partitioning, columnar storage (Parquet + Snappy), partition projection
- AWS S3 documentation — lifecycle rules, Standard-IA tier, Athena queryability constraints (no Glacier)
- scipy.signal.correlate API — stable since scipy 1.0
- pandas rolling window API — stable since pandas 1.0
- Quantitative finance academic consensus — look-ahead bias, multiple testing correction, Bonferroni, Sharpe IID assumption

### Secondary (MEDIUM confidence)
- Polygon.io REST API documentation (training data, May 2025) — endpoint structure, pagination via next_url, `adjusted` parameter behavior; verify current docs before implementation
- NumPy 2.x breaking changes — training data from NumPy 2.0 release notes
- Lambda Docker image build patterns — community documentation, AWS blog posts
- polygon-api-client PyPI (v1.14.x, May 2025) — verify current version and maintenance status

### Tertiary (LOW confidence)
- Polygon.io rate limits by plan tier — training data; plan names and limits change; verify against current pricing page before hardcoding any rate limit values
- Python 3.13 Lambda runtime readiness — announced but adoption of scientific Python wheels on AL2023 was uncertain as of training cutoff

---
*Research completed: 2026-02-18*
*Ready for roadmap: yes*
