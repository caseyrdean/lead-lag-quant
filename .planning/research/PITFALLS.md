# Pitfalls Research

**Domain:** Serverless Quantitative Lead-Lag Analytics Platform
**Researched:** 2026-02-18
**Confidence:** MEDIUM-HIGH (training data; unable to verify against live sources due to tool restrictions, but these are well-established domain patterns that change slowly)

---

## Critical Pitfalls

Mistakes that cause incorrect signals, unreproducible results, or platform rewrites.

---

### Pitfall 1: Dividend Contamination in Returns (Adjustment Policy A Violation)

**What goes wrong:**
Polygon.io's `adjusted=true` parameter applies BOTH split AND dividend adjustments to historical prices. If you request adjusted data from the API, you silently get dividend-adjusted close prices baked in. Computing returns from these prices violates Adjustment Policy A (split-only), and every downstream signal -- correlation, lead-lag, stability score -- is computed on contaminated data. The contamination is subtle: prices differ by only a few percent from the correct values, so signals "look reasonable" but are wrong.

**Why it happens:**
- Polygon's `adjusted` parameter is a boolean, not a selector. There is no `adjusted=splits_only` option. The flag applies all corporate action adjustments or none.
- Developers assume "adjusted" means split-adjusted and don't read the docs closely.
- The difference between split+dividend adjusted and split-only adjusted is small in absolute terms for most stocks over short windows, so casual inspection doesn't catch it.

**How to avoid:**
1. **Ingest UNADJUSTED data only** (`adjusted=false` on all Polygon aggregate bar requests). Store raw unadjusted OHLCV as the system of record in S3.
2. **Fetch split records separately** from `/v3/reference/splits` and apply them deterministically in your own normalization layer.
3. **Fetch dividend records separately** from `/v3/reference/dividends` and store them in their own table, NEVER used in returns computation for Policy A.
4. **Assertion in the normalization pipeline:** `assert adjustment_policy_id == "A"` and `assert "dividend" not in adjustment_factors` at the point where adjusted prices are computed.
5. **Integration test:** For a known ticker with a known dividend (e.g., pick one from your universe), verify that `returns_policy_a` differs from Polygon's `adjusted=true` returns by exactly the dividend factor.

**Warning signs:**
- Returns for a known dividend-paying stock exactly match Polygon `adjusted=true` returns.
- No separate `corporate_actions_dividends` table exists or is empty.
- The normalization code path has no `adjustment_policy_id` parameter.
- Any code path that calls Polygon with `adjusted=true`.

**Phase to address:** Phase 1 (Data Ingestion & Normalization) -- this must be correct from day one. Every downstream computation depends on it.

---

### Pitfall 2: Look-Ahead Bias from Future Split Data Leaking into Historical Computations

**What goes wrong:**
A stock splits 4:1 on June 15. When you fetch split records from Polygon, you get the complete history including this June 15 split. If your normalization pipeline runs on January 1 data but applies the June 15 split factor retroactively, the January prices are "correct" in hindsight but represent information that was unavailable on January 1. Backtesting with these prices introduces look-ahead bias: the system appears to work because it had future information.

**Why it happens:**
- Split adjustment is typically applied retroactively -- that's how financial data providers work. The confusion is about WHEN you knew the split would happen.
- Point-in-time (PIT) data is hard. Most financial data providers give you the "latest" view, not the view as-of a historical date.
- Developers apply all known splits to all historical data in a single pass, which is the standard approach for analysis but poison for backtesting.

**How to avoid:**
1. **Snapshot split records with fetch timestamps.** When you ingest splits from Polygon, store the `fetched_at` timestamp alongside each split record. This creates a point-in-time record of what you knew and when.
2. **Backtest rule: only apply splits known before the backtest date.** When computing `adjusted_bars_policy_a` for a backtest running as-of date T, filter splits to `execution_date <= T` AND `fetched_at <= T`.
3. **For live daily signals (non-backtest):** Apply all known splits retroactively. This is correct because you genuinely know them now.
4. **Separate backtest adjustment path:** `adjust_for_backtest(bars, as_of_date)` vs `adjust_for_live(bars)`. Make the distinction explicit in code.
5. **Never re-query Massive during backtests** (already in project constraints) -- but also never use the "latest" split table. Use the snapshotted version.

**Warning signs:**
- Split records table has no `fetched_at` or `known_as_of` column.
- Backtest code uses the same adjustment function as live code with no date filtering.
- Backtest hit rates are suspiciously high (90%+) on in-sample data but collapse out-of-sample.
- No distinction between "splits known at time T" and "all splits ever" in the codebase.

**Phase to address:** Phase 1 (Data Ingestion) for snapshotting, Phase 4 (Backtest) for enforcement. Must be designed in Phase 1 even if backtest is built later.

---

### Pitfall 3: Spurious Cross-Correlation in Lead-Lag Detection

