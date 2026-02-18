# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-18)

**Core value:** Any seeded equity pair produces a reproducible, auditable full position spec backed by statistically validated lead-lag relationships -- and a paper trading simulator to validate those signals against real prices before committing capital.
**Current focus:** Phase 3 - Feature Engineering

## Current Position

Phase: 3 of 6 (Feature Engineering)
Plan: 1 of 3 -- Plan 1 COMPLETE
Status: Ready
Last activity: 2026-02-18 -- Completed 03-01-PLAN.md (Cross-correlation foundation: scipy/statsmodels, 5 feature tables, SPY residualization, Bonferroni xcorr)

Progress: [#######.......] 33%

## Performance Metrics

**Velocity:**
- Total plans completed: 6
- Average duration: 17min
- Total execution time: 1.68 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-data-ingestion-pipeline | 3 | 55min | 18min |
| 02-normalization-returns | 2 | 40min | 20min |
| 03-feature-engineering | 1 | 6min | 6min |

**Recent Trend:**
- Last 5 plans: 01-03 (35min), 02-01 (25min), 02-02 (15min), 03-01 (6min)
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

### Pending Todos

None yet.

### Blockers/Concerns

- Polygon.io rate limits by plan tier need verification against current docs before Phase 1 implementation
- stability_score (RSI-v2) component weights not yet defined -- must be specified before Phase 4

## Session Continuity

Last session: 2026-02-18
Stopped at: Completed 03-01-PLAN.md (Cross-correlation foundation: scipy/statsmodels deps, 5 feature tables, SPY residualization, Bonferroni xcorr with Bonferroni threshold)
Resume file: .planning/phases/03-feature-engineering/03-01-SUMMARY.md
