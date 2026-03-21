# Phase 6: Backtest & Visualization - Research

**Researched:** 2026-03-21
**Domain:** Python backtest engine (SQLite-only), FastAPI endpoints, React/Recharts visualization panels
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BACKTEST-01 | Backtest module reads from SQLite stored data only — never calls Polygon API | SQLite schema fully mapped; all needed data (normalized_bars, returns_policy_a, signals, splits) is present; backtest module goes in backtest/ package |
| BACKTEST-02 | Backtest adjustment path filters split records to `fetched_at <= backtest_date` (no look-ahead bias) | splits table has fetched_at column (TEXT, ISO-8601); filter pattern: `WHERE ticker=? AND execution_date <= ? AND fetched_at <= ?` |
| BACKTEST-03 | Backtest reports: hit rate, mean return per trade, annualized Sharpe ratio, maximum drawdown | Sharpe/drawdown computation already established in paper_trading/analytics.py; pattern confirmed reusable |
| UI-02 | Lead-Lag Charts panel — cross-correlation heatmap across lags, rolling optimal correlation over time | features_cross_correlation table has all required data; heatmap via Recharts or HTML table (same pattern as MonthlyHeatmap); rolling optimal via line chart |
| UI-03 | Regime State panel — current Bull/Base/Bear/Failure with all indicator values (RS, MA position, ATR, volume) | regime_states table has rs_value, price_vs_21ma, price_vs_50ma, atr_ratio; distribution_events has volume_ratio, vwap_rejection_streak |
| UI-05 | Backtest Results panel — hit rate, mean return, Sharpe, max drawdown for user-selected pair and date range | New FastAPI endpoint returns JSON; React component with pair selector + date range inputs + stat cards |
</phase_requirements>

---

## Summary

Phase 6 is a pure data-access phase — all required data already lives in SQLite from Phases 1-4. The backtest module must be a new Python package (`backtest/`) that reads exclusively from SQLite and never touches the Polygon API. The three SQLite tables critical to backtest are: `signals` (which trades to simulate), `normalized_bars` / `returns_policy_a` (what prices and returns occurred), and `splits` (for point-in-time adjustment using `fetched_at <= backtest_date`).

The frontend stack is React 19 + Recharts 3 + Tailwind CSS 4. All existing charts use Recharts (not Plotly — Plotly is only used server-side in paper_trading/analytics.py for a legacy code path that is not consumed by the React frontend). The React frontend fetches JSON from FastAPI REST endpoints using the `api` object in `frontend/src/lib/api.ts`. New pages require: a new page component in `frontend/src/pages/`, new route in `App.tsx`, sidebar link added to `Sidebar.tsx`, and new API methods in `api.ts`. The existing `types/index.ts` needs new interface definitions for backtest results, xcorr heatmap points, and regime state.

The three new React pages (BacktestPage, LeadLagChartsPage, RegimeStatePage) follow a consistent pattern: `useEffect` calls `api.xxx.yyy()` on mount, state is stored with `useState`, empty/loading states render informative placeholders, and charts use `<ResponsiveContainer>`. No new npm packages are needed — Recharts already provides Heatmap-equivalent via table (same technique as MonthlyHeatmap.tsx) and line/bar charts for all required visualizations.

**Primary recommendation:** Build `backtest/engine.py` first (pure Python, testable in isolation), then FastAPI endpoints in `api/routes/backtest.py`, then React pages consuming those endpoints. Follow the exact pattern of `paper_trading/analytics.py` + `api/routes/analytics.py` + `frontend/src/pages/AnalyticsPage.tsx` as the blueprint throughout.

---

## Standard Stack

### Core (already installed — no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | >=2.1 | DataFrame operations for signal simulation, return series, drawdown | Already in pyproject.toml; used throughout all phases |
| numpy | >=1.26 | Sharpe ratio computation (sqrt(252)), drawdown arrays | Already in pyproject.toml |
| sqlite3 | stdlib | SQLite reads for backtest data | Project pattern: raw sqlite3, no ORM |
| fastapi | current | REST endpoints for backtest results, xcorr data, regime state | Already the project API framework |
| recharts | 3.8.0 | React charts — line, area, bar, and table-based heatmap | Already installed in frontend; all existing charts use it |
| react-router-dom | 7.13.1 | New page routes for Backtest, Lead-Lag Charts, Regime State | Already installed |
| tailwindcss | 4.2.2 | Styling consistent with all existing components | Already installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| math (stdlib) | stdlib | math.sqrt(252) for annualization | Already used in paper_trading/analytics.py |
| structlog | current | Logging in backtest module | Project logging convention (get_logger) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom heatmap via HTML table | Recharts Heatmap or Plotly | HTML table already proven by MonthlyHeatmap.tsx; no new dependency needed |
| pandas for backtest returns | numpy arrays only | pandas is cleaner for date-indexed series; already a dependency |

