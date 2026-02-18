# Stack Research

**Domain:** Serverless quantitative analytics platform (AWS Lambda / Python)
**Researched:** 2026-02-18
**Confidence:** MEDIUM (versions verified against training data through May 2025; unable to verify latest releases via web due to tool restrictions -- all versions should be validated with `pip index versions <pkg>` before adoption)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12 | Runtime | AWS Lambda's most mature scientific-Python runtime as of early 2026. Python 3.13 Lambda runtime was announced but 3.12 has the broadest pre-built wheel support for numpy/scipy/pandas on Amazon Linux 2023. Avoid 3.13 until scientific stack wheels are fully battle-tested on AL2023. |
| NumPy | >=2.1, <3.0 | Array operations, correlation math | Foundation for all numerical computation. v2.x is stable and ships manylinux_2_17 wheels that work on Lambda's AL2023. The rolling window and vectorized operations are essential for cross-correlation computation. |
| pandas | >=2.2, <3.0 | Time-series DataFrames, resampling, alignment | Industry standard for financial time-series manipulation. The `DatetimeIndex` alignment, `rolling()` windows, and `shift()` for lead-lag offsets are exactly what this project needs. v2.2+ has Arrow-backed string columns reducing memory use. |
| SciPy | >=1.14, <2.0 | `scipy.signal.correlate`, `scipy.stats.pearsonr`, statistical tests | Provides `scipy.signal.correlate` and `scipy.signal.correlation_lags` for cross-correlation computation. Also `scipy.stats.pearsonr` for significance testing of correlation coefficients. No viable alternative for these signal-processing primitives. |
| boto3 | (use Lambda-bundled) | AWS SDK for S3, DynamoDB, Athena | Pre-installed in Lambda runtime -- do NOT package it in your layer. Using the runtime-bundled version avoids layer bloat and ensures compatibility with the Lambda execution environment. Pin in dev requirements for local testing only. |
| Terraform | >=1.7, <2.0 | IaC for S3, DynamoDB | Project constraint. Use for stateful resources (S3 buckets, DynamoDB tables) only. Lambda deployed via script per project spec. |

### Data Ingestion

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `requests` | >=2.31 | HTTP client for Polygon.io/Massive API | Use raw `requests` instead of `polygon-api-client`. See detailed rationale below. |
| `urllib3` | >=2.0 | Connection pooling (requests dependency) | Comes with requests. Ensure v2.x for modern TLS defaults. |

**Why `requests` over `polygon-api-client`:**

The `polygon-api-client` (maintained by Polygon.io) wraps their REST and WebSocket APIs. However, for this project:

1. **You only need aggregate bars and reference endpoints** -- 4-5 REST calls total. The client adds abstraction over trivially simple GET requests.
2. **Dependency weight matters on Lambda** -- `polygon-api-client` pulls in `websockets`, `certifi`, and other dependencies you will never use for a batch Lambda that calls REST endpoints.
3. **Version coupling risk** -- When Polygon changes their API (they renamed fields going from v2 to v3), the client library lags behind official docs. With raw `requests`, you control the parsing and adapt immediately.
4. **Your parsers are already versioned** -- The project spec calls for versioned parsers with `adjustment_policy_id` propagation. You want full control over JSON parsing, not a client library's opinionated model objects.
5. **Debugging transparency** -- When a field is missing or renamed, raw JSON + your parser is immediately inspectable. A client library adds an abstraction layer that obscures the actual API response.

**Confidence:** MEDIUM. The `polygon-api-client` was at v1.14.x as of mid-2025 and was reasonably maintained. But the rationale for raw `requests` is architectural, not about library quality.

### Database & Storage

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| S3 | (AWS managed) | Raw JSON system of record, adjusted bar storage | Immutable append-only storage for raw Polygon responses. Cheap, durable, queryable via Athena. Perfect for the "raw JSON is system of record" requirement. |
| DynamoDB | (AWS managed) | Signal storage, pair configuration, regime state | Correct choice at this scale (<100 tickers, user-seeded pairs). Single-digit millisecond reads for API Gateway signal lookups. On-demand capacity means zero cost when idle. |
| Athena | (AWS managed) | Ad-hoc queries over S3 data | Query raw/adjusted bars stored in S3 without ETL. Use for backtest data access and exploratory analysis. Parquet format recommended for cost efficiency. |