**What goes wrong:**
Cross-correlation analysis finds "significant" lead-lag relationships that are actually artifacts of:
- **Common factor exposure:** Both stocks move with the S&P 500. Removing market returns eliminates the apparent lead-lag.
- **Autocorrelation in returns:** If stock A has momentum (autocorrelation), it will spuriously cross-correlate with stock B at various lags.
- **Short window over-fitting:** A 20-day rolling cross-correlation window has very few degrees of freedom. With 5 lags tested, you're doing 10 hypothesis tests on 20 data points. Spurious significance is almost guaranteed.
- **Non-stationarity:** A lead-lag relationship that held during a volatility regime (e.g., Q1 2025 tariff shock) vanishes when the regime ends.

**Why it happens:**
- Cross-correlation is a blunt instrument that does not control for confounders.
- Financial time series are notoriously non-stationary.
- Multiple testing correction (Bonferroni, BH) is rarely applied in quick analytics pipelines.
- Small sample sizes in rolling windows give high variance estimates.

**How to avoid:**
1. **Residualize returns before cross-correlation.** Regress both series against a common factor (SPY returns at minimum) and compute cross-correlation on residuals. This removes the "both track the market" artifact.
2. **Minimum window size:** Use at least 60 trading days (3 months) for rolling cross-correlation. 20 days is too noisy.
3. **Multiple testing correction:** When testing lags -5 through +5 (11 tests), apply Bonferroni correction: significance threshold = 0.05/11 = 0.0045, not 0.05. Or use Benjamini-Hochberg FDR control.
4. **Stability score (RSI-v2) is the right approach** -- but the lag drift penalty must be large enough to kill relationships that flip direction. A relationship that is lag +2 one month and lag -1 the next month is noise, not signal.
5. **Out-of-sample validation is mandatory.** The stability_score must include an out-of-sample window (already in spec), but be rigorous: the OOS window must be strictly non-overlapping with the estimation window, with a gap period.
6. **Hard minimum for correlation_strength > 0.65** (already in spec) is good. Also require p-value < 0.01 (not just 0.05) given the multiple testing context.

**Warning signs:**
- Most seeded pairs show "significant" lead-lag at some lag. (If >50% of pairs are significant, your threshold is too loose.)
- Lead-lag direction flips frequently (lag +2 becomes lag -2 within a month).
- Removing SPY factor exposure kills most signals.
- stability_score is high but out-of-sample hit rate is below 55%.

**Phase to address:** Phase 2 (Feature Engineering & Lead-Lag Engine). This is the statistical heart of the system. Get it wrong and everything downstream is garbage.

---

### Pitfall 4: Look-Ahead Bias in Stability Score Out-of-Sample Validation

**What goes wrong:**
The stability_score (RSI-v2) includes an out-of-sample validation component. If the out-of-sample window overlaps with the estimation window, or if the stability score is re-computed with a sliding window that incorporates data that was previously "out-of-sample," you get information leakage. The score looks validated but is actually in-sample.

A subtler form: the out-of-sample window is non-overlapping, but the rolling computation is updated daily. Yesterday's "out-of-sample" data becomes part of today's estimation window. Over time, every data point has been both in-sample and out-of-sample, defeating the purpose.

**Why it happens:**
- Rolling window implementations naturally slide forward, converting old OOS data into IS data.
- The concept of "out-of-sample" in a production (non-backtest) system is philosophically different from academic backtesting.
- It feels wasteful to have a gap period that "wastes" data.

**How to avoid:**
1. **Fixed gap between estimation and validation windows.** If estimation window is [T-80, T-20], the validation window is [T-10, T], with [T-20, T-10] as a dead zone. The dead zone prevents edge-of-window leakage.
2. **For live daily computation:** Accept that the "out-of-sample" component is a sliding walk-forward test, not a true OOS test. Name it `walk_forward_score` not `oos_score` to avoid self-deception.
3. **For backtest:** Use expanding window with blocked cross-validation: train on [0, T], gap [T, T+G], test on [T+G, T+G+V]. Never reuse test data.
4. **Log the exact windows used** for each stability_score computation. If auditing shows overlap, flag it.

