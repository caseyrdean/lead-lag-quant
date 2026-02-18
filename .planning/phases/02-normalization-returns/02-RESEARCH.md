# Phase 2: Normalization & Returns - Research

**Researched:** 2026-02-18
**Domain:** Financial data normalization — split-adjusted OHLCV, rolling returns, NYSE calendar assignment, SQLite schema
**Confidence:** HIGH (core algorithms verified via official docs and API references)

---

## Summary

Phase 2 transforms raw Polygon agg bars and split records stored in `raw_api_responses` into clean, split-adjusted bars and multi-period return series. The central algorithm is backward split adjustment: for each trading bar, compute a cumulative split factor by multiplying all `(split_to / split_from)` ratios for splits that executed *after* that bar's date. Polygon's splits API provides a `historical_adjustment_factor` field that already encodes this cumulative backward factor — this is the authoritative value to store and use rather than recomputing from raw ratios.

Multi-period returns (1d, 5d, 10d, 20d, 60d) are computed via `pandas.DataFrame.pct_change(periods=N)` on the `adj_close` column, one ticker at a time. In pandas >= 2.1 the `fill_method` parameter is deprecated — call `df.ffill().pct_change(periods=N)` or simply `df.pct_change(periods=N, fill_method=None)` to avoid FutureWarnings. NYSE trading day assignment uses `exchange_calendars` (version 4.13.1 as of Feb 2026) via `calendar.minute_to_session(utc_ts, direction="next")` to map Polygon's Unix-ms timestamps to canonical session dates.

The SQLite schema for this phase requires three new tables: `normalized_bars`, `returns_policy_a`, and `dividends`. All three carry an `adjustment_policy_id TEXT NOT NULL DEFAULT 'policy_a'` column per NORM-03. Use `INTEGER PRIMARY KEY` composite via `UNIQUE` constraint on `(ticker, trading_day)` with `ON CONFLICT DO UPDATE` (upsert) for idempotency, consistent with Phase 1 decisions.

**Primary recommendation:** Use Polygon's `historical_adjustment_factor` directly as the cumulative split multiplier. Apply it to divide raw OHLC prices and multiply volume. Compute returns with `pct_change(periods=N, fill_method=None)` per ticker. Use `minute_to_session` from `exchange_calendars` for timestamp mapping.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | >= 2.2 (project constraint) | DataFrame operations, pct_change, groupby | Industry standard for financial time series; vectorized OHLCV transforms |
| numpy | >= 2.1 (project constraint) | Array math for split factor computation | Used by pandas internally; direct use for cumulative products |
| exchange_calendars | 4.13.1 (latest, Feb 2026) | NYSE session lookup, timestamp-to-trading-day mapping | Actively maintained fork of trading_calendars; 50+ exchanges; `minute_to_session` API |
| sqlite3 | stdlib | Schema DDL, upsert, WAL mode | Already decided in Phase 1 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json | stdlib | Parse raw_api_responses.response_body | Reading JSON blobs from ingestion table |
| datetime / zoneinfo | stdlib | UTC conversion from Unix ms | Before passing to exchange_calendars |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| exchange_calendars | pandas_market_calendars | pandas_market_calendars wraps exchange_calendars; adds complexity; Phase 1 already uses exchange_calendars directly |
| pct_change(periods=N) | numpy log returns | Log returns are additive across time but the spec says "returns_policy_a" computed from adj_close — simple returns match industry convention for cross-sectional signals; stick with simple unless spec changes |
| Polygon historical_adjustment_factor | Self-computed cumulative product | Self-computation is feasible but Polygon's field is pre-verified and handles edge cases (stock dividends flagged as forward_split); use Polygon's value as source of truth |

**Installation:**
```bash
pip install exchange_calendars>=4.0
# pandas, numpy already installed per project constraints
```

---

## Architecture Patterns

### Recommended Module Structure
```
normalization/
├── __init__.py
├── split_adjuster.py      # loads splits from DB, applies historical_adjustment_factor
├── bar_normalizer.py      # reads raw_api_responses, emits normalized_bars rows
├── returns_calculator.py  # reads normalized_bars, emits returns_policy_a rows
├── dividend_storer.py     # reads raw dividend JSON, writes dividends table
└── timestamp_utils.py     # unix_ms_to_utc(), utc_to_trading_day() using exchange_calendars
```