**Why DynamoDB over RDS at this scale:**

| Factor | DynamoDB | RDS (PostgreSQL) |
|--------|----------|-------------------|
| Cost at <100 tickers | ~$0/month (on-demand, low traffic) | ~$15-30/month minimum (instance always running) |
| Cold start from Lambda | No connection overhead | Connection pooling needed (RDS Proxy adds cost/complexity) |
| Operational burden | Zero (fully managed, no patching) | Instance sizing, patching, backups to manage |
| Schema flexibility | Native JSON documents | Rigid schema, migrations needed |
| Query patterns needed | Key-value lookups by pair/date | Not doing complex JOINs -- overkill |
| Serverless alignment | Native serverless service | RDS is server-based; even Aurora Serverless v2 has minimum capacity |

DynamoDB is the right choice. The query patterns here are: "get latest signal for pair X", "get all signals for date Y", "get pair configuration". These are key-value lookups, not relational queries.

**When to reconsider RDS:** If you add all-pairs exhaustive computation (O(n^2) relationships) and need complex JOIN queries across the correlation matrix. That is explicitly out of scope.

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyarrow` | >=15.0 | Parquet read/write for S3 storage | Convert adjusted bars to Parquet before S3 storage. Athena queries Parquet 10-100x cheaper than JSON due to columnar pruning. Required for pandas Arrow-backed dtypes. |
| `pytest` | >=8.0 | Test framework | All unit and integration tests. Use `pytest-xdist` for parallel test execution. |
| `pytest-mock` | >=3.12 | Mocking for tests | Mock S3/DynamoDB/API calls in unit tests. Use alongside `moto` for AWS service mocking. |
| `moto` | >=5.0 | AWS service mocking | Mock S3, DynamoDB, Lambda in tests without hitting real AWS. Essential for testing the full pipeline locally. |
| `pydantic` | >=2.6 | Data validation, signal schema | Validate signal payloads, pair configurations, API responses. V2 is dramatically faster than V1. Use for all internal data contracts between modules. |
| `structlog` | >=24.1 | Structured logging | JSON-structured logs that work well with CloudWatch Logs Insights. Essential for debugging Lambda executions in production. |
| `mypy` | >=1.8 | Static type checking | Catch type errors in numerical code before runtime. Critical when passing arrays/DataFrames between modules. |
| `ruff` | >=0.3 | Linter + formatter | Replaces flake8 + black + isort. Single tool, extremely fast. |
| `aws-lambda-powertools` | >=2.35 (Python) | Lambda middleware | Provides structured logging, tracing, event parsing, idempotency for Lambda. Replaces boilerplate in every handler. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `uv` | Python package management + virtual environments | 10-100x faster than pip. Handles dependency resolution and virtual environments. Use `uv pip compile` to generate locked requirements for Lambda layers. Already present in project (uv.lock exists). |
| `docker` | Lambda layer building | Build numpy/scipy/pandas layers in an `amazonlinux:2023` container to ensure binary compatibility. Do NOT build on Windows/Mac and deploy -- the compiled C extensions will not work. |
| `aws-sam-local` or `localstack` | Local Lambda testing | Test Lambda functions locally before deploying. SAM CLI is lighter; LocalStack is more comprehensive but heavier. Recommend SAM CLI for this project's scope. |
| `terraform` | Infrastructure as Code | S3 buckets, DynamoDB tables, IAM roles. Per project constraint, Lambda deployed via script (not Terraform). |

---

## Lambda Packaging: The Critical Constraint

This is the single most important technical decision for this project. Scientific Python on Lambda is well-understood but has sharp edges.

### Lambda Layer Size Limits

| Limit | Value | Impact |
|-------|-------|--------|
| Deployment package (zipped) | 50 MB | Your function code + all layers combined |
| Unzipped deployment package | 250 MB | Total extracted size of all layers + function code |
| Single layer (zipped) | 50 MB | Per-layer zip file limit |
| Maximum layers per function | 5 | Can split across multiple layers |
| `/tmp` storage | 512 MB (default), up to 10 GB (configurable) | Can download large dependencies at cold start if needed |

### Packaging Strategy: Two Lambda Layers

**Layer 1: Scientific Python (~45-48 MB zipped)**
- numpy
- scipy
- pandas
- pyarrow

**Layer 2: Application Dependencies (~5-10 MB zipped)**
- requests
- pydantic
- structlog
- aws-lambda-powertools

**Why two layers:**
1. Scientific Python layer changes rarely (pin versions, rebuild quarterly)
2. Application dependencies change more often
3. Separating them means most deploys only update the small layer
4. Both fit within the 50 MB per-layer zip limit

### Building the Scientific Layer

```bash
# MUST build on Amazon Linux 2023 (matching Lambda runtime)
docker run --rm -v $(pwd)/layer:/out amazonlinux:2023 bash -c "
  dnf install -y python3.12 python3.12-pip zip
  python3.12 -m pip install \
    numpy>=2.1,<3 \
    scipy>=1.14,<2 \
    pandas>=2.2,<3 \
    pyarrow>=15,<16 \
    -t /out/python/lib/python3.12/site-packages/ \
    --platform manylinux2014_x86_64 \
    --only-binary=:all:
  cd /out && zip -r9 /out/scientific-layer.zip python/