**Installation:** No new Python or npm packages required. All dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure
```
backtest/
├── __init__.py          # empty
└── engine.py            # run_backtest(), _compute_hit_rate(), _compute_sharpe(), _compute_max_drawdown()

api/routes/
└── backtest.py          # GET /api/backtest/run, GET /api/backtest/xcorr, GET /api/backtest/regime

frontend/src/
├── pages/
│   ├── BacktestPage.tsx       # UI-05: pair selector, date range, result cards
│   ├── LeadLagChartsPage.tsx  # UI-02: xcorr heatmap + rolling optimal correlation line
│   └── RegimeStatePage.tsx    # UI-03: regime badge + indicator value table
├── components/
│   └── backtest/
│       ├── BacktestControls.tsx     # pair/date inputs + run button
│       ├── BacktestResultCards.tsx  # stat cards: hit rate, mean return, Sharpe, drawdown
│       ├── XcorrHeatmap.tsx         # lag × date heatmap (HTML table approach)
│       ├── RollingOptimalChart.tsx  # line chart of optimal lag correlation over time
│       └── RegimeStatePanel.tsx     # badge + indicator table
└── types/index.ts               # add: BacktestResult, XcorrHeatmapPoint, RegimeStateEntry
```

### Pattern 1: Backtest Module Structure (mirror paper_trading/analytics.py)
**What:** Pure Python functions that read SQLite, compute stats, return plain dicts. No API calls.
**When to use:** Every backtest computation. Never call Polygon inside backtest/.

```python
# Source: mirrors paper_trading/analytics.py pattern
# backtest/engine.py

import sqlite3
import math
import pandas as pd
from utils.logging import get_logger

def run_backtest(
    conn: sqlite3.Connection,
    leader: str,
    follower: str,
    start_date: str,      # ISO-8601: "2024-01-01"
    end_date: str,        # ISO-8601: "2025-01-01"
) -> dict:
    """Run a stored-data backtest for a pair over a date range.

    BACKTEST-01: reads only from SQLite — never calls Polygon API.
    BACKTEST-02: filters splits with fetched_at <= backtest_date.
    BACKTEST-03: returns hit_rate, mean_return, sharpe_ratio, max_drawdown.

    Returns dict with keys:
        hit_rate, mean_return_per_trade, annualized_sharpe, max_drawdown,
        total_trades, winning_trades, start_date, end_date, leader, follower
    Returns zero-dict if no signals in date range.
    """
    log = get_logger("backtest.engine")
    # Step 1: Load signals in date range for this pair
    # Step 2: For each signal, look up follower return over lag window
    #         using returns_policy_a (already split-adjusted via Policy A)
    # Step 3: Compute metrics
```

### Pattern 2: Look-Ahead Bias Prevention (BACKTEST-02)
**What:** Filter splits table to only those that were "known" as of backtest_date using fetched_at.
**When to use:** Any point-in-time adjustment recalculation in the backtest.

The key insight from the codebase: `normalized_bars` already stores split-adjusted prices computed with Policy A. The backtest can directly use `normalized_bars.adj_close` and `returns_policy_a.return_Nd` without re-running normalization — these are stored results. The `fetched_at` filter on `splits` is for any scenario where the backtest needs to reconstruct what adjustment factors were "known" at a given date. For the v1 backtest using stored returns, the primary bias vector is **signal selection**: only use signals with `signal_date <= backtest_date`, not future signals.