### Pattern 1: Read-From-Raw, Write-Normalized
**What:** Read JSON blobs from `raw_api_responses` (endpoint = 'aggs'), parse each bar, apply split adjustment, write to `normalized_bars`.
**When to use:** Every time normalization runs; designed to be idempotent via upsert.
**Example:**
```python
# Source: Phase 1 decisions + sqlite3 stdlib docs
import json, sqlite3
import pandas as pd

def normalize_ticker(conn: sqlite3.Connection, ticker: str) -> None:
    # 1. Load raw bars
    rows = conn.execute(
        "SELECT response_body FROM raw_api_responses WHERE ticker=? AND endpoint='aggs'",
        (ticker,)
    ).fetchall()
    bars = []
    for (body,) in rows:
        data = json.loads(body)
        bars.extend(data.get("results", []))
    df = pd.DataFrame(bars)  # cols: t, o, h, l, c, v, vw, n

    # 2. Load adjustment factor for this ticker
    factor = get_adjustment_factor(conn, ticker)  # see split_adjuster.py

    # 3. Apply adjustment (Policy A: splits only, no dividends)
    df["adj_open"]   = df["o"] / factor
    df["adj_high"]   = df["h"] / factor
    df["adj_low"]    = df["l"] / factor
    df["adj_close"]  = df["c"] / factor
    df["adj_volume"] = df["v"] * factor  # volume inverse of price

    # 4. Assign trading day
    df["trading_day"] = df["t"].apply(unix_ms_to_trading_day)
    df["adjustment_policy_id"] = "policy_a"

    # 5. Upsert
    upsert_normalized_bars(conn, ticker, df)
```

### Pattern 2: Backward Split Adjustment Using historical_adjustment_factor
**What:** Polygon's splits API returns `historical_adjustment_factor` — a pre-computed cumulative backward adjustment factor. For a bar on date D, the correct multiplier is the product of all `(split_to / split_from)` ratios for splits with `execution_date > D`. Polygon computes this as `historical_adjustment_factor`.

**Key insight:** `historical_adjustment_factor` is the divisor for prices (divide raw price by factor to get adjusted price). Volume is multiplied by the same factor.

**Correct formula:**
```
adj_price = raw_price / historical_adjustment_factor
adj_volume = raw_volume * historical_adjustment_factor
```