"
```

**Critical: arm64 vs x86_64**

Use **arm64 (Graviton2)** for Lambda:
- 20% cheaper per ms than x86_64
- Comparable or better performance for numerical workloads
- Change `--platform` to `manylinux2014_aarch64` and set Lambda architecture to `arm64`
- NumPy/SciPy/pandas all ship aarch64 wheels

### Cold Start Impact

| Configuration | Cold Start | Warm Invocation |
|---------------|------------|-----------------|
| Python 3.12 + scientific layer (x86_64) | ~3-5 seconds | ~100-500ms |
| Python 3.12 + scientific layer (arm64) | ~2-4 seconds | ~80-400ms |
| With Provisioned Concurrency (1) | <100ms (always warm) | ~80-400ms |

**For daily batch execution (MVP), cold start does not matter.** The Lambda runs once per day on a schedule. A 3-5 second cold start on a job that runs for 30-120 seconds is irrelevant. Do NOT waste money on Provisioned Concurrency for batch Lambdas.

**For API Gateway signal lookups, cold start matters.** The `/signals` endpoint should be a separate, lightweight Lambda that reads from DynamoDB only -- no numpy/scipy/pandas layer needed. This gives sub-second cold starts.

**Architecture implication:** Separate your compute Lambdas (need scientific layer) from your API Lambdas (only need boto3 + pydantic). This is the single most impactful architecture decision for performance.

### Memory Configuration

| Lambda Function | Recommended Memory | Rationale |
|-----------------|-------------------|-----------|
| Ingestion (Polygon fetch) | 256 MB | Network-bound, minimal computation |
| Normalization / Adjustment | 512 MB | DataFrame operations on <100 tickers |
| Feature Computation | 1024 MB | Rolling windows, cross-correlation on time series |
| Lead-Lag Engine | 1024 MB | The heaviest computation -- cross-correlation across lags |
| Signal Generation | 512 MB | Threshold application, position spec construction |
| API Handler | 256 MB | DynamoDB reads only, no scientific computation |

**Why 1024 MB for compute Lambdas:** Lambda allocates CPU proportional to memory. At 1024 MB you get roughly 0.6 vCPU. Below this, numpy/scipy operations become CPU-starved and wall-clock time increases, often costing MORE than a higher-memory configuration due to per-ms billing. Profile and adjust.

---

## Cross-Correlation and Lead-Lag Computation

This is the mathematical core of the project. Here is the recommended implementation approach.

### Primary: scipy.signal.correlate + pandas.rolling

```python
import numpy as np
import pandas as pd
from scipy import signal