```python
# BACKTEST-02: look-ahead bias prevention on splits (if adjustment recalculation is needed)
# Source: STATE.md decision [02-01]
splits_df = pd.read_sql_query("""
    SELECT * FROM splits
    WHERE ticker = ?
      AND execution_date <= ?
      AND fetched_at <= ?
    ORDER BY execution_date ASC
""", conn, params=(ticker, backtest_date, backtest_date))

# For v1 backtest using pre-computed returns_policy_a:
# Signal date filter is the primary bias control:
signals_df = pd.read_sql_query("""
    SELECT * FROM signals
    WHERE ticker_a = ? AND ticker_b = ?
      AND signal_date >= ? AND signal_date <= ?
    ORDER BY signal_date ASC
""", conn, params=(leader, follower, start_date, end_date))
```

### Pattern 3: FastAPI Route (mirror api/routes/analytics.py)
**What:** Router with GET endpoints, `Conn` dependency, try/except returning JSONResponse on error.
**When to use:** Every new backtest endpoint.

```python
# Source: api/routes/analytics.py pattern — HIGH confidence (read directly from codebase)
# api/routes/backtest.py

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from api.deps import Conn
from backtest.engine import run_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])

@router.get("/run")
def api_run_backtest(
    conn: Conn,
    leader: str,
    follower: str,
    start_date: str,
    end_date: str,
):
    try:
        return run_backtest(conn, leader, follower, start_date, end_date)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
```

Register in `api/main.py`:
```python
from api.routes import backtest
app.include_router(backtest.router, prefix="/api")
```

### Pattern 4: React Page (mirror AnalyticsPage.tsx + StatsCards.tsx)
**What:** Page component uses `useState` + `useEffect` to fetch from API. Stat values in `Card` components.
**When to use:** BacktestPage (UI-05), LeadLagChartsPage (UI-02), RegimeStatePage (UI-03).

```typescript
// Source: frontend/src/pages/AnalyticsPage.tsx + StatsCards.tsx patterns
// frontend/src/pages/BacktestPage.tsx

import { useState } from "react";
import { api } from "../lib/api";
import type { BacktestResult } from "../types";

export default function BacktestPage() {
  const [leader, setLeader] = useState("");
  const [follower, setFollower] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);

  const runBacktest = () => {
    setLoading(true);
    api.backtest.run(leader, follower, startDate, endDate)
      .then((d) => setResult(d as unknown as BacktestResult))
      .finally(() => setLoading(false));
  };
  // ...
}
```

### Pattern 5: XCross-Correlation Heatmap (mirror MonthlyHeatmap.tsx)
**What:** HTML table rendering heatmap cells, colored by correlation strength. No extra library needed.
**When to use:** UI-02 cross-correlation heatmap across lags.

```typescript
// Source: frontend/src/components/analytics/MonthlyHeatmap.tsx pattern
// Rows = lags (-5 to +5), Columns = trading_days (sparse/recent)
// Cell background: green for positive correlation, red for negative, intensity = |correlation|
function corrColor(value: number | null): string {
  if (value == null) return "transparent";
  const intensity = Math.min(Math.abs(value), 1);
  if (value >= 0) return `rgba(34, 197, 94, ${0.15 + intensity * 0.65})`;
  return `rgba(239, 68, 68, ${0.15 + intensity * 0.65})`;
}
```

### Pattern 6: api.ts Extension
**What:** Add new method groups to the `api` object in `frontend/src/lib/api.ts`.
**When to use:** All new Phase 6 API calls.

```typescript
// Source: frontend/src/lib/api.ts pattern
// Add to the api object:
backtest: {
  run: (leader: string, follower: string, startDate: string, endDate: string) =>
    request<BacktestResult>(
      `/backtest/run?leader=${leader}&follower=${follower}&start_date=${startDate}&end_date=${endDate}`
    ),
  xcorr: (leader: string, follower: string, days?: number) =>
    request<XcorrHeatmapPoint[]>(
      `/backtest/xcorr?leader=${leader}&follower=${follower}&days=${days ?? 180}`
    ),
  regime: (leader: string, follower: string) =>
    request<RegimeStateEntry>(`/backtest/regime?leader=${leader}&follower=${follower}`),
},
```