**Warning signs:**
- No gap between estimation and validation window.
- Validation window length is configurable but defaults to 0.
- stability_score is always high (>80) -- suggests it's not actually testing anything.
- Backtest results are insensitive to the validation window length (changing 5 days to 20 days doesn't change results).

**Phase to address:** Phase 2 (Feature Engineering) for design, Phase 4 (Backtest) for verification.

---

### Pitfall 5: AWS Lambda Deployment Package Size Limits for Scientific Python

**What goes wrong:**
numpy + scipy + pandas together exceed 250 MB (the Lambda uncompressed deployment package limit). The deployment fails, or you strip dependencies and get runtime ImportError. Docker-based Lambda (container image) has a 10 GB limit, but cold starts increase significantly with image size.

**Why it happens:**
- numpy alone is ~30 MB. scipy is ~40-80 MB. pandas is ~50 MB. With transitive dependencies (openpyxl, etc.) you hit 250 MB easily.
- Lambda's 250 MB limit applies to the UNZIPPED deployment package in the `/opt` and function directories combined.
- Lambda Layers help organize but each layer still counts toward the 250 MB total.
- Developers try the simple `pip install -t .` + `zip` approach first and hit the wall.

**How to avoid:**
1. **Use Lambda container images (Docker).** This raises the limit to 10 GB and eliminates packaging pain entirely. Use the `public.ecr.aws/lambda/python:3.12` base image and `pip install` your dependencies normally.
2. **Strip unnecessary files in Docker build:** Remove `__pycache__`, `.pyc`, `tests/` directories, and unused scipy submodules. A stripped numpy+scipy+pandas image is ~400-500 MB, well within the 10 GB limit.
3. **Pre-build the layer for Lambda Layers approach:** Use `manylinux` wheels or build in a Docker container matching the Lambda runtime (Amazon Linux 2023). Never build on Windows/Mac and deploy to Lambda.
4. **Consider AWS-maintained layers:** AWS provides a "AWS SDK for pandas" (formerly AWS Data Wrangler) layer that includes pandas and numpy pre-packaged. Verify it meets your version requirements.
5. **Memory allocation:** numpy/scipy operations on correlation matrices need RAM. Set Lambda memory to at least 1024 MB (ideally 2048 MB) for the computation Lambdas. Lambda CPU scales linearly with memory.

**Warning signs:**
- Deployment fails with "Unzipped size must be smaller than 262144000 bytes."
- `ImportError: No module named 'scipy'` at runtime.
- Cold start times >10 seconds (image is too large or memory too low).
- Inconsistent behavior between local and Lambda (built on wrong architecture).

**Phase to address:** Phase 0 (Infrastructure Setup). Solve packaging once, early, before writing business logic.

---

### Pitfall 6: DynamoDB Hot Partition on Time-Series Signal Writes

**What goes wrong:**
DynamoDB distributes data across partitions based on the partition key hash. If your partition key is `date` (e.g., `2026-02-18`), then all writes for a daily batch land on the same partition. DynamoDB provisions throughput per-partition (each partition supports up to ~1000 WCU and 3000 RCU). During a daily batch run, all signal writes for all pairs hit one partition, causing `ProvisionedThroughputExceededException` or throttling under on-demand capacity.

**Why it happens:**
- Time-series data is naturally ordered by time. The naive schema design uses `date` as the partition key.
- DynamoDB documentation warns against this, but the anti-pattern is tempting because queries are naturally "give me all signals for date X."
- With <100 tickers and seeded pairs, you might have 50-200 signal writes per day. This is actually low enough that it might NOT hit throttling under on-demand mode -- but the design is still fragile.

**How to avoid:**
1. **Use `ticker_pair` as the partition key and `date` as the sort key.** Schema: `PK=CRWV#NVDA, SK=2026-02-18`. This distributes writes across partitions by pair, not by date. Query pattern "all signals for pair X in date range" is a simple range query.
2. **For "all signals on date X" queries** (which now require a scan or GSI): create a GSI with `date` as the partition key. GSIs handle hot partitions better because they're designed for query patterns, and you can accept slightly stale reads.
3. **Use on-demand capacity mode** for the signal tables. With <200 writes per daily batch, on-demand is cheaper than provisioned and handles bursts without throttling.
4. **TTL for signal expiry:** Add a `ttl` attribute (epoch seconds) set to signal_date + retention_period (e.g., 180 days). DynamoDB TTL deletes are free and automatic. This prevents table growth from becoming a cost problem.
5. **Alternative: use S3 + Athena for signal storage** instead of DynamoDB. For a daily-batch, read-heavy-after-write workload, Parquet files in S3 queried by Athena may be simpler and cheaper than DynamoDB. DynamoDB shines for low-latency point reads; if you only need signals for API reads, DynamoDB is fine, but batch analytics should query S3/Athena.

**Warning signs:**
- Partition key is `date` or `YYYYMMDD`.
- `ThrottlingException` during daily batch runs.
- All items for a single day have the same partition key.
- No TTL attribute on signal items.

**Phase to address:** Phase 1 (Data Ingestion / Storage Schema Design). Table schema is extremely hard to change after data is in DynamoDB.

---

### Pitfall 7: Polygon.io Rate Limiting, Pagination Truncation, and Incomplete Data

**What goes wrong:**
Multiple failure modes compound:
1. **Rate limiting:** Polygon enforces per-minute rate limits (varies by plan: 5 req/min on free, unlimited on paid plans). Without backoff, your ingestion pipeline gets 429 errors and silently skips tickers.
2. **Pagination truncation:** The aggregates endpoint returns a maximum number of results per request (typically 50,000 bars). If you request 10 years of daily data for one ticker, you get it in one request (~2,520 bars). But if you request 1-minute bars for a year, you need to paginate via `next_url`. If your code doesn't follow pagination, you get truncated data.
3. **Missing data:** Polygon may not have data for all dates (holidays, halted tickers, newly listed stocks). Your pipeline must distinguish "no data because market was closed" from "no data because API failed."
4. **Split record completeness:** Polygon's `/v3/reference/splits` may have incomplete records for very old splits or recently listed tickers. If a split is missing, your adjustment is wrong for the entire history of that ticker.

**Why it happens:**
- Developers test with 1 ticker over 1 year and everything works. Scale to 100 tickers and rate limits hit.
- Pagination logic is "I'll add it later" and never gets added.
- Holiday detection is surprisingly complex (half-days, early closes, special closures).
- Split completeness is assumed but not verified.

**How to avoid:**
1. **Exponential backoff with jitter on 429 responses.** Sleep = min(60, base * 2^attempt + random(0, 1)). Max 5 retries.
2. **Always follow `next_url` in paginated responses.** Write a generic `paginate_all(url)` helper that follows `next_url` until it's absent. Never assume a single request returns all data.
3. **Validate data completeness after ingestion:** Count business days (excluding known holidays) in the requested range. If received bars < expected business days * 0.95, flag the ticker for review.
4. **Cross-reference split records against price jumps.** If a stock's close-to-open ratio is >1.5x or <0.67x without a corresponding split record, flag it as a potential missing split.
5. **Store raw API responses in S3** (already in spec). This enables re-processing if you discover a bug in ingestion, without re-querying Polygon.
6. **Separate ingestion from processing.** Ingest all data first, validate completeness, then run normalization. Don't normalize in-flight.

**Warning signs:**
- `429 Too Many Requests` in logs.
- Ticker has 200 bars when you expected 252 (missing ~50 days).
- A stock's adjusted price series has a sudden 2x or 0.5x jump (missing split).
- `next_url` is never used in the ingestion code.

**Phase to address:** Phase 1 (Data Ingestion). This is the foundation. Bad data in = bad signals out.

---

### Pitfall 8: Backtest Module Re-Querying External APIs

**What goes wrong:**
The backtest module calls Polygon.io (or any external data source) during a backtest run. This means:
1. Results are not reproducible (API data may change -- corrections, restatements).
2. Backtest results depend on current API state, not historical state.
3. Rate limits can cause backtest failures mid-run.
4. Subtle look-ahead: the API returns the "latest" view of corporate actions, not the point-in-time view.

**Why it happens:**
- Reusing ingestion code in the backtest path is convenient.
- "I'll just fetch the data I need" is simpler than building a local data store query layer.
- The backtest initially works because the data is the same; the bug surfaces weeks later when data changes.

**How to avoid:**
1. **Architectural boundary:** The backtest module MUST NOT import or call any module from the ingestion layer. Enforce this with import linting (e.g., `import-linter` or a simple grep in CI).
2. **Backtest reads from S3/DynamoDB only.** Define a `BacktestDataProvider` interface that reads exclusively from stored data. The live pipeline has a `LiveDataProvider` that calls Polygon.
3. **No network calls in backtest.** In test mode, mock all network access or run with network disabled (Lambda can't enforce this, but a test wrapper can).
4. **Checksums on backtest input data.** Hash the input dataset at the start of a backtest run. If the same backtest produces different results with the same hash, you have a non-determinism bug.

**Warning signs:**
- Backtest code imports from the ingestion module.
- Backtest runtime varies significantly between runs (network latency).
- Backtest results change when run a week later on the same date range.
- CloudWatch logs show Polygon API calls during backtest Lambda invocations.

**Phase to address:** Phase 4 (Backtest Module). Design the data provider interface in Phase 1, enforce it in Phase 4.

---

## Moderate Pitfalls

---

### Pitfall 9: Timezone and Timestamp Normalization Errors

**What goes wrong:**
Polygon.io returns timestamps in Unix milliseconds (UTC). US equity markets trade in Eastern Time. Daylight Saving Time shifts EST (UTC-5) to EDT (UTC-4) twice a year. If your pipeline naively converts timestamps or groups by calendar date, bars can land on the wrong trading day during DST transitions.

**Prevention:**
1. **Store all timestamps in UTC internally.** Never convert to local time until display.
2. **Define "trading day" as the NYSE calendar date**, not the UTC date. Use a library like `exchange_calendars` (Python) to determine trading day boundaries.
3. **Be explicit about bar semantics:** A daily bar for 2026-02-18 represents trading on that NYSE trading day, regardless of UTC date boundaries.
4. **Test DST transition dates specifically:** March and November dates where UTC midnight falls in a different trading day than expected.

**Warning signs:**
- Missing or duplicate bars around March/November DST transitions.
- A bar dated "2026-03-09" appears to have 0 volume (it was assigned to the wrong day).
- Off-by-one errors in date-range queries.

**Phase to address:** Phase 1 (Data Ingestion / Normalization).

---

### Pitfall 10: Lambda Cold Start Latency for Daily Batch Workflows

**What goes wrong:**
Lambda cold starts for a Docker container with scientific Python can be 5-15 seconds. For a daily batch job that processes 100 tickers, each invocation's cold start adds up. If you invoke Lambdas serially, the job takes 25-50 minutes. If you invoke in parallel, you hit Lambda concurrency limits.

**Prevention:**
1. **Batch processing within a single Lambda invocation** where possible. Process all tickers in one invocation instead of one-ticker-per-invocation. With 2048 MB memory, you can handle 100 tickers in-memory easily.
2. **Use provisioned concurrency** for the daily batch Lambda if cold starts are unacceptable (costs money but guarantees warm starts).
3. **Separate hot-path and cold-path Lambdas:** The API-serving Lambda should be lean (no scipy needed) with fast cold starts. The batch computation Lambda can be heavy.
4. **Step Functions for orchestration:** Use AWS Step Functions to chain ingestion -> normalization -> features -> signals as a workflow, not chained Lambda invocations.
5. **Lambda timeout:** Set to 15 minutes (maximum) for batch Lambdas. A daily run processing 100 tickers through cross-correlation should take 1-5 minutes, but leave headroom.

**Warning signs:**
- Daily batch takes >30 minutes end-to-end.
- Lambda invocations time out at the 3-minute default.
- CloudWatch shows 10+ second init durations.

**Phase to address:** Phase 0 (Infrastructure Setup) for packaging, Phase 3 (Signal Generation) for orchestration.

---

### Pitfall 11: Correlation Matrix Memory Explosion with Pair Growth

**What goes wrong:**
Cross-correlation across lags for N tickers involves O(N^2 * L) computations where L is the number of lags. With 50 seeded pairs and 11 lags (-5 to +5), this is manageable (~550 cross-correlation computations). But if someone adds tickers or computes all-pairs, 100 tickers = 4,950 pairs * 11 lags = 54,450 computations, each on a 60-day rolling window. The intermediate correlation matrices consume significant memory.

**Prevention:**
1. **Enforce seeded-pairs-only at the computation layer.** The feature engine should accept a list of `(ticker_a, ticker_b)` pairs, NOT a ticker list. Never call `itertools.combinations(tickers, 2)`.
2. **Memory profiling:** For the MVP pair count, profile actual memory usage on Lambda. With 50 pairs and 60-day windows, memory should be well under 1 GB. Add a safety check: if `len(pairs) > MAX_PAIRS`, raise an error rather than OOM.
3. **Chunked processing:** If pairs grow beyond Lambda memory limits, process in chunks of 50 pairs per invocation.
4. **Use numpy vectorized operations**, not Python loops, for cross-correlation. `np.correlate` or `scipy.signal.correlate` are dramatically faster than manual lag-shift-correlate loops.

**Warning signs:**
- Lambda OOM kills (`Runtime.ExitError` with signal 9).
- Processing time grows quadratically as tickers are added.
- Code contains `for t1 in tickers: for t2 in tickers:` nested loops.

**Phase to address:** Phase 2 (Feature Engineering / Lead-Lag Engine).

---

### Pitfall 12: Adjustment Policy ID Not Propagated Through Pipeline

**What goes wrong:**
You build the normalization layer with Policy A correctly. Later, you add Policy B (dividend-adjusted). But signals, features, and backtests don't track which adjustment policy was used to compute them. You end up with signals computed from different policies mixed in the same DynamoDB table, and no way to tell them apart.

**Prevention:**
1. **`adjustment_policy_id` is a required field on every intermediate and output record:** adjusted_bars, returns, features, correlations, signals, position specs. It's part of the DynamoDB sort key or an attribute on every S3 object.
2. **Pipeline functions accept `adjustment_policy_id` as an explicit parameter**, never default to an implicit global.
3. **Queries filter by `adjustment_policy_id`**. A signal query without a policy filter is an error, not a "return all" convenience.
4. **Schema enforcement:** DynamoDB items without `adjustment_policy_id` fail validation.

**Warning signs:**
- Any table or S3 prefix structure that doesn't include the policy ID.
- Functions that compute returns without an explicit policy parameter.
- Mixing signals from different policies in the same API response.

**Phase to address:** Phase 1 (Data Normalization). Baked into the schema from day one.

---

### Pitfall 13: Regime Classification Overfitting to One Pair

**What goes wrong:**
The regime rules (Bull/Base/Bear/Failure) are calibrated on the CRWV/NVDA pair during a specific market period. The RS thresholds (+5% for bullish, -7% for bearish), ATR expansion threshold (130%), and distribution rules (150% volume) may not generalize to other pairs with different volatility profiles, market caps, or sector dynamics.

**Prevention:**
1. **Parameterize regime thresholds per pair or per volatility class**, not as global constants. High-vol pairs need wider thresholds than low-vol pairs.
2. **Normalize thresholds relative to historical volatility.** Instead of "RS > +5%", use "RS > 1.5 * rolling_std(RS, 60d)". This adapts to each pair's natural variability.
3. **Validate regime classification on at least 3-5 pairs** before declaring the rules production-ready. If rules classify >60% of days as "Bull" for all pairs, the bullish threshold is too loose.
4. **Log regime transitions.** If a pair flip-flops between Bull and Bear daily, the thresholds are too tight for that pair's volatility.

**Warning signs:**
- All pairs show the same regime distribution (e.g., 80% Bull).
- Regime flip-flops more than once per week.
- Thresholds are hard-coded global constants with no per-pair or per-volatility-class override.

**Phase to address:** Phase 3 (Signal Generation / Regime Classification).

---

## Minor Pitfalls

---

### Pitfall 14: S3 Raw JSON Storage Without Partitioning

**What goes wrong:**
Storing all raw Polygon JSON responses in a flat S3 prefix (e.g., `s3://bucket/raw/response_001.json`) makes it impossible to efficiently query or re-process specific tickers or date ranges. Athena scans become full-bucket scans. Costs escalate linearly with data volume.

**Prevention:**
Partition S3 by `ticker/year/month/day/`: `s3://bucket/raw/bars/{ticker}/{YYYY}/{MM}/{DD}/response.json`. This enables Athena partition pruning and selective re-processing.

**Phase to address:** Phase 1 (Data Ingestion).

---

### Pitfall 15: Not Handling Polygon API Schema Changes

**What goes wrong:**
Polygon occasionally changes response schemas (field names, nesting, new fields). If your parser is tightly coupled to a specific schema version, an API update breaks ingestion silently (fields become `None`) or loudly (KeyError).

**Prevention:**
1. **Version your parsers.** `parse_agg_bar_v1()`, `parse_agg_bar_v2()`. When Polygon changes, add a new parser version, don't modify the old one.
2. **Schema validation on ingestion:** Validate required fields exist and have expected types before storing. Fail loudly.
3. **Store raw JSON alongside parsed data.** If a parser bug is discovered, re-parse from raw.

**Phase to address:** Phase 1 (Data Ingestion).

---

### Pitfall 16: Backtest Sharpe Ratio Inflation from Daily Returns

**What goes wrong:**
Computing Sharpe ratio from daily returns and annualizing by multiplying by sqrt(252) assumes returns are IID (independent, identically distributed). Financial returns are autocorrelated and have fat tails. The annualized Sharpe is overstated.

**Prevention:**
1. **Report both daily and annualized Sharpe**, with a note about the IID assumption.
2. **Also report hit rate, max drawdown, and mean return** as more robust metrics for a lead-lag strategy.
3. **Use block bootstrap** for confidence intervals on Sharpe rather than assuming normality.
4. **Compare to a baseline strategy** (buy-and-hold SPY) to contextualize the Sharpe.

**Phase to address:** Phase 4 (Backtest Module).

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Using Polygon `adjusted=true` instead of self-adjusting | Simpler ingestion, no split logic | Violates Policy A, unreproducible, can't support Policy B later | **Never** for this project |
| Single Lambda for all pipeline stages | Simpler deployment, fewer Lambda configs | Can't tune memory/timeout per stage, blast radius of a bug is the entire pipeline | Only in very early prototyping; split before Phase 2 |
| Hardcoded regime thresholds | Faster initial implementation | Won't generalize beyond CRWV/NVDA, requires code changes to tune | Acceptable for MVP with 1 pair; parameterize before adding pairs |
| Storing signals in DynamoDB only (no S3 backup) | Simpler data flow | No audit trail, DynamoDB TTL deletes are permanent, can't bulk analyze historical signals | **Never** -- always write signals to both DynamoDB (for API) and S3 (for audit/analysis) |
| Skipping multiple testing correction in lead-lag | Simpler statistics, more signals | False positive lead-lag relationships, wasted trading capital on noise | **Never** for production signals; acceptable for exploratory analysis only |
| No gap period in OOS validation | More data for validation, simpler window logic | Look-ahead contamination in stability_score | **Never** |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Polygon.io Aggregates | Using `adjusted=true` (applies both splits AND dividends) | Use `adjusted=false` and apply splits yourself from `/v3/reference/splits` |
| Polygon.io Aggregates | Not following `next_url` pagination | Always paginate until `next_url` is absent; wrap in a `paginate_all()` helper |
| Polygon.io Aggregates | Assuming timestamps are in local time | Timestamps are Unix milliseconds in UTC; convert to NYSE trading day using `exchange_calendars` |
| Polygon.io Splits | Assuming split records are complete for all tickers | Cross-reference against price discontinuities; flag tickers with unexplained >50% overnight price changes |
| Polygon.io Dividends | Storing but accidentally using dividends in return calculations | Dividends table should be read-only for analytics; the returns computation function should never import/access it |
| AWS Lambda + Docker | Building Docker image on Mac/Windows ARM and deploying to Lambda x86_64 | Build with `--platform linux/amd64` flag or build in CI on x86_64 |
| AWS Lambda Memory | Defaulting to 128 MB for numerical workloads | Use 1024-2048 MB; Lambda CPU scales linearly with memory, so doubling memory can more than halve execution time |
| DynamoDB | Using `Scan` to find signals by date | Create a GSI with date as partition key, or redesign to avoid Scan; Scan is O(table_size) regardless of result size |
| DynamoDB | Batch writes without error handling for unprocessed items | `BatchWriteItem` can return unprocessed items; always retry them with exponential backoff |
| S3 | Storing JSON without compression | Use gzip compression for raw JSON storage; reduces S3 costs by 70-80% and speeds up Athena queries |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Python loop for cross-correlation instead of numpy vectorization | Batch takes >30 min for 50 pairs | Use `numpy.correlate` or `scipy.signal.correlate`; vectorize across the lag dimension | >20 pairs on 60-day windows |
| Loading all historical data into Lambda memory for each invocation | OOM errors, 15-min timeout | Load only the required date range; use S3 Select or DynamoDB queries to filter server-side | >2 years of daily data for >50 tickers simultaneously |
| Serial Polygon API calls for each ticker | Ingestion takes >1 hour for 100 tickers | Use asyncio/aiohttp or concurrent.futures for parallel requests, respecting rate limits | >20 tickers at 5 req/min free tier |
| DynamoDB Scan for batch analytics | Query latency >30 seconds, RCU spike | Use Athena on S3 Parquet for analytics queries; DynamoDB for point reads only | >100,000 signal records |
| Recomputing all features from scratch daily | Daily batch takes >15 minutes | Incremental computation: only compute features for new bars, append to existing feature store | >1 year of history across >50 tickers |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Polygon API key in Lambda environment variable (plaintext) | Key exposed in CloudWatch logs, Lambda console | Store in AWS Secrets Manager or SSM Parameter Store (SecureString); retrieve at runtime |
| API Gateway endpoint with no authentication | Anyone can read your trading signals | Use API key + IAM auth; even for personal use, accidental exposure is possible |
| S3 bucket with public access | Raw financial data and signals exposed | Block all public access at the account level; use bucket policies for least-privilege |
| Hardcoded AWS credentials in code | Credential leakage if code is pushed to GitHub | Use IAM roles for Lambda execution; never hardcode credentials |
| Signal API returns full raw data alongside signals | Excess data exposure, potential for reverse-engineering data source | Return only the signal payload, not the underlying raw data; raw data stays in S3 |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Data Ingestion:** Often missing pagination handling -- verify `next_url` is always followed until exhausted
- [ ] **Data Ingestion:** Often missing rate limit backoff -- verify 429 responses trigger exponential backoff, not silent failure
- [ ] **Split Adjustment:** Often missing `fetched_at` timestamp on split records -- verify point-in-time reconstruction is possible
- [ ] **Normalization:** Often missing holiday/half-day handling -- verify bar counts match expected NYSE trading days
- [ ] **Returns Computation:** Often missing dividend contamination check -- verify returns_policy_a differs from Polygon adjusted=true returns for dividend-paying stocks
- [ ] **Cross-Correlation:** Often missing multiple testing correction -- verify significance thresholds account for the number of lags tested
- [ ] **Stability Score:** Often missing gap period between estimation and validation windows -- verify non-overlapping windows with dead zone
- [ ] **Backtest:** Often missing network isolation -- verify backtest code never imports from ingestion module
- [ ] **Backtest:** Often missing split look-ahead prevention -- verify backtest only uses splits known as-of the backtest date
- [ ] **DynamoDB Schema:** Often missing `adjustment_policy_id` on signal records -- verify every record has it and queries filter by it
- [ ] **DynamoDB:** Often missing TTL attribute -- verify signal records have TTL set for automatic cleanup
- [ ] **Lambda:** Often missing `--platform linux/amd64` in Docker build -- verify image runs on Lambda's x86_64 architecture
- [ ] **API:** Often missing explainability payload -- verify each signal includes lag, window, correlation, stability, regime, and policy metadata

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Dividend contamination in returns | HIGH | Recompute ALL returns, features, correlations, and signals from raw unadjusted data. Invalidate all historical signals. If backtests were run on contaminated data, all backtest results are invalid. |
| Look-ahead bias from future splits | HIGH | Add `fetched_at` to split records going forward. For historical data, re-ingest split records and manually reconstruct point-in-time view. Re-run all backtests. Cannot retroactively fix backtests that already used contaminated adjustments. |
| Spurious cross-correlations in production signals | MEDIUM | Add residualization and multiple testing correction. Re-run signal generation. Historical signals flagged as "pre-correction" and excluded from performance tracking. |
| Lambda OOM on correlation computation | LOW | Increase Lambda memory to 3008 MB or 10240 MB. If still failing, chunk pairs into batches of 25. No data loss, just re-run. |
| DynamoDB hot partition throttling | MEDIUM | Migrate to new table with correct partition key scheme. Requires backfill of existing data. Use DynamoDB data export to S3, transform, reimport. |
| Polygon rate limiting causing incomplete ingestion | LOW | Re-run ingestion for failed tickers with backoff. Compare stored bar counts to expected counts and fill gaps. Raw JSON in S3 means no data loss for already-ingested tickers. |
| Backtest re-queried Polygon (non-reproducible results) | MEDIUM | Invalidate all backtest results. Implement data provider interface. Re-run backtests against stored data. The backtest results themselves aren't recoverable -- they must be regenerated. |
| Missing `adjustment_policy_id` on records | MEDIUM | Backfill with default "A" if only Policy A was ever used. Add schema validation to prevent future omissions. If multiple policies were used without tracking, data provenance is lost -- may need to recompute from raw. |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Dividend contamination (Pitfall 1) | Phase 1: Data Ingestion | Integration test: compare returns_policy_a to Polygon adjusted returns for dividend-paying stock; they must differ |
| Look-ahead bias from splits (Pitfall 2) | Phase 1: Data Ingestion + Phase 4: Backtest | Verify split records have `fetched_at`; backtest code filters splits by date |
| Spurious cross-correlation (Pitfall 3) | Phase 2: Lead-Lag Engine | Unit test: cross-correlation of two independent random walks should show no significant lead-lag; residualization against SPY implemented |
| OOS validation contamination (Pitfall 4) | Phase 2: Feature Engineering | Verify gap period > 0 between estimation and validation windows; log window boundaries |
| Lambda packaging (Pitfall 5) | Phase 0: Infrastructure | Docker image builds and deploys successfully; cold start < 10 seconds; numpy/scipy/pandas import successfully |
| DynamoDB hot partition (Pitfall 6) | Phase 1: Storage Schema | Partition key is `ticker_pair`, not `date`; load test with 200 concurrent writes succeeds |
| Polygon rate limiting / pagination (Pitfall 7) | Phase 1: Data Ingestion | Ingestion of 100 tickers completes without 429 errors; bar counts match expected trading days |
| Backtest API isolation (Pitfall 8) | Phase 4: Backtest | Import linting verifies backtest module does not import ingestion module; no Polygon API calls in backtest CloudWatch logs |
| Timezone errors (Pitfall 9) | Phase 1: Data Normalization | DST transition dates (March, November) have correct bar counts and no duplicates |
| Lambda cold start (Pitfall 10) | Phase 0: Infrastructure | End-to-end daily batch completes in < 10 minutes |
| Memory explosion (Pitfall 11) | Phase 2: Lead-Lag Engine | Memory usage for 50 pairs on 60-day window < 512 MB; `MAX_PAIRS` safety check enforced |
| Policy ID propagation (Pitfall 12) | Phase 1: Normalization | Every DynamoDB item and S3 object includes `adjustment_policy_id`; query without policy filter raises error |
| Regime overfitting (Pitfall 13) | Phase 3: Signal Generation | Regime classification validated on 3+ pairs; no pair has >70% days in single regime |
| S3 partitioning (Pitfall 14) | Phase 1: Data Ingestion | S3 prefix structure includes `ticker/year/month/day/` |
| Parser versioning (Pitfall 15) | Phase 1: Data Ingestion | Parser functions are versioned; raw JSON always stored alongside parsed data |
| Sharpe inflation (Pitfall 16) | Phase 4: Backtest | Report includes daily Sharpe, annualized Sharpe with IID caveat, hit rate, max drawdown |

## Sources

- Training data knowledge of financial data engineering patterns (MEDIUM confidence -- well-established domain practices)
- Training data knowledge of AWS Lambda packaging and DynamoDB design patterns (MEDIUM confidence -- AWS fundamentals are stable)
- Training data knowledge of quantitative finance statistical pitfalls (HIGH confidence -- academic/practitioner consensus on look-ahead bias, spurious correlation, multiple testing)
- Project-specific constraints from PROJECT.md (HIGH confidence -- directly provided)
- Note: WebSearch and WebFetch were unavailable during this research session. Polygon.io API specifics (exact rate limits, pagination field names, adjustment parameter behavior) should be verified against current official documentation before implementation.

---
*Pitfalls research for: Serverless Quantitative Lead-Lag Analytics Platform*
*Researched: 2026-02-18*
