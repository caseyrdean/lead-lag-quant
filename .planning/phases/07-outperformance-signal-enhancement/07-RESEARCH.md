# Phase 7: Outperformance Signal Enhancement - Research

**Researched:** 2026-03-21
**Domain:** Python signal generation enhancement, SQLite schema migration, backtest metrics disaggregation
**Confidence:** HIGH — all findings sourced directly from codebase inspection

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### BUY/HOLD/SELL Classification
- Action field added to signal records alongside existing long/short direction (not a replacement)
- All actions are FLAGS ONLY — BUY, HOLD, SELL surface in the dashboard; human executes all trades
- Two BUY conditions, both produce the same `action: BUY` (no sub-tagging):
  1. Follower consistently outperforming leader (RS positive streak)
  2. Follower was underperforming leader and reverses upward for 3+ consecutive sessions
- HOLD: follower RS is within the pair's historical RS volatility band (dynamic, not fixed ±2%)
- SELL: requires N sessions of sustained RS decline below the leader's trajectory (not a single-reading drop)
- SELL from stability/correlation: only flag SELL if the stability score AND correlation strength are on a deteriorating trend, not a one-off dip below threshold
- Each action transition (BUY→HOLD, HOLD→SELL, etc.) is logged with timestamp for full lifecycle audit trail

#### RS Acceleration
- Measured as slope of RS series over recent sessions, scaled by pair-specific RS standard deviation (dynamic threshold, not fixed)
- Track BOTH follower RS acceleration AND leader RS deceleration — both present = highest conviction
- RS acceleration is informational metadata on the signal, NOT a hard gate (signal still fires without it)
- BUY only triggers on confirmed positive RS crossover — accelerating-but-still-negative RS does not qualify

#### New Signal Fields
- `action`: BUY / HOLD / SELL
- `response_window`: average number of sessions follower stays in BUY state after lag event (hold duration estimate)
- `rs_acceleration`: slope of follower RS relative to pair-specific RS volatility (float)
- `leader_rs_deceleration`: slope of leader RS (float) — captures divergence story
- `outperformance_margin`: expected_target minus leader baseline return over the same lag window
- Action field updates on each pipeline re-run (signals are upserted, not immutable for action)

#### Response Window
- Defined as: average duration follower stays in BUY state after a lag event fires
- Computed from historical RS state transitions for the pair
- Gives trader a time-bound expectation: "this signal typically plays out over N sessions"

#### Pipeline Scheduler
- Change poll interval from 30 minutes to **15 minutes**
- Applies to `utils/pipeline_scheduler.py` background thread

#### Backtest Updates
- Break down existing backtest metrics (hit rate, Sharpe, drawdown) by action: BUY / HOLD / SELL
- Add outperformance comparison: follower realized return vs leader realized return over the response_window
- Validates that BUY signals actually outperformed the leader historically
- No React UI changes in this phase — backtest UI is a separate future phase