### Anti-Patterns to Avoid
- **Calling Polygon inside backtest/**: BACKTEST-01 is absolute. The backtest package must never import from `ingestion_massive/` or use `PolygonClient`.
- **Recomputing cross-correlations in the backtest**: Phase 3 already computed and stored them in `features_cross_correlation`. Read from there.
- **Using Plotly in the React frontend**: The existing charts use Recharts, not Plotly. Plotly is only used in `paper_trading/analytics.py` (a legacy server-side path not consumed by React). All Phase 6 React charts must use Recharts.
- **Importing from Gradio (ui/)**: ui/ was deleted in Plan 05.1-04.
- **Modifying `normalized_bars` or `returns_policy_a` from backtest**: Backtest is read-only. It consumes stored data only.
- **Forward-looking signal selection**: Only include signals where `signal_date` is within the user's backtest window.

---

## SQLite Schema Map for Phase 6

All tables are confirmed present in `utils/db.py` and `leadlag_engine/db.py`:

### Tables the Backtest Engine Reads

| Table | Key Columns | Used For |
|-------|-------------|---------|
| `signals` | `ticker_a, ticker_b, signal_date, direction, optimal_lag, correlation_strength, stability_score` | Which trades to simulate |
| `normalized_bars` | `ticker, trading_day, adj_close` | Price at signal date and lag window entry/exit |
| `returns_policy_a` | `ticker, trading_day, return_1d, return_5d, return_10d, return_20d, return_60d` | Return during lag window per signal |
| `splits` | `ticker, execution_date, fetched_at, historical_adjustment_factor` | BACKTEST-02 look-ahead bias filter |
| `features_cross_correlation` | `ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant` | UI-02 xcorr heatmap and rolling optimal |
| `regime_states` | `ticker, trading_day, regime, rs_value, price_vs_21ma, price_vs_50ma, atr_ratio` | UI-03 regime state panel |
| `distribution_events` | `ticker, trading_day, volume_ratio, vwap_rejection_streak, is_flagged` | UI-03 distribution event display |
| `ticker_pairs` | `leader, follower, is_active` | Populating pair selectors in UI |

### Key Join Pattern for Backtest Trade Simulation
```sql
-- For each signal, get the follower's return over the lag window
SELECT
    s.signal_date,
    s.direction,
    s.optimal_lag,
    r.return_1d,
    r.return_5d,
    r.return_10d
FROM signals s
JOIN returns_policy_a r
    ON r.ticker = s.ticker_b
    AND r.trading_day = date(s.signal_date, s.optimal_lag || ' days')
WHERE s.ticker_a = ? AND s.ticker_b = ?
  AND s.signal_date BETWEEN ? AND ?
```

Note: `optimal_lag` is in trading days but `date()` uses calendar days. Use `normalized_bars` to find the Nth trading day offset rather than calendar arithmetic if precision is critical.

### regime_states Schema (from leadlag_engine/db.py)
```sql
regime_states (
    ticker          TEXT NOT NULL,
    trading_day     TEXT NOT NULL,
    regime          TEXT NOT NULL,           -- 'Bull', 'Bear', 'Base', 'Failure'
    rs_value        REAL,                    -- fractional (0.05 = 5%)
    price_vs_21ma   REAL,                    -- (price/ma21 - 1), fractional
    price_vs_50ma   REAL,                    -- (price/ma50 - 1), fractional
    atr_ratio       REAL,                    -- current_atr / mean_atr_20d
    is_distribution INTEGER DEFAULT 0,
    PRIMARY KEY (ticker, trading_day)
)
```

---

## Metric Computation Reference

Confirmed patterns from `paper_trading/analytics.py` (HIGH confidence — read directly):

### Hit Rate
```python
# Proportion of trades where return in lag window matched direction
winning = sum(1 for ret in trade_returns if ret > 0)
hit_rate = winning / len(trade_returns) if trade_returns else 0.0
```

### Mean Return Per Trade
```python
mean_return = sum(trade_returns) / len(trade_returns) if trade_returns else 0.0
```

### Annualized Sharpe Ratio
```python
# Source: paper_trading/analytics.py get_risk_metrics() — verified
import math
daily_returns = pd.Series(trade_returns)
std = daily_returns.std()
mean = daily_returns.mean()
sharpe = (mean / std) * math.sqrt(252) if std != 0 else 0.0
```

### Maximum Drawdown
```python
# Source: paper_trading/analytics.py get_risk_metrics() — verified
cumulative = pd.Series(trade_returns).cumsum()
running_peak = cumulative.cummax()
drawdown = (cumulative - running_peak) / running_peak.replace(0, float("nan")) * 100
max_drawdown = float(drawdown.min()) if not drawdown.isna().all() else 0.0
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sharpe ratio | Custom formula | Pattern from `paper_trading/analytics.py` | Already proven, handles edge cases (std=0, empty) |
| Max drawdown | Custom loop | `cummax()` pattern from `paper_trading/analytics.py` | Vectorized; handles NaN correctly |
| Heatmap visualization | Third-party component | HTML table with `pnlColor()` pattern from `MonthlyHeatmap.tsx` | No new dependency; identical technique works |
| Trading day offset arithmetic | Custom calendar logic | Query `normalized_bars` for Nth subsequent trading_day | NYSE calendar already handled by data ingestion |
| Split adjustment in backtest | Re-running normalization | Use stored `adj_close` from `normalized_bars` (already adjusted) | Normalization already ran in Phase 2; stored results are ground truth |

**Key insight:** All heavy computation is already done and stored in SQLite. Phase 6 is a read+display phase — the hard work of normalization, feature computation, regime classification, and signal generation is complete.

---

## Common Pitfalls

### Pitfall 1: Calendar Day vs. Trading Day Offset
**What goes wrong:** Using `date(signal_date, optimal_lag || ' days')` to find the return window treats `optimal_lag` as calendar days, but signals use trading day lags (±1 through ±5 bars). A lag of +2 bars on a Friday means Monday+Tuesday, not the calendar date 2 days later.
**Why it happens:** SQLite `date()` function uses calendar math, not NYSE calendar.
**How to avoid:** Join `normalized_bars` ordered by `trading_day` to find the Nth trading day after `signal_date`, or use `features_lagged_returns` which already stores pre-computed lag returns. The simplest approach: query `features_lagged_returns WHERE ticker=? AND trading_day=signal_date AND lag=optimal_lag` — this is already computed by Phase 3.
**Warning signs:** Backtests producing returns that don't match expected lag windows.

### Pitfall 2: Using Future Signals as Trades
**What goes wrong:** Including all signals in the DB instead of only those with `signal_date` between the user's backtest start and end dates.
**Why it happens:** Forgetting that signals accumulate over time; newer signals are "future" relative to the backtest window.
**How to avoid:** Always filter: `WHERE signal_date >= ? AND signal_date <= ?` using the user's chosen dates.

### Pitfall 3: Plotting Recharts with Dense XCross-Correlation Time Series
**What goes wrong:** Rendering 180 days × 11 lags = 1980 data points in the heatmap as individual chart elements freezes the browser.
**Why it happens:** Recharts (and all charting libs) struggle with large dense grids as SVG elements.
**How to avoid:** Use the HTML table approach (from MonthlyHeatmap.tsx) for the cross-correlation heatmap — CSS-colored table cells are far more performant. For the rolling optimal correlation line chart, downsample to weekly or show last 90 days by default (user-configurable).

### Pitfall 4: Empty Regime State on First Load
**What goes wrong:** `regime_states` table is empty if the engine hasn't run since DB creation. The UI shows a blank panel.
**Why it happens:** `classify_regime()` only writes to `regime_states` when the pipeline runs; a fresh DB has no entries.
**How to avoid:** API endpoint for regime state must handle empty result gracefully and return a sentinel object (e.g., `{"regime": "Unknown", "rs_value": null, ...}`). React component must show "No regime data — run the pipeline first" placeholder.

### Pitfall 5: xcorr Heatmap Date Column Count
**What goes wrong:** The `features_cross_correlation` table has one row per (ticker_a, ticker_b, trading_day, lag), which can be thousands of rows. A naive SELECT returns too many columns for the heatmap.
**Why it happens:** Cross-correlation is computed rolling for every day × every lag.
**How to avoid:** The xcorr endpoint should return only recent data (default: last 90 trading days) with an optional `days` query param. Group by lag for heatmap view (lag as rows, recent dates as columns), or return the most recent cross-section only (single row per lag).

### Pitfall 6: signals Table Uses (ticker_a, ticker_b, signal_date) as PK
**What goes wrong:** Assuming `rowid` is stable for signal lookups in backtest. The signals table PK is `(ticker_a, ticker_b, signal_date)`.
**Why it happens:** The paper_trading code uses `rowid` for `source_signal_id` in trades, but backtest should use the natural key.
**How to avoid:** Always filter signals using `ticker_a=? AND ticker_b=? AND signal_date BETWEEN ? AND ?` — never rely on rowid ordering in backtest.

---

## Code Examples

### Backtest: Using features_lagged_returns to Avoid Calendar Arithmetic
```python
# Source: signals/generator.py compute_expected_target() — verified pattern
# The cleanest way to get return-at-lag in backtest is via features_lagged_returns
# which was computed by Phase 3 and already handles trading-day offsets correctly.

def _get_return_at_lag(conn, ticker_b, signal_date, optimal_lag):
    """Get the stored lag return for ticker_b at signal_date with given lag."""
    row = conn.execute(
        """
        SELECT return_value
        FROM features_lagged_returns
        WHERE ticker = ? AND trading_day = ? AND lag = ?
        """,
        (ticker_b, signal_date, optimal_lag),
    ).fetchone()
    return row[0] if row else None
```

### API: xcorr Endpoint Data Shape
```python
# Returns list of {lag: int, trading_day: str, correlation: float, is_significant: int}
# Frontend heatmap pivots this: rows=lags, columns=dates, cells=correlation
rows = conn.execute("""
    SELECT lag, trading_day, correlation, is_significant
    FROM features_cross_correlation
    WHERE ticker_a = ? AND ticker_b = ?
      AND trading_day >= date('now', ? || ' days')
      AND correlation IS NOT NULL
    ORDER BY trading_day ASC, lag ASC
""", (leader, follower, f"-{days}")).fetchall()
```

### API: Regime State Endpoint Data Shape
```python
# Returns the most recent regime_states row for ticker_b (follower)
# joined with latest distribution_events
row = conn.execute("""
    SELECT rs.regime, rs.rs_value, rs.price_vs_21ma, rs.price_vs_50ma,
           rs.atr_ratio, rs.trading_day,
           de.volume_ratio, de.vwap_rejection_streak, de.is_flagged
    FROM regime_states rs
    LEFT JOIN distribution_events de
        ON de.ticker = rs.ticker AND de.trading_day = rs.trading_day
    WHERE rs.ticker = ?
    ORDER BY rs.trading_day DESC
    LIMIT 1
""", (follower,)).fetchone()
```

### React: Pair Selector Component Pattern
```typescript
// Pairs fetched from /api/pairs, then displayed as dropdowns
// Source: PairManager.tsx fetch pattern
const [pairs, setPairs] = useState<Pair[]>([]);
useEffect(() => {
  api.pairs.list().then((d) => setPairs(d as unknown as Pair[]));
}, []);

// Render as <select> with "LEADER / FOLLOWER" option text
// User selects pair → triggers backtest or chart fetch
```

### TypeScript: New Types for Phase 6
```typescript
// Add to frontend/src/types/index.ts

export interface BacktestResult {
  leader: string;
  follower: string;
  start_date: string;
  end_date: string;
  total_trades: number;
  winning_trades: number;
  hit_rate: number;          // 0-100 percent
  mean_return_per_trade: number;  // decimal (0.02 = 2%)
  annualized_sharpe: number;
  max_drawdown: number;       // negative decimal (-0.15 = -15%)
}

export interface XcorrHeatmapPoint {
  lag: number;               // -5 to +5
  trading_day: string;
  correlation: number | null;
  is_significant: number;    // 0 or 1
}

export interface RegimeStateEntry {
  regime: string;            // "Bull" | "Bear" | "Base" | "Failure" | "Unknown"
  trading_day: string | null;
  rs_value: number | null;
  price_vs_21ma: number | null;
  price_vs_50ma: number | null;
  atr_ratio: number | null;
  volume_ratio: number | null;
  vwap_rejection_streak: number | null;
  is_flagged: number;        // 0 or 1
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Gradio UI (ui/) | React/Vite frontend + FastAPI REST | Phase 5.1 (2026-03-21) | All new UI is React pages, not Gradio tabs |
| Gradio gr.Plot with Plotly figs | Recharts components in React | Phase 5.1 | Never pass Plotly figures to frontend; return JSON data, render with Recharts |
| ui/ directory | Deleted in Plan 05.1-04 | 2026-03-21 | No Gradio code anywhere |

**Deprecated/outdated:**
- `ui/` directory: fully deleted in Plan 05.1-04. Do not reference or recreate.
- Gradio dependencies: removed from pyproject.toml in Phase 5.1.
- `gr.Plot()`, `gr.Dataframe()`, `gr.Tab()`: not available; all UI is React.

---

## Open Questions

1. **XCross-Correlation Heatmap Date Resolution**
   - What we know: `features_cross_correlation` has one row per (ticker_a, ticker_b, trading_day, lag) — potentially hundreds of dates. The heatmap (lag × date) with 180 days = 11 × 180 = 1980 cells.
   - What's unclear: Whether the planner should default to showing 30, 60, or 90 days in the heatmap for performance. The UI-02 requirement says "cross-correlation heatmap across lags" without specifying a time window.
   - Recommendation: Default to last 60 trading days with a user-selectable `days` query param. At 11 lags × 60 dates = 660 cells in an HTML table — fast to render.

2. **Backtest: Which Return Period to Use for "Return Per Trade"**
   - What we know: `returns_policy_a` has return_1d, return_5d, return_10d, return_20d, return_60d. The optimal_lag in signals ranges ±1 to ±5 days. `features_lagged_returns` has the exact pre-computed value.
   - What's unclear: Whether to use `features_lagged_returns` at the signal's `optimal_lag` offset (most statistically correct) or `returns_policy_a.return_Nd` where N matches the lag (simpler but may not match lag precisely).
   - Recommendation: Use `features_lagged_returns WHERE lag = optimal_lag` — this is what Phase 3 computed and what Phase 4 uses to generate `expected_target`. Consistent with the rest of the system.

3. **Regime State Panel: Per-Pair or Per-Ticker**
   - What we know: `regime_states` is keyed by `ticker` (the follower ticker_b) and `trading_day`. `classify_regime()` is called with (ticker_a, ticker_b) but stores data under `ticker_b`.
   - What's unclear: The UI-03 requirement says "for a selected pair" — but regime data is stored per-follower ticker. Two pairs with the same follower share regime state.
   - Recommendation: The regime endpoint accepts `leader` and `follower` params (consistent with other endpoints) but queries `regime_states WHERE ticker = follower` — follower is the instrument being assessed.

---

## Validation Architecture

> nyquist_validation is not set in .planning/config.json. Skipping this section.

---

## Sources

### Primary (HIGH confidence)
- `utils/db.py` — complete SQLite schema for all tables used in backtest (read directly)
- `leadlag_engine/db.py` — regime_states, distribution_events, signals, flow_map schemas (read directly)
- `paper_trading/analytics.py` — Sharpe ratio and max drawdown computation patterns (read directly)
- `api/routes/analytics.py` — FastAPI route pattern with Conn dependency and error handling (read directly)
- `frontend/src/lib/api.ts` — API client pattern for adding new endpoints (read directly)
- `frontend/src/types/index.ts` — TypeScript type conventions (read directly)
- `frontend/src/components/analytics/MonthlyHeatmap.tsx` — HTML table heatmap pattern (read directly)
- `frontend/src/components/analytics/EquityChart.tsx` — Recharts chart pattern (read directly)
- `frontend/package.json` — confirmed recharts 3.8.0, no Plotly in frontend (read directly)
- `pyproject.toml` — confirmed pandas, numpy, scipy installed; no new deps needed (read directly)

### Secondary (MEDIUM confidence)
- `leadlag_engine/regime.py` — confirmed what regime_states stores and how classify_regime() writes it (read directly)
- `signals/generator.py` — confirmed `features_lagged_returns` usage for expected_target (read directly; pattern reusable for backtest)
- `tests/conftest.py` — confirmed test fixture pattern (tmp_db, api_client) for Phase 6 tests (read directly)

### Tertiary (LOW confidence)
- None — all findings sourced directly from codebase files.

---

## Metadata

**Confidence breakdown:**
- SQLite schema: HIGH — read directly from db.py and leadlag_engine/db.py
- Standard stack: HIGH — pyproject.toml and package.json read directly; no new dependencies needed
- Architecture patterns: HIGH — read directly from existing analytics.py, analytics route, EquityChart, MonthlyHeatmap
- Metric computation: HIGH — Sharpe and drawdown pattern read directly from paper_trading/analytics.py
- Pitfalls: HIGH — derived from codebase reading (calendar math, dense heatmap, empty regime state)
- React/TypeScript patterns: HIGH — read directly from types/index.ts, lib/api.ts, existing pages

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (30 days — stable codebase, no fast-moving dependencies)