def rolling_cross_correlation(
    leader: pd.Series,
    follower: pd.Series,
    window: int = 60,
    max_lag: int = 10
) -> pd.DataFrame:
    """
    Compute rolling cross-correlation between leader and follower
    returns over a sliding window, for lags from -max_lag to +max_lag.
    """
    results = []
    for end in range(window, len(leader) + 1):
        start = end - window
        l_slice = leader.iloc[start:end].values
        f_slice = follower.iloc[start:end].values

        # Normalize (z-score) to get correlation not covariance
        l_norm = (l_slice - l_slice.mean()) / (l_slice.std() + 1e-10)
        f_norm = (f_slice - f_slice.mean()) / (f_slice.std() + 1e-10)

        # Full cross-correlation
        corr = signal.correlate(l_norm, f_norm, mode='full') / window
        lags = signal.correlation_lags(len(l_norm), len(f_norm), mode='full')

        # Extract lags of interest
        mask = (lags >= -max_lag) & (lags <= max_lag)
        results.append({
            'date': leader.index[end - 1],
            'lags': lags[mask],
            'correlations': corr[mask],
            'peak_lag': lags[mask][np.argmax(np.abs(corr[mask]))],
            'peak_corr': corr[mask][np.argmax(np.abs(corr[mask]))]
        })

    return pd.DataFrame(results)
```

### Why NOT a dedicated lead-lag library

There is no well-maintained, production-quality Python library specifically for financial lead-lag analysis. The options:

| Library | Status | Why Not |
|---------|--------|---------|
| `lead-lag` (on PyPI) | Low maintenance, few stars | Thin wrapper around scipy.signal.correlate. You gain nothing and add a dependency. |
| `tsfresh` | Active, feature extraction | Overkill -- extracts 700+ features. You need exactly one: cross-correlation at specific lags. |
| `tslearn` | Active, time series ML | Focused on DTW and clustering, not financial lead-lag detection. |
| `stumpy` | Active, matrix profile | Matrix profile is for motif/anomaly detection, not cross-correlation lead-lag. |

**The right approach:** Build your lead-lag engine directly on scipy.signal.correlate + numpy + pandas. The math is straightforward (normalized cross-correlation), and wrapping it yourself gives you full control over:
- Window sizes
- Lag ranges
- Normalization method
- Significance testing (scipy.stats.pearsonr for p-values)
- The stability_score formula (which is custom to this project)

This is a 200-300 line module, not a library selection problem.

---

## Installation

```bash
# Project setup with uv (already initialized)
uv init  # if not already done
uv add numpy ">=2.1,<3" pandas ">=2.2,<3" scipy ">=1.14,<2"
uv add pyarrow ">=15,<16" requests ">=2.31"
uv add pydantic ">=2.6" structlog ">=24.1" aws-lambda-powertools ">=2.35"

# Dev dependencies
uv add --dev pytest ">=8.0" pytest-mock ">=3.12" pytest-xdist ">=3.5"
uv add --dev moto ">=5.0" mypy ">=1.8" ruff ">=0.3"
uv add --dev boto3-stubs  # type stubs for boto3

