# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-18)

**Core value:** Any seeded equity pair produces a reproducible, auditable full position spec backed by statistically validated lead-lag relationships -- and a paper trading simulator to validate those signals against real prices before committing capital.
**Current focus:** Phase 5 - Paper Trading Simulation

## Current Position

Phase: 5 of 6 (Paper Trading Simulation)
Plan: 1 of 2 -- Plan 05-01 complete
Status: Executing
Last activity: 2026-02-19 -- Completed Plan 05-01 (paper_trading engine, price poller, 10 new tests, 147 total passing)

Progress: [################] 75%

## Performance Metrics

**Velocity:**
- Total plans completed: 10
- Average duration: 15min
- Total execution time: 2.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-data-ingestion-pipeline | 3 | 55min | 18min |
| 02-normalization-returns | 2 | 40min | 20min |
| 03-feature-engineering | 2 | 14min | 7min |
| 04-lead-lag-engine-regime-signals | 2 | 40min | 20min |

| 05-paper-trading-simulation | 1 | 8min | 8min |

**Recent Trend:**
- Last 5 plans: 03-02 (8min), 04-01 (18min), 04-02 (22min), 05-01 (8min)
- Trend: stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: v1 is a local Gradio demo -- no AWS Lambda, S3, DynamoDB, or Terraform. SQLite for all storage. Gradio for UI.
- [Roadmap]: Module layout follows spec: /ingestion_massive, /normalization, /features, /leadlag_engine, /signals, /paper_trading, /backtest, /ui, /utils, /tests
- [Roadmap]: UI panels distributed across phases (vertical slices) rather than bundled into a single UI phase
- [01-01]: Used raw sqlite3 (no ORM) for full control over schema and ON CONFLICT clauses
- [01-01]: Module-level NYSE calendar caching to avoid expensive re-creation
- [01-01]: Explicit pythonpath in pytest config for reliable test module resolution
- [01-02]: Always pass adjusted=false to Polygon /v2/aggs -- unadjusted raw prices required for corporate action normalization
- [01-02]: SPY always included in ingest_pair via set deduplication {leader, follower, SPY} (INGEST-10)
- [01-02]: Per-endpoint error isolation: failed endpoint logs status=failed but remaining endpoints continue
- [01-02]: Deterministic params serialization via json.dumps(sort_keys=True) for idempotent row lookup
- [01-03]: app.queue() called before returning Blocks instance -- required for gr.Progress to render during fetch
- [01-03]: SQLite is single source of truth for pair state -- no gr.State() for persistence
- [01-03]: load_dotenv() placed at very top of main.py before any imports that read env vars
- [01-03]: python-dotenv added to pyproject.toml as runtime dependency (not dev-only)
- [02-01]: Policy A is split-only: adj_price = raw_price * historical_adjustment_factor; dividends stored separately and never applied to prices
- [02-01]: Polygon historical_adjustment_factor strategy: next split after bar_date provides cumulative backward factor; 1.0 if no splits exist after bar_date
- [02-01]: XNYS calendar instantiated once as module-level singleton in timestamp_utils.py to avoid expensive repeated creation
- [02-01]: fetched_at on splits rows copied from raw_api_responses.retrieved_at for point-in-time backtest isolation (NORM-05)
- [02-01]: adjustment_policy_id column defaults to 'policy_a' on normalized_bars for future multi-policy extensibility
- [02-02]: Returns computed strictly per-ticker -- single-ticker DataFrame fed to pct_change to prevent cross-ticker boundary bleed (NORM-04)
- [02-02]: fill_method=None passed to pct_change to satisfy pandas >= 2.1 deprecation
- [02-02]: First N rows per period carry NULL return (insufficient history) -- stored as NULL, not zero
- [02-02]: Normalize tab placed third in Gradio UI; run_normalization() runs normalize_all_pairs then compute_returns_all_pairs sequentially
- [03-01]: statsmodels 0.14 RollingOLS: .resid not available; residuals computed manually as y - (alpha + beta*spy) from rolling params DataFrame
- [03-01]: BONFERRONI_THRESHOLD = 0.05/11 as module-level constant -- 11 lag tests per window requires correction to avoid ~42% false positive rate
- [03-01]: Manual Python loop for rolling cross-correlation -- pandas.rolling().apply() is 1D only, cannot slice two series simultaneously
- [03-01]: Guard len(series) < window in residualize_against_spy to return all-NaN series rather than crash RollingOLS with IndexError
- [03-02]: Lagged returns use series.shift(lag): positive lag=backward look (first N NaN), negative lag=forward look (last N NaN) -- plan docstring had inverted description but test expectations were authoritative
- [03-02]: Pipeline separates pair-level features (xcorr, RS) from per-ticker features (volatility, zscore, lagged_returns) for clean orchestration and independent reuse
- [03-02]: compute_features_all_pairs always includes SPY in per-ticker computation (hardcoded into tickers set)
- [Phase 04-lead-lag-engine-regime-signals]: RSI-v2 weights: lag_persistence=0.30, walk_forward_oos=0.25, rolling_confirmation=0.20, regime_stability=0.15, lag_drift=0.10 (resolves STATE.md blocker on undefined weights)
- [Phase 04-lead-lag-engine-regime-signals]: detect_optimal_lag requires MIN_SIGNIFICANT_DAYS=30 per lag; selects by abs(median_corr) but returns signed correlation_strength
- [Phase 04-lead-lag-engine-regime-signals]: init_engine_schema called from init_schema() so tmp_db fixture creates all Phase 4 tables automatically without conftest changes
- [04-02]: passes_gate uses abs(correlation_strength) > 0.65 -- allows short signals (strong inverse correlations) to pass the strength gate; direction handled separately by sign
- [04-02]: classify_regime() MUST be called before compute_stability_score() -- regime_stability_score() is an INPUT to RSI-v2 composite; ordering enforced in pipeline.py
- [04-02]: adjustment_policy_id='policy_a' hardcoded in generate_signal() -- locked decision, not configurable
- [05-01]: Average-cost basis for position tracking (not FIFO); simpler and appropriate for paper trading
- [05-01]: SIZING_FRACTIONS: full=20%, half=10%, quarter=5% of starting capital per position
- [05-01]: Polygon snapshot fallback chain: lastTrade.p -> min.c -> day.c -> prevDay.c
- [05-01]: Lazy-init NYSE calendar singleton to avoid import-time pandas_market_calendars overhead
- [05-01]: Partial unique index idx_trades_signal_buy prevents duplicate auto-execution at DB level
- [05-01]: init_paper_trading_schema wired into init_schema() following same pattern as init_engine_schema

### Pending Todos

None yet.

### Blockers/Concerns

- Polygon.io rate limits by plan tier need verification against current docs before Phase 1 implementation
- stability_score (RSI-v2) component weights RESOLVED: defined as lag_persistence=0.30, walk_forward_oos=0.25, rolling_confirmation=0.20, regime_stability=0.15, lag_drift=0.10 in leadlag_engine/stability.py

## Session Continuity

Last session: 2026-02-19
Stopped at: Completed 05-01-PLAN.md (paper_trading engine + tests). Ready for 05-02-PLAN.md (Gradio UI).
Resume file: .planning/phases/05-paper-trading-simulation/05-01-SUMMARY.md