### Claude's Discretion
- Exact N sessions for SELL confirmation (symmetrical with BUY's 3-session reversal is a reasonable default)
- SQLite schema design for signal_transitions table
- Exact slope computation method (linear regression vs point-difference) — use whichever is more robust given pair data density

### Deferred Ideas (OUT OF SCOPE)
- React UI updates to show BUY/HOLD/SELL on the Signal Dashboard and Backtest Results page — separate phase after data model is stable
- Leader deceleration as a hard gate (discussed, kept as metadata only for now)
- Per-pair configurable reversal session threshold (discussed, defaulting to 3 for now)
</user_constraints>

---

## Summary

Phase 7 is a pure Python/SQLite enhancement with no frontend work. It extends the existing `signals` table with five new columns (`action`, `response_window`, `rs_acceleration`, `leader_rs_deceleration`, `outperformance_margin`), adds a new `signal_transitions` audit table, and updates three primary modules: `signals/generator.py`, `backtest/engine.py`, and `utils/pipeline_scheduler.py`.

The codebase is fully understood from inspection. The `signals` table primary key is `(ticker_a, ticker_b, signal_date)`. The upsert in `leadlag_engine/db.py` already handles partial updates — `action` must be added to the SET clause so it updates on re-run (unlike `generated_at` which is immutability-anchored). The RS series is already stored in `features_relative_strength` as `rs_value` (fractional decimal, 10-session rolling, one row per `(ticker_a, ticker_b, trading_day)`) — the slope computation reads directly from this table. The `outperformance_margin` is computed as `expected_target - leader_baseline_return` where leader baseline return is the mean lagged return for `ticker_a` over the `optimal_lag` window.

The backtest engine (`backtest/engine.py`) currently returns a flat dict of aggregate metrics (hit_rate, Sharpe, drawdown, mean_return_per_trade). The update must disaggregate these per `action` value by joining signals with their action column. The `signal_transitions` table needs a clear schema: `(ticker_a, ticker_b, signal_date, from_action, to_action, transitioned_at)` with an index on `(ticker_a, ticker_b)`. The scheduler `POLL_INTERVAL` constant in `utils/pipeline_scheduler.py` is a single integer at line 28 — change from `1800` to `900`.

**Primary recommendation:** Add new columns via `ALTER TABLE ... ADD COLUMN` migration pattern (already used in `leadlag_engine/db.py` and `utils/db.py`), compute all new fields in `signals/generator.py`, update `upsert_signal` in `leadlag_engine/db.py`, and extend `run_backtest` with per-action breakdown.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | >=2.1 | RS series slicing, slope computation, rolling stats | Already in stack; RS data loaded as Series |
| numpy | >=1.26 | Linear regression via `np.polyfit` for slope | In stack; more robust than point-difference on sparse data |
| scipy | >=1.13 | Already used for correlation significance | In stack |
| sqlite3 | stdlib | Schema migration, signal upserts | Project uses SQLite exclusively |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| statsmodels | >=0.14 | OLS regression (alternative slope method) | Only if `np.polyfit` proves insufficient; prefer numpy for simplicity |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `np.polyfit` for slope | point-difference (last - first) / n | polyfit is more robust to noise; point-difference is simpler but volatile on sparse RS data |
| ALTER TABLE migration | full schema recreation | ALTER TABLE is the project's established pattern; no data loss risk |

**Installation:** No new packages required. All dependencies are already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended File Touch List
```
signals/generator.py         # Add 5 new fields, add RS action classifier, rs_acceleration, outperformance_margin
leadlag_engine/db.py         # Schema migration (5 new columns), signal_transitions table, update upsert_signal
utils/pipeline_scheduler.py  # Change POLL_INTERVAL from 1800 to 900
backtest/engine.py           # Add per-action metric breakdown + outperformance comparison
tests/test_signals_generator.py   # Tests for new fields and BUY/HOLD/SELL logic
tests/test_backtest_engine.py     # Tests for per-action metrics
```

### Pattern 1: Schema Migration (ALTER TABLE — established project pattern)

**What:** Add columns with `ALTER TABLE ... ADD COLUMN` wrapped in try/except for idempotency.
**When to use:** Every time a new column is added to an existing production table.

```python
# Source: leadlag_engine/db.py lines 67-72 (existing pattern)
try:
    conn.execute("ALTER TABLE signals ADD COLUMN action TEXT")
    conn.execute("ALTER TABLE signals ADD COLUMN response_window REAL")
    conn.execute("ALTER TABLE signals ADD COLUMN rs_acceleration REAL")
    conn.execute("ALTER TABLE signals ADD COLUMN leader_rs_deceleration REAL")
    conn.execute("ALTER TABLE signals ADD COLUMN outperformance_margin REAL")
    conn.commit()
except Exception:
    pass  # Columns already exist
```

This migration belongs in `init_engine_schema()` in `leadlag_engine/db.py`, called at startup via `utils/db.py → init_schema()`.

### Pattern 2: RS Slope Computation

**What:** Compute slope of RS series over the last N sessions using `np.polyfit`.
**When to use:** Both `rs_acceleration` and `leader_rs_deceleration` — slope of `features_relative_strength.rs_value` over the last N sessions for the pair.

```python
# Source: codebase inspection — np.polyfit is in-stack via numpy>=1.26
import numpy as np

def compute_rs_slope(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    lookback_sessions: int = 5,
) -> float | None:
    """Slope of RS series over last N sessions, normalized by pair RS std dev."""
    df = pd.read_sql_query(
        """
        SELECT rs_value FROM features_relative_strength
        WHERE ticker_a=? AND ticker_b=?
          AND rs_value IS NOT NULL
        ORDER BY trading_day DESC
        LIMIT ?
        """,
        conn,
        params=(ticker_a, ticker_b, lookback_sessions * 3),  # extra for std dev
    )
    if len(df) < lookback_sessions:
        return None

    rs_series = df['rs_value'].iloc[::-1].values  # chronological order
    recent = rs_series[-lookback_sessions:]
    x = np.arange(len(recent))
    slope, _ = np.polyfit(x, recent, 1)

    # Normalize by pair-specific RS std dev (dynamic threshold)
    rs_std = float(df['rs_value'].std()) if len(df) >= 10 else None
    if rs_std and rs_std > 0:
        return float(slope / rs_std)
    return float(slope)
```

### Pattern 3: BUY/HOLD/SELL Classifier

**What:** Classify action from current RS state relative to historical RS distribution.
**When to use:** Called inside `generate_signal()` after gate passes.

BUY conditions (either satisfies):
1. RS has been positive (above 0) for 3+ consecutive sessions → consistent outperformance
2. RS was negative, reversed upward for 3+ consecutive sessions → reversal confirmation

SELL condition: RS has been declining for N consecutive sessions (default N=3 to match BUY symmetry).

HOLD condition: RS is within ±1 std dev of the pair's historical RS mean (within the volatility band).

```python
# Source: CONTEXT.md decisions + features_relative_strength schema (codebase inspection)
def classify_action(
    rs_series: pd.Series,
    rs_std: float,
    rs_mean: float,
    n_sessions: int = 3,
) -> str:
    """Classify BUY/HOLD/SELL from recent RS series.

    rs_series: chronologically ordered RS values (most recent last)
    rs_std: pair-specific RS standard deviation
    rs_mean: pair-specific RS mean (historical)
    """
    if len(rs_series) < n_sessions:
        return 'HOLD'

    recent = rs_series.iloc[-n_sessions:]

    # BUY condition 1: consistent outperformance — RS positive for N sessions
    if (recent > 0).all():
        return 'BUY'

    # BUY condition 2: reversal — was negative, now positive for N sessions
    if len(rs_series) >= n_sessions + 1:
        pre_reversal = rs_series.iloc[-(n_sessions + 1)]
        if pre_reversal < 0 and (recent > 0).all():
            return 'BUY'

    # SELL condition: N consecutive sessions of RS decline
    diffs = recent.diff().dropna()
    if (diffs < 0).all():
        return 'SELL'

    # HOLD: within historical volatility band
    current_rs = rs_series.iloc[-1]
    if abs(current_rs - rs_mean) <= rs_std:
        return 'HOLD'

    return 'HOLD'  # default
```

### Pattern 4: signal_transitions Table Schema

**What:** Audit log for every action state change per signal.
**When to use:** Written every time a signal's action field changes value.

```sql
-- Source: CONTEXT.md design decision — Claude's discretion on schema
CREATE TABLE IF NOT EXISTS signal_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_a        TEXT NOT NULL,
    ticker_b        TEXT NOT NULL,
    signal_date     TEXT NOT NULL,  -- FK to signals(ticker_a, ticker_b, signal_date)
    from_action     TEXT,           -- NULL for initial assignment (no prior state)
    to_action       TEXT NOT NULL,  -- BUY, HOLD, or SELL
    transitioned_at TEXT NOT NULL   -- ISO-8601 UTC timestamp
);

CREATE INDEX IF NOT EXISTS idx_transitions_pair
    ON signal_transitions(ticker_a, ticker_b);
CREATE INDEX IF NOT EXISTS idx_transitions_signal
    ON signal_transitions(ticker_a, ticker_b, signal_date);
```

**Transition logging logic:** Before upserting a signal, read the current `action` from the DB. If different from the new action (or NULL → first write), insert a transition row. This must happen inside `generate_signal()` or `upsert_signal()`, after computing the new action.

### Pattern 5: outperformance_margin Computation

**What:** `expected_target - leader_baseline_return` over the same `optimal_lag` window.
**When to use:** Computed in `generate_signal()` alongside `expected_target`.

```python
# Source: codebase inspection — parallels existing compute_expected_target()
def compute_leader_baseline_return(
    conn: sqlite3.Connection,
    ticker_a: str,  # leader
    optimal_lag: int,
    lookback_days: int = 120,
) -> float | None:
    """Mean lagged return for the leader over optimal_lag window."""
    anchor_row = conn.execute(
        "SELECT MAX(trading_day) FROM features_lagged_returns WHERE ticker=?",
        (ticker_a,),
    ).fetchone()
    anchor = anchor_row[0] if anchor_row else None
    if anchor is None:
        return None

    df = pd.read_sql_query(
        """
        SELECT return_value
        FROM features_lagged_returns
        WHERE ticker=? AND lag=?
          AND return_value IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
        """,
        conn,
        params=(ticker_a, optimal_lag, anchor, f'-{lookback_days}'),
    )
    if df.empty:
        return None
    return float(df['return_value'].mean())
```

Then: `outperformance_margin = expected_target - leader_baseline_return` (both can be None; handle gracefully).

### Pattern 6: Response Window Computation

**What:** Average BUY-state duration for a pair, computed from historical RS state transitions.
**When to use:** Computed in `generate_signal()` — queries `signal_transitions` for historical BUY→non-BUY durations.

```python
# Source: CONTEXT.md decision + signal_transitions schema
def compute_response_window(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
) -> float | None:
    """Average sessions the pair stays in BUY state after a lag event fires.

    Computed from signal_transitions history:
    - Find all BUY entries (from_action != 'BUY' AND to_action = 'BUY')
    - Find the following non-BUY transition for each
    - Average the session counts
    """
    # On first run, signal_transitions is empty — return None (no history)
    rows = conn.execute(
        """
        SELECT transitioned_at FROM signal_transitions
        WHERE ticker_a=? AND ticker_b=?
        ORDER BY transitioned_at ASC
        """,
        (ticker_a, ticker_b),
    ).fetchall()

    if not rows:
        return None

    # Parse transitions to measure BUY run durations
    # ... (session counting logic against trading_day sequences)
    # Returns None if insufficient history (< 2 complete BUY cycles)
```

Note: Session counting from timestamps is tricky — prefer joining against `normalized_bars` trading days to count actual sessions, not calendar days.

### Pattern 7: Backtest Per-Action Breakdown

**What:** Extend `run_backtest()` to return metrics disaggregated by action.
**When to use:** The backtest route already returns a flat dict; add `by_action` key.

```python
# Source: backtest/engine.py inspection
# The signals query must now fetch the action column:
rows = conn.execute(
    """
    SELECT signal_date, optimal_lag, action
    FROM signals
    WHERE ticker_a=? AND ticker_b=?
      AND signal_date BETWEEN ? AND ?
    ORDER BY signal_date ASC
    """,
    (leader, follower, start_date, end_date),
).fetchall()

# Group trade_returns by action, compute metrics per group
# Return: existing flat dict + 'by_action': {'BUY': {...}, 'HOLD': {...}, 'SELL': {...}}
```

### Anti-Patterns to Avoid

- **Making action immutable like generated_at:** Action MUST update on re-run (it's a current-state field, not an audit anchor). The SET clause in `upsert_signal` must include `action`.
- **Computing RS std dev from only the last N sessions:** Use the full historical RS series for std dev, then take only the last N rows for the streak logic. Short windows produce unstable std devs.
- **Logging transitions inside upsert_signal without reading current state first:** Must read the existing `action` before writing new one to detect if a transition occurred.
- **Using calendar days for response_window:** Join against `normalized_bars` trading days, not datetime arithmetic. The pair is validated on trading sessions only.
- **Assuming features_lagged_returns has leader (ticker_a) data:** It does — `compute_lagged_returns_for_ticker()` runs for every ticker including leaders. The `compute_leader_baseline_return()` function queries `ticker_a` at `optimal_lag`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Linear slope of RS series | Manual (last - first) / n point-difference | `np.polyfit(x, y, 1)` | More robust to noisy RS data; single intermediate values are volatile |
| RS standard deviation | Custom rolling std | `pd.Series.std()` on the full historical RS series | pandas handles NaN/empty edge cases correctly |
| Trading day session count | Calendar day arithmetic | Query `normalized_bars` for `COUNT(DISTINCT trading_day)` in range | Avoids weekend/holiday miscounts |

**Key insight:** All supporting data (RS series, lagged returns for both leader and follower) is already in the database. No new data ingestion or feature computation pipeline is required.

---

## Common Pitfalls

### Pitfall 1: action Column Not in upsert_signal SET Clause
**What goes wrong:** The `action` field is written on first insert but never updated on re-run. The signal's action is stale.
**Why it happens:** The existing `upsert_signal` intentionally excludes `generated_at` from SET. Developers cargo-cult the exclusion pattern and leave `action` out too.
**How to avoid:** `action` is NOT immutable. Add it to the SET clause alongside all other mutable fields.
**Warning signs:** `action` is always the first-ever classification, never updates even when RS state clearly changes.

### Pitfall 2: signal_transitions Written on Every Upsert
**What goes wrong:** Every pipeline run writes a transition row even when action hasn't changed (HOLD→HOLD spam).
**Why it happens:** The transition log is written unconditionally.
**How to avoid:** Read current `action` from `signals` table BEFORE the upsert. Only insert a `signal_transitions` row if `new_action != existing_action` (or if the row is new).
**Warning signs:** `signal_transitions` table grows at the rate of `n_pairs × pipeline_runs` per day.

### Pitfall 3: None-Handling for New Fields
**What goes wrong:** `outperformance_margin`, `rs_acceleration`, or `response_window` is `None` when `features_lagged_returns` or `features_relative_strength` have insufficient data. The upsert crashes on a non-NULL column constraint.
**Why it happens:** All new columns must be NULLABLE (no `NOT NULL` constraint) since data may be sparse for new pairs.
**How to avoid:** Define all 5 new columns with no NOT NULL constraint (same as `expected_target` and `invalidation_threshold` in the existing schema).
**Warning signs:** Crashes on first pipeline run for newly-added pairs with < 10 sessions of RS history.

### Pitfall 4: response_window Bootstrap Problem
**What goes wrong:** `response_window` is always `None` because `signal_transitions` is empty until transitions actually accumulate.
**Why it happens:** Response window is derived from historical transition data, which only exists after the system has been running for multiple signal cycles.
**How to avoid:** Return `None` gracefully; document that response_window will be `None` for pairs with < 2 complete BUY→exit cycles. Do NOT block signal generation on this.
**Warning signs:** First week of Phase 7 deployment shows all `response_window = None` — this is correct behavior.

### Pitfall 5: backtest by_action Returns Empty Dicts for Missing Actions
**What goes wrong:** Frontend (in a future phase) tries to read `by_action.BUY.hit_rate` but `by_action` is `{}` or missing the key because no BUY signals existed in the date range.
**Why it happens:** Groupby on empty sets doesn't produce zero-dict entries.
**How to avoid:** Always return all three action keys in `by_action` dict, populated with zeros when no signals exist for that action. Match the zero-dict pattern already used in `run_backtest`.
**Warning signs:** KeyError exceptions in future UI code.

### Pitfall 6: BUY reversal condition requires pre-reversal check
**What goes wrong:** The reversal BUY condition (follower was negative, now positive for 3 sessions) fires incorrectly when there is no prior negative RS history in the lookback window.
**Why it happens:** Only checking that the last 3 sessions are positive, without verifying the pre-reversal state.
**How to avoid:** Confirm that `rs_series.iloc[-(n_sessions + 1)]` exists and is negative before declaring a reversal BUY.
**Warning signs:** Pairs that have always been positive RS get classified as "reversal BUY" on first run.

---

## Code Examples

### Full signals Table Schema (current state)
```sql
-- Source: leadlag_engine/db.py init_engine_schema() — verified by inspection
CREATE TABLE IF NOT EXISTS signals (
    ticker_a                TEXT NOT NULL,
    ticker_b                TEXT NOT NULL,
    signal_date             TEXT NOT NULL,
    optimal_lag             INTEGER,
    window_length           INTEGER,
    correlation_strength    REAL,
    stability_score         REAL,
    regime_state            TEXT,
    adjustment_policy_id    TEXT NOT NULL DEFAULT 'policy_a',
    direction               TEXT,
    expected_target         REAL,
    invalidation_threshold  REAL,
    sizing_tier             TEXT,
    flow_map_entry          TEXT,
    data_warning            TEXT,
    generated_at            TEXT NOT NULL,
    PRIMARY KEY (ticker_a, ticker_b, signal_date)
);
-- Plus existing index: idx_signals_date, idx_signals_ticker_a
-- Plus migration: data_warning column added via ALTER TABLE (already applied)
```

Phase 7 adds 5 columns via migration:
```sql
-- All NULLABLE — sparse data must not crash
ALTER TABLE signals ADD COLUMN action TEXT;
ALTER TABLE signals ADD COLUMN response_window REAL;
ALTER TABLE signals ADD COLUMN rs_acceleration REAL;
ALTER TABLE signals ADD COLUMN leader_rs_deceleration REAL;
ALTER TABLE signals ADD COLUMN outperformance_margin REAL;
```

### features_relative_strength Table Schema (pre-existing)
```sql
-- Source: utils/db.py init_schema() — verified by inspection
CREATE TABLE IF NOT EXISTS features_relative_strength (
    ticker_a        TEXT NOT NULL,
    ticker_b        TEXT NOT NULL,
    trading_day     TEXT NOT NULL,
    rs_value        REAL,           -- fractional decimal: 0.05 = 5%
    PRIMARY KEY (ticker_a, ticker_b, trading_day)
);
-- RS = rolling 10-session cumulative return of leader minus follower
-- Computed by features/relative_strength.py compute_relative_strength_for_pair()
```

### features_lagged_returns Table Schema (pre-existing)
```sql
-- Source: utils/db.py init_schema() — verified by inspection
CREATE TABLE IF NOT EXISTS features_lagged_returns (
    ticker          TEXT NOT NULL,
    trading_day     TEXT NOT NULL,
    lag             INTEGER NOT NULL,  -- -5 to +5 excluding 0
    return_value    REAL,
    PRIMARY KEY (ticker, trading_day, lag)
);
-- Stores both ticker_a (leader) and ticker_b (follower) data
-- Positive lag: past return (backward-looking); negative lag: future return
```

### Pipeline Scheduler Poll Interval (single constant to change)
```python
# Source: utils/pipeline_scheduler.py line 28 — verified by inspection
POLL_INTERVAL = 1800       # 30 minutes between checks  <- change to 900
PIPELINE_HOUR_ET = 17      # Don't run before 5 PM ET   <- unchanged
```

### Existing upsert_signal pattern — what changes
```python
# Source: leadlag_engine/db.py upsert_signal() — verified by inspection
# Current SET clause (mutable fields):
# optimal_lag, window_length, correlation_strength, stability_score,
# regime_state, direction, expected_target, invalidation_threshold,
# sizing_tier, flow_map_entry, data_warning
# -- generated_at is EXCLUDED (immutability anchor)
#
# Phase 7 additions to SET clause:
# action, response_window, rs_acceleration, leader_rs_deceleration,
# outperformance_margin
```

### Existing backtest run_backtest return shape (what we extend)
```python
# Source: backtest/engine.py run_backtest() — verified by inspection
# Current return dict keys:
# leader, follower, start_date, end_date, total_trades, winning_trades,
# hit_rate, mean_return_per_trade, annualized_sharpe, max_drawdown
#
# Phase 7 addition:
# by_action: {
#   'BUY':  {total_trades, winning_trades, hit_rate, mean_return, sharpe, drawdown, outperformance_vs_leader},
#   'HOLD': {same keys},
#   'SELL': {same keys},
#   'UNKNOWN': {same keys},  # for signals without action field (pre-Phase 7 data)
# }
# outperformance_vs_leader: mean(follower_return - leader_return) for signals in that action group
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| signals have no action classification | signals carry BUY/HOLD/SELL action | Phase 7 | Enables actionable trade guidance vs raw correlation |
| response_window not tracked | response_window derived from transition history | Phase 7 | Gives time-bound trade expectation |
| backtest metrics are aggregate only | backtest metrics disaggregated by action | Phase 7 | Validates signal quality per action category |
| RS used only for regime classification | RS slope used for acceleration metadata | Phase 7 | Captures momentum divergence between pair constituents |
| POLL_INTERVAL = 1800 (30 min) | POLL_INTERVAL = 900 (15 min) | Phase 7 | More responsive signal updates during trading day |

---

## Open Questions

1. **Response window session counting from transitions**
   - What we know: `signal_transitions` stores ISO-8601 UTC timestamps for each action change
   - What's unclear: Counting trading sessions between two timestamps requires joining against `normalized_bars` for the follower ticker — need to verify the query pattern is efficient
   - Recommendation: Use `COUNT(DISTINCT trading_day) FROM normalized_bars WHERE ticker=? AND trading_day BETWEEN ? AND ?` to count sessions. Cap the response_window computation at pairs with >= 2 complete BUY→exit cycles; return None otherwise.

2. **Backtest outperformance_vs_leader lookup**
   - What we know: `features_lagged_returns` stores both leader and follower returns at `lag=optimal_lag`; the backtest already queries follower returns
   - What's unclear: The outperformance computation requires fetching BOTH `ticker_b` (follower) and `ticker_a` (leader) returns at `signal_date` and `lag` — this means one extra `features_lagged_returns` query per signal in the backtest loop
   - Recommendation: Add a single additional JOIN or second query per signal row to retrieve `leader_return_value`. The backtest is SQLite-only so this is acceptable.

3. **SELL confirmation N sessions**
   - What we know: CONTEXT.md leaves N to Claude's discretion; recommends symmetric with BUY's 3-session threshold
   - What's unclear: Whether 3 sessions is sufficient to avoid false SELL signals on typical RS noise
   - Recommendation: Default `SELL_CONFIRMATION_SESSIONS = 3` (same as BUY). Make it a module-level constant in `signals/generator.py` so it can be changed without code search. Document the symmetry rationale in comments.

---

## Sources

### Primary (HIGH confidence)
- Direct inspection of `signals/generator.py` — full signal generation flow, field set, gate logic
- Direct inspection of `leadlag_engine/db.py` — complete signals table schema, upsert pattern, migration pattern
- Direct inspection of `utils/db.py` — full `init_schema()` including all feature table schemas
- Direct inspection of `backtest/engine.py` — current metrics, return shape, query patterns
- Direct inspection of `features/relative_strength.py` — RS computation: 10-session rolling, stored as fractional decimal
- Direct inspection of `features/lagged_returns.py` — lag offsets -5 to +5, both leader and follower stored
- Direct inspection of `utils/pipeline_scheduler.py` — POLL_INTERVAL = 1800, exact location of constant
- Direct inspection of `leadlag_engine/pipeline.py` — pipeline ordering, how generate_signal is called
- Direct inspection of `tests/conftest.py`, `tests/test_signals_generator.py`, `tests/test_backtest_engine.py` — test infrastructure, fixture patterns

### Secondary (MEDIUM confidence)
- CONTEXT.md Phase 7 decisions — user intent for BUY/HOLD/SELL logic, response window, RS acceleration

---

## Metadata

**Confidence breakdown:**
- Current schema / field inventory: HIGH — read directly from source files
- Architecture patterns: HIGH — derived from verified codebase patterns (migration, upsert, compute functions)
- New field computation logic: HIGH — RS data is in-DB, slope via numpy polyfit, outperformance margin arithmetic
- Response window from transitions: MEDIUM — bootstrap problem and session-counting query need care; pattern is correct but exact SQL not verified
- Pitfalls: HIGH — all derived from real code patterns observed in this codebase

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (codebase is stable; no external library churn risk)