# boto3 is NOT installed as a project dependency
# It is pre-installed in Lambda runtime
# Only install for local development/testing:
uv add --dev boto3
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `requests` for Polygon API | `polygon-api-client` | If you later need WebSocket streaming (Phase 2 intraday), the client's async WebSocket support becomes valuable. Re-evaluate at that point. |
| `pandas` DataFrames | `polars` | If DataFrames exceed Lambda memory (unlikely at <100 tickers). Polars is faster but pandas has deeper ecosystem integration with scipy/numpy and more familiar API for quant work. |
| DynamoDB for signals | PostgreSQL (RDS) | If you add complex relational queries (JOIN across correlation matrices, ad-hoc SQL). Not needed for key-value signal lookups. |
| S3 + Athena for bar storage | TimescaleDB | If you need real-time continuous aggregates or complex time-series SQL. Overkill for daily batch processing of <100 tickers. Also not serverless. |
| `scipy.signal.correlate` | `numpy.correlate` | Never. `numpy.correlate` does not support `mode='full'` with proper lag computation. `scipy.signal.correlate` + `correlation_lags` is strictly superior. |
| `uv` for packaging | `pip` + `pip-tools` | Never for this project. `uv` is already initialized (uv.lock present). It is faster and handles dependency resolution better. |
| arm64 Lambda | x86_64 Lambda | Only if a dependency lacks aarch64 wheels. All recommended packages have arm64 wheels. |
| SAM CLI for local testing | LocalStack | If you need to test Step Functions, EventBridge, or other complex service interactions locally. For Lambda + S3 + DynamoDB, SAM CLI is sufficient and lighter. |
| `pydantic` v2 | `dataclasses` + manual validation | Never for this project. The signal payloads have nested structures and strict validation requirements. Pydantic's JSON serialization and validator ecosystem justify the dependency. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `polygon-api-client` | Adds websocket dependencies, opinionated model objects, version coupling for 4-5 simple REST calls | `requests` with your own versioned parsers |
| `numpy.correlate` | Missing `mode='full'` lag semantics, no `correlation_lags` companion function | `scipy.signal.correlate` + `scipy.signal.correlation_lags` |
| `tsfresh` | Extracts 700+ features when you need exactly one (cross-correlation). Massive dependency that will blow Lambda layer limits. | Direct scipy.signal + custom rolling code |
| `dask` or `spark` on Lambda | Lambda is single-invocation, not a distributed compute cluster. Dask/Spark overhead is enormous for <100 tickers. | Plain numpy/pandas -- your data fits in memory with room to spare |
| `TA-Lib` (Technical Analysis Library) | Notoriously painful to compile on Lambda (C dependency, no manylinux wheel). You only need MA, ATR, and volume metrics which are trivial in pandas. | `pandas.DataFrame.rolling().mean()`, manual ATR calculation |
| `SQLAlchemy` + RDS | Connection pooling headaches on Lambda, idle instance cost, operational overhead -- all for key-value lookups that DynamoDB handles natively | DynamoDB with boto3 |
| `pandas_ta` or `ta` | Additional dependencies for indicators you can compute in 5 lines of pandas. Adds Lambda layer bloat. | Manual indicator computation in pandas |
| `pickle` for serialization | Not portable across Python versions, security risk for deserialization, not queryable | Parquet (pyarrow) for DataFrames, JSON for small objects |
| `terraform` for Lambda | Project spec says Lambda via script. Managing Lambda code + layers via Terraform creates painful deploy cycles. | Deploy script for Lambda; Terraform for stateful resources only |
| `boto3` in Lambda layer | Pre-installed in Lambda runtime. Including it wastes layer space and can cause version conflicts. | Use runtime-provided boto3; pin in dev dependencies for local testing |
| Python 3.13 on Lambda | Scientific Python wheel ecosystem still maturing on 3.13 + AL2023. Risk of missing wheels at deploy time. | Python 3.12 -- fully mature wheel support |

---

## Stack Patterns by Variant

**If staying with daily batch only (MVP):**
- Use CloudWatch Events (EventBridge) scheduled rule to trigger Lambda
- No need for SQS, SNS, or Step Functions
- Single sequential pipeline: ingest -> normalize -> compute features -> lead-lag -> signals -> store
- Each step can be a separate Lambda or modules in one Lambda (prefer separate for memory optimization)

**If adding intraday / 5-min bars (Phase 2):**
- Re-evaluate `polygon-api-client` for WebSocket streaming support
- Consider Step Functions to orchestrate the pipeline with error handling
- Will need SQS between ingestion and computation for buffering
- May need to re-evaluate `polars` over `pandas` if data volume increases significantly
- Lambda 15-minute timeout becomes a constraint -- may need Fargate for long-running computations

