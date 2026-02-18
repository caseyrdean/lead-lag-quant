# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-18)

**Core value:** Any seeded equity pair produces a reproducible, auditable full position spec backed by statistically validated lead-lag relationships -- and a paper trading simulator to validate those signals against real prices before committing capital.
**Current focus:** Phase 2 - Normalization & Returns

## Current Position

Phase: 2 of 6 (Normalization & Returns)
Plan: 2 of next
Status: Ready
Last activity: 2026-02-18 -- Completed 02-01-PLAN.md (Normalization module, Schema + Policy A pipeline)

Progress: [#####.........] 21%

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: 19min
- Total execution time: 1.33 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-data-ingestion-pipeline | 3 | 55min | 18min |
| 02-normalization-returns | 1 | 25min | 25min |

**Recent Trend:**
- Last 5 plans: 01-01 (5min), 01-02 (15min), 01-03 (35min), 02-01 (25min)
- Trend: baseline

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

### Pending Todos

None yet.

### Blockers/Concerns

- Polygon.io rate limits by plan tier need verification against current docs before Phase 1 implementation
- stability_score (RSI-v2) component weights not yet defined -- must be specified before Phase 4

## Session Continuity

Last session: 2026-02-18
Stopped at: Completed 02-01-PLAN.md (Normalization module -- schema + Policy A pipeline)
Resume file: .planning/phases/02-normalization-returns/02-01-SUMMARY.md