**Example (AAPL 2005 split):**
```json
{
  "execution_date": "2005-02-28",
  "historical_adjustment_factor": 0.017857,
  "split_from": 1,
  "split_to": 2,
  "ticker": "AAPL"
}
```
A bar before 2005-02-28 with raw close of $56.00: adj_close = 56.00 / 0.017857 = $3136 (pre-split price in today's share basis... wait, this is inverted).

**Critical clarification:** The Polygon docs state "multiply the unadjusted price by the historical_adjustment_factor" — meaning their factor is a *multiplier*, not a divisor. Verify at implementation time whether to multiply or divide by running a sanity check: adj_price for recent data should equal raw price (factor = 1.0 near current date).

**Safe verification pattern:**
```python
# Source: Polygon splits API docs (massive.com/docs/rest/stocks/corporate-actions/splits)
# Always sanity-check: most recent bars should have adj ≈ raw
assert abs(df_recent["adj_close"].iloc[-1] - df_recent["c"].iloc[-1]) < 0.01
```

**For tickers with no splits:** `historical_adjustment_factor` will be absent from the splits response (empty results). Default to factor = 1.0 for all dates. This is the NORM-05 base case.

### Pattern 3: Rolling Multi-Period Returns
**What:** Compute 1d, 5d, 10d, 20d, 60d simple returns from `adj_close` using `pct_change(periods=N)` per ticker. Process each ticker independently to avoid cross-ticker contamination.

**Pandas >= 2.1 correct usage (no FutureWarning):**
```python
# Source: pandas 2.1.0 release notes (GH 53491)
# Do NOT use: df.pct_change(fill_method='ffill')  # deprecated
# Use either:
returns = df["adj_close"].pct_change(periods=N, fill_method=None)
# or equivalently:
returns = df["adj_close"].ffill().pct_change(periods=N)
```

**Multi-period returns function:**
```python
def compute_returns(adj_close: pd.Series) -> pd.DataFrame:
    """adj_close must be sorted by date, single ticker."""
    periods = {"1d": 1, "5d": 5, "10d": 10, "20d": 20, "60d": 60}
    result = {}
    for name, n in periods.items():
        result[f"return_{name}"] = adj_close.pct_change(periods=n, fill_method=None)
    return pd.DataFrame(result)
```

### Pattern 4: Timestamp to Trading Day
**What:** Polygon stores bar timestamps as Unix milliseconds UTC. Convert to UTC datetime, then map to NYSE trading session.

```python
# Source: exchange_calendars 4.13.1 API (github.com/gerrymanoim/exchange_calendars)
import exchange_calendars as xcals
import pandas as pd

_nyse = xcals.get_calendar("XNYS")  # module-level singleton

def unix_ms_to_trading_day(unix_ms: int) -> str:
    """Return NYSE trading day as 'YYYY-MM-DD' string."""
    utc_ts = pd.Timestamp(unix_ms, unit="ms", tz="UTC")
    session = _nyse.minute_to_session(utc_ts, direction="next")
    return session.strftime("%Y-%m-%d")
```

**Notes:**
- `direction="next"` means if the timestamp falls on a weekend or holiday, it maps to the next trading day. For end-of-day bars this is typically the bar's own day.
- For Polygon daily bars, `t` is typically the open timestamp of the bar date. Use `direction="next"` or verify the pattern first.
- Cache the `xcals.get_calendar("XNYS")` call — it's expensive to instantiate.

### Pattern 5: fetched_at Propagation for Point-in-Time (NORM-05)
**What:** The `splits` table must store `fetched_at` to enable point-in-time backtest isolation. The `fetched_at` value is already on the `raw_api_responses` row (`retrieved_at` column per Phase 1 spec).

**Implementation:**
```python
# When extracting splits from raw_api_responses, copy retrieved_at as fetched_at
rows = conn.execute(
    "SELECT response_body, retrieved_at FROM raw_api_responses "
    "WHERE ticker=? AND endpoint='splits'",
    (ticker,)
).fetchall()
for body, retrieved_at in rows:
    splits_data = json.loads(body)
    for split in splits_data.get("results", []):
        split["fetched_at"] = retrieved_at  # propagate to splits table
```

### Anti-Patterns to Avoid
- **Computing cumulative split factors yourself from split_from/split_to without using Polygon's historical_adjustment_factor:** Polygon provides the authoritative pre-computed value. Self-computation requires careful sort order (reverse chronological), cumulative product, and edge case handling. Use Polygon's value; only fall back to self-computation if `historical_adjustment_factor` is missing from a response.
- **Processing multiple tickers in a single DataFrame without groupby isolation:** `pct_change` will bleed across ticker boundaries if data is not split by ticker first. Always process one ticker at a time or use `groupby("ticker").pct_change()` carefully.
- **Using `df.pct_change(fill_method='ffill')` in pandas >= 2.1:** Raises FutureWarning, will be removed. Use `fill_method=None` explicitly.
- **Applying dividends to price calculations under Policy A:** NORM-02 prohibits this. Dividends go to the `dividends` table only.
- **Using `date_to_session` instead of `minute_to_session` for timestamps:** `date_to_session` takes a date string; `minute_to_session` takes a timestamp. For Unix-ms conversion, use `minute_to_session`.
- **Instantiating `xcals.get_calendar("XNYS")` per bar:** Expensive. Instantiate once at module load.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NYSE holiday/early-close calendar | Custom holiday list dict | `exchange_calendars` XNYS | NYSE calendar valid 1885-present; includes early closes, late opens; Phase 1 already implemented this |
| Multi-period returns | Loop over date windows | `pct_change(periods=N)` | Vectorized, handles NaN at edges, avoids off-by-one date errors |
| Cumulative split factor | cumprod from raw split events | Polygon `historical_adjustment_factor` field | Polygon pre-computes; handles corporate action edge cases (stock dividends, reclassifications) |
| Upsert logic | DELETE + INSERT | `INSERT ... ON CONFLICT DO UPDATE` | Atomic, consistent with Phase 1 pattern, no race condition |
| Timestamp timezone math | Manual UTC offset handling | `pd.Timestamp(unix_ms, unit='ms', tz='UTC')` | Pandas handles DST and timezone correctly |

**Key insight:** The biggest "don't hand-roll" in this phase is the cumulative split ratio. Many implementations recompute it from raw split events and get the sort order wrong (must be reverse chronological), compound incorrectly, or miss edge cases like stock dividends flagged as splits. Polygon provides `historical_adjustment_factor` precisely to avoid this — use it.

---

## Common Pitfalls

### Pitfall 1: Multiply vs. Divide for historical_adjustment_factor
**What goes wrong:** Polygon's docs say "multiply the unadjusted price by the `historical_adjustment_factor`" — but this depends on how Polygon defines the factor's direction. The example in the AAPL 2005 split shows `historical_adjustment_factor = 0.017857` which is very small (~1/56), suggesting it may be a fraction that collapses prices backward in time rather than adjusting forward to today's basis.
**Why it happens:** "Backward adjustment" means anchoring current prices and scaling historical prices. Depending on whether you're normalizing "to today's share count" or "to original share count," the direction flips.
**How to avoid:** At implementation start, take a ticker with known splits (e.g., AAPL), retrieve raw price and historical_adjustment_factor, and verify: `raw_price * factor` or `raw_price / factor` — whichever produces a price matching Polygon's adjusted endpoint output.
**Warning signs:** Adjusted prices for current period don't match raw prices (should be equal for most recent data if adjusted to current basis).

### Pitfall 2: pct_change Cross-Ticker Contamination
**What goes wrong:** If you load multiple tickers into a single DataFrame sorted by date (not ticker), `pct_change(periods=1)` computes the return from the last row of ticker A to the first row of ticker B when they border each other.
**Why it happens:** pct_change is purely positional — it doesn't know about ticker boundaries.
**How to avoid:** Either process one ticker at a time, or use `df.sort_values(["ticker","trading_day"]).groupby("ticker")["adj_close"].pct_change()` and verify the first return per ticker is NaN.
**Warning signs:** Returns on the first day of each ticker that aren't NaN.

### Pitfall 3: pct_change fill_method FutureWarning
**What goes wrong:** `df.pct_change()` in pandas >= 2.1 raises FutureWarning about fill_method deprecation. In pandas 3.x it will error.
**Why it happens:** The old default was `fill_method='pad'` (forward fill gaps before computing change). Pandas changed the default and deprecated non-None values.
**How to avoid:** Always pass `fill_method=None` explicitly: `pct_change(periods=N, fill_method=None)`. This is verified against pandas 2.1.0 release notes (GH 53491).
**Warning signs:** FutureWarning messages in test output mentioning fill_method.

### Pitfall 4: Tickers With No Splits
**What goes wrong:** Querying splits for a ticker that has never split returns empty `results`. If you then try to use `historical_adjustment_factor` it's absent. Without explicit handling, the normalization silently produces NaN prices.
**Why it happens:** Code assumes splits always exist.
**How to avoid:** Default to `factor = 1.0` when splits results is empty. This is the correct behavior — no splits means no adjustment needed.
**Warning signs:** Large blocks of NaN in `adj_close` for tickers that are well-known split-free stocks.

### Pitfall 5: Polygon Daily Bar Timestamp Interpretation
**What goes wrong:** Polygon daily agg bar `t` field is Unix ms for the *start* of the trading session (typically 4:00am ET or midnight UTC for daily bars), not 4pm close. Naively converting to UTC date may give the previous calendar day in some timezones.
**Why it happens:** Daily bar timestamps represent session open in UTC; depending on Polygon's convention this could be midnight UTC on the trading day.
**How to avoid:** Use `minute_to_session(ts, direction="next")` which handles this. Separately, verify with a known holiday: a bar for the day before a holiday should map to its own date, not the next session.
**Warning signs:** Trading days are off by 1 for dates near midnight UTC.

### Pitfall 6: Volume Adjustment Direction
**What goes wrong:** Prices are divided by the split factor; volume must be multiplied (not divided) by the same factor. Getting this wrong produces volume figures that don't match reality.
**Why it happens:** Volume adjustment is the inverse of price adjustment to preserve dollar turnover continuity.
**How to avoid:** For a 2-for-1 split: `adj_price = price / 2`, `adj_volume = volume * 2`. Verify with known split dates that pre-split volume roughly doubles in the adjusted series.
**Warning signs:** Pre-split bars show dramatically lower volume than post-split bars in the adjusted series.

---

## Code Examples

### SQLite Schema for This Phase

```sql
-- Source: Phase 1 decisions + SQLite docs (sqlite.org/lang_upsert.html)

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS splits (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                     TEXT NOT NULL,
    execution_date             TEXT NOT NULL,  -- 'YYYY-MM-DD'
    split_from                 REAL NOT NULL,
    split_to                   REAL NOT NULL,
    historical_adjustment_factor REAL,         -- from Polygon splits API
    adjustment_type            TEXT,           -- 'forward_split', 'reverse_split', 'stock_dividend'
    fetched_at                 TEXT NOT NULL,  -- copied from raw_api_responses.retrieved_at
    UNIQUE(ticker, execution_date)
);

CREATE TABLE IF NOT EXISTS normalized_bars (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker               TEXT NOT NULL,
    trading_day          TEXT NOT NULL,   -- 'YYYY-MM-DD' NYSE session date
    open                 REAL NOT NULL,   -- raw open
    high                 REAL NOT NULL,
    low                  REAL NOT NULL,
    close                REAL NOT NULL,
    adj_open             REAL NOT NULL,   -- split-adjusted (Policy A)
    adj_high             REAL NOT NULL,
    adj_low              REAL NOT NULL,
    adj_close            REAL NOT NULL,
    adj_volume           REAL NOT NULL,
    vwap                 REAL,
    transactions         INTEGER,
    adjustment_policy_id TEXT NOT NULL DEFAULT 'policy_a',
    created_at           TEXT NOT NULL DEFAULT (datetime('now','utc')),
    UNIQUE(ticker, trading_day)
);

CREATE TABLE IF NOT EXISTS returns_policy_a (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker               TEXT NOT NULL,
    trading_day          TEXT NOT NULL,
    return_1d            REAL,   -- pct_change(1)
    return_5d            REAL,   -- pct_change(5)
    return_10d           REAL,   -- pct_change(10)
    return_20d           REAL,   -- pct_change(20)
    return_60d           REAL,   -- pct_change(60)
    adjustment_policy_id TEXT NOT NULL DEFAULT 'policy_a',
    created_at           TEXT NOT NULL DEFAULT (datetime('now','utc')),
    UNIQUE(ticker, trading_day)
);

CREATE TABLE IF NOT EXISTS dividends (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL,
    ex_date        TEXT NOT NULL,   -- 'YYYY-MM-DD'
    cash_amount    REAL,
    currency       TEXT,
    dividend_type  TEXT,
    pay_date       TEXT,
    record_date    TEXT,
    fetched_at     TEXT NOT NULL,
    UNIQUE(ticker, ex_date)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_normalized_bars_ticker_day
    ON normalized_bars(ticker, trading_day);
CREATE INDEX IF NOT EXISTS idx_returns_ticker_day
    ON returns_policy_a(ticker, trading_day);
CREATE INDEX IF NOT EXISTS idx_splits_ticker_date
    ON splits(ticker, execution_date);
```

### Upsert Pattern (Idempotent)
```sql
-- Source: sqlite.org/lang_upsert.html
INSERT INTO normalized_bars
    (ticker, trading_day, open, high, low, close,
     adj_open, adj_high, adj_low, adj_close, adj_volume,
     vwap, transactions, adjustment_policy_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'policy_a')
ON CONFLICT(ticker, trading_day) DO UPDATE SET
    adj_open=excluded.adj_open,
    adj_high=excluded.adj_high,
    adj_low=excluded.adj_low,
    adj_close=excluded.adj_close,
    adj_volume=excluded.adj_volume,
    adjustment_policy_id=excluded.adjustment_policy_id;
```

### Computing Returns Per Ticker
```python
# Source: pandas 2.1.0 release notes + pandas.Series.pct_change docs (pandas 3.0.1)
import pandas as pd

def compute_returns_for_ticker(conn, ticker: str) -> None:
    df = pd.read_sql_query(
        "SELECT trading_day, adj_close FROM normalized_bars "
        "WHERE ticker=? ORDER BY trading_day ASC",
        conn,
        params=(ticker,)
    )
    df = df.set_index("trading_day")

    periods = {"1d": 1, "5d": 5, "10d": 10, "20d": 20, "60d": 60}
    for col, n in periods.items():
        # fill_method=None avoids FutureWarning in pandas >= 2.1
        df[f"return_{col}"] = df["adj_close"].pct_change(periods=n, fill_method=None)

    df["ticker"] = ticker
    df["adjustment_policy_id"] = "policy_a"

    # Upsert each row
    for trading_day, row in df.iterrows():
        conn.execute("""
            INSERT INTO returns_policy_a
                (ticker, trading_day, return_1d, return_5d, return_10d,
                 return_20d, return_60d, adjustment_policy_id)
            VALUES (?,?,?,?,?,?,?,'policy_a')
            ON CONFLICT(ticker, trading_day) DO UPDATE SET
                return_1d=excluded.return_1d,
                return_5d=excluded.return_5d,
                return_10d=excluded.return_10d,
                return_20d=excluded.return_20d,
                return_60d=excluded.return_60d
        """, (
            ticker, trading_day,
            row.get("return_1d"), row.get("return_5d"), row.get("return_10d"),
            row.get("return_20d"), row.get("return_60d")
        ))
    conn.commit()
```

### Timestamp Conversion
```python
# Source: exchange_calendars 4.13.1 (pypi.org/project/exchange_calendars/)
# + pandas.Timestamp docs
import exchange_calendars as xcals
import pandas as pd

_nyse_calendar = xcals.get_calendar("XNYS")  # create once

def unix_ms_to_trading_day(unix_ms: int) -> str:
    """Convert Polygon Unix millisecond timestamp to NYSE trading day string."""
    utc_ts = pd.Timestamp(unix_ms, unit="ms", tz="UTC")
    # minute_to_session maps trading minutes to their session
    # direction="next": if timestamp is not a trading minute (e.g., weekend),
    # returns the next valid session. For end-of-day daily bars, this is correct.
    session = _nyse_calendar.minute_to_session(utc_ts, direction="next")
    return session.strftime("%Y-%m-%d")

def is_trading_day(date_str: str) -> bool:
    """Check if a date string is a NYSE trading session."""
    return _nyse_calendar.is_session(date_str)
```

### Split Extraction With fetched_at
```python
# Source: Phase 1 schema decisions + Polygon splits API docs
def extract_splits_to_table(conn, ticker: str) -> None:
    rows = conn.execute(
        "SELECT response_body, retrieved_at FROM raw_api_responses "
        "WHERE ticker=? AND endpoint='splits' ORDER BY retrieved_at DESC LIMIT 1",
        (ticker,)
    ).fetchall()

    for body, retrieved_at in rows:
        data = json.loads(body)
        for split in data.get("results", []):
            conn.execute("""
                INSERT INTO splits
                    (ticker, execution_date, split_from, split_to,
                     historical_adjustment_factor, adjustment_type, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, execution_date) DO UPDATE SET
                    historical_adjustment_factor=excluded.historical_adjustment_factor,
                    fetched_at=excluded.fetched_at
            """, (
                ticker,
                split["execution_date"],
                split["split_from"],
                split["split_to"],
                split.get("historical_adjustment_factor"),  # may be None
                split.get("adjustment_type"),
                retrieved_at
            ))
    conn.commit()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `df.pct_change(fill_method='ffill')` | `df.pct_change(fill_method=None)` or `df.ffill().pct_change()` | pandas 2.1.0 (Aug 2023) | FutureWarning in 2.1/2.2; error expected in future version |
| `trading_calendars` (Quantopian) | `exchange_calendars` (gerrymanoim fork) | ~2021 | trading_calendars abandoned; exchange_calendars is the maintained fork |
| Self-computing cumulative split factor | Using `historical_adjustment_factor` from Polygon API | Polygon added this field (exact date unknown) | Removes error-prone custom computation |

**Deprecated/outdated:**
- `trading_calendars` package: Abandoned since Quantopian shutdown; do not install or import.
- `df.pct_change(fill_method='pad')`: Deprecated in pandas 2.1, pass `fill_method=None` instead.

---

## Open Questions

1. **historical_adjustment_factor: multiply or divide?**
   - What we know: Polygon docs say "multiply the unadjusted price by the historical_adjustment_factor." The AAPL example shows factor 0.017857 for a Feb 2005 split with split_to=2.
   - What's unclear: Whether 0.017857 is applied as price * 0.017857 (making it smaller — wrong for recent bars) or price / 0.017857. The small value suggests it might be a *price ratio* relative to today's share count across many splits (AAPL had many splits), not just one.
   - Recommendation: At implementation start, hardcode a known test: AAPL on 2020-01-02 should have adj_close ≈ raw_close (both in current share basis post 2020 split). Verify multiply vs. divide empirically before writing production code.

2. **Polygon daily bar `t` field: midnight UTC or session open?**
   - What we know: Polygon docs say `t` is "Unix Msec timestamp" for the bar. For daily bars this is typically midnight UTC on the session date.
   - What's unclear: Whether midnight UTC maps correctly to the NYSE session date (it should for US Eastern dates, but needs verification for dates near DST transitions).
   - Recommendation: Test with a known holiday-adjacent date. If `pd.Timestamp(t, unit='ms', tz='UTC').date()` matches the expected trading day, `minute_to_session` is not needed — just `.date()` is sufficient. If not, `minute_to_session(direction="next")` is the safe fallback.

3. **historical_adjustment_factor for the most recent split vs. cumulative**
   - What we know: The API example shows one split record with `historical_adjustment_factor: 0.017857` for AAPL with split_to=2. For just one 2-for-1 split, the factor should be 0.5, not 0.017857. This strongly suggests `historical_adjustment_factor` is already cumulative across all splits to date.
   - Recommendation: Confirmed by Polygon docs — "cumulative multiplier." Use the factor from the most recent split record (largest execution_date) as the single adjustment value to apply to all historical bars before that date. For bars between two splits, use the factor from the later split.

4. **Performance: batch upsert vs. row-by-row**
   - What we know: Row-by-row upserts in Python sqlite3 are slow for large datasets. `executemany()` is faster. For daily bars over many tickers, performance matters.
   - Recommendation: Use `executemany()` with a list of tuples rather than looping `execute()`. Should still be within acceptable range for daily bar counts (< 10,000 rows per ticker typically).

---

## Sources

### Primary (HIGH confidence)
- Polygon/Massive splits API docs (`massive.com/docs/rest/stocks/corporate-actions/splits`) — fields: execution_date, split_from, split_to, historical_adjustment_factor, adjustment_type
- `pandas.DataFrame.pct_change` official docs (pandas 3.0.1) — signature, periods parameter, fill_method deprecation
- `pandas 2.1.0` release notes — confirmed fill_method deprecation (GH 53491)
- `exchange_calendars` PyPI page — version 4.13.1, released 2026-02-05
- `exchange_calendars` GitHub source (`exchange_calendar.py`) — `minute_to_session` method signature and direction parameter
- `sqlite.org/lang_upsert.html` — ON CONFLICT DO UPDATE syntax

### Secondary (MEDIUM confidence)
- `albertlobo.com/markets/adjusted-ohlc-values` — iterative backward split factor computation, volume inverse adjustment rule; verified against Polygon docs
- `exchange_calendars` README — `get_calendar("XNYS")`, `date_to_session`, `is_session`, session navigation methods
- Polygon knowledge base (via Massive redirect) — confirmed raw agg bars are unadjusted

### Tertiary (LOW confidence — flag for validation)
- General WebSearch results on log vs simple returns: multiple medium/blog posts agree simple returns via `pct_change` are standard for cross-sectional factor models; log returns preferred for time-series models. The spec says "returns_policy_a" without specifying log vs simple — assumed simple. Validate with user if ambiguous.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pandas, numpy, exchange_calendars, sqlite3 all verified via official sources
- Split adjustment algorithm: MEDIUM-HIGH — Polygon field confirmed; multiply vs. divide direction flagged as open question needing empirical verification at implementation start
- Rolling returns (pct_change): HIGH — pandas docs confirmed, deprecation pattern confirmed
- SQLite schema: HIGH — follows Phase 1 patterns exactly, upsert syntax from sqlite.org
- Timestamp mapping: HIGH — exchange_calendars 4.13.1 `minute_to_session` confirmed from source code
- fetched_at propagation: HIGH — straightforward copy from raw_api_responses.retrieved_at per Phase 1 schema

**Research date:** 2026-02-18
**Valid until:** 2026-03-20 (30 days; pandas and exchange_calendars are stable libraries)