**If adding more than 100 tickers (scale-up):**
- DynamoDB remains fine (designed for scale)
- S3 + Athena remains fine (designed for scale)
- Lambda fan-out pattern: one Lambda per pair for parallel computation
- Consider Step Functions Map state for parallel pair processing
- Memory may need increase to 2048 MB for larger correlation matrices

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| numpy >=2.1 | scipy >=1.14 | scipy 1.14+ requires numpy 2.x. Do not mix numpy 1.x with scipy 1.14+. |
| numpy >=2.1 | pandas >=2.2 | pandas 2.2+ fully supports numpy 2.x. |
| pandas >=2.2 | pyarrow >=15.0 | pandas Arrow-backed dtypes require pyarrow 15+. |
| scipy >=1.14 | Python 3.12 | scipy 1.14 added Python 3.12 wheels. |
| pydantic >=2.6 | Python 3.12 | Full Python 3.12 support. |
| moto >=5.0 | boto3 (latest) | moto 5.x tracks latest boto3 API changes. |
| aws-lambda-powertools >=2.35 | Python 3.12 | Full Python 3.12 support, Pydantic v2 integration. |

**Critical compatibility note:** NumPy 2.x is a breaking change from NumPy 1.x. All C-extension packages (scipy, pandas) must be compiled against NumPy 2.x. Using pre-built wheels (as recommended) ensures this. Do NOT compile from source unless you verify ABI compatibility.

---

## Testing Strategy for Financial Time-Series Code

| Test Type | Tool | What to Test |
|-----------|------|-------------|
| Unit tests | `pytest` | Mathematical correctness of cross-correlation, lead-lag detection, stability score, regime classification |
| Property-based tests | `hypothesis` (optional) | Generate random time series and verify mathematical invariants (e.g., autocorrelation at lag 0 = 1.0) |
| AWS mocking | `moto` | S3 read/write, DynamoDB put/get/query, Lambda invocation |
| Snapshot tests | `pytest` + JSON fixtures | Known-good signal outputs from reference pairs (CRWV/NVDA). Store expected output, compare on every test run. |
| Integration tests | SAM CLI local invoke | Full pipeline execution against mocked or local AWS services |
| Backtest validation | Custom assertions | No look-ahead bias verification, returns_policy_a exclusivity, no future split leakage |

**Key testing principle for quant code:** Every mathematical function should have a test with hand-computed expected values. If you cannot compute the expected correlation by hand for a 5-element test vector, the function is not tested.

---

## Sources

- Training data knowledge (May 2025 cutoff) -- **all version numbers should be validated with `pip index versions <package>` before adoption**
- AWS Lambda documentation (limits, runtimes, layers) -- MEDIUM confidence, verified against training data; check https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html for latest
- scipy.signal.correlate API -- HIGH confidence, stable API since scipy 1.0
- pandas rolling window API -- HIGH confidence, stable API since pandas 1.0
- NumPy 2.x breaking changes -- MEDIUM confidence, verified against NumPy 2.0 release notes in training data
- polygon-api-client PyPI page -- MEDIUM confidence, v1.14.x was latest in training data; verify current version
- Terraform AWS provider -- HIGH confidence, well-established patterns
- Lambda layer packaging -- HIGH confidence from extensive community documentation and AWS official guides

**Confidence notes:**
- Library version numbers: MEDIUM -- these are my best knowledge as of May 2025. Patch versions have certainly advanced. Run `pip index versions <pkg>` to get current.
- AWS Lambda Python 3.12 support: HIGH -- was GA well before my training cutoff.
- AWS Lambda Python 3.13 support: LOW -- was announced but adoption status of scientific wheels uncertain. Verify before using.
- scipy.signal.correlate API stability: HIGH -- this API has been stable for years and is the standard approach.
- DynamoDB vs RDS recommendation: HIGH -- the architectural rationale is independent of version numbers.
- Lambda layer size limits: HIGH -- these are fundamental AWS limits that change rarely (50 MB zipped, 250 MB unzipped).

---
*Stack research for: Lead-Lag Quant -- Serverless AWS Quantitative Analytics Platform*
*Researched: 2026-02-18*
