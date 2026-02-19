# Phase 5: Paper Trading Simulation - Research

**Researched:** 2026-02-18
**Domain:** Python paper trading engine, SQLite P&L accounting, Polygon snapshot API, Gradio live dashboard UI
**Confidence:** HIGH (SQLite schema, Polygon API, Gradio patterns), MEDIUM (market hours library, polling integration)

---

## Summary

Phase 5 has two cleanly separable concerns: (1) a paper trading engine that manages portfolio state, auto-executes and manually records simulated trades, and computes P&L entirely in SQLite; and (2) a Gradio UI layer with two panels — a Signal Dashboard (UI-01) and a Paper Trading panel (UI-04) — that display live-ish data refreshed by `gr.Timer`.

The SQLite schema is the central design decision. Three tables are needed: `paper_portfolio` (one row per capital config), `paper_positions` (one row per open position per ticker, average-cost basis), and `paper_trades` (immutable audit log of every open/close event). The average-cost method is the correct approach here — it is simpler to implement, avoids FIFO lot tracking complexity, and is appropriate for a paper trading simulator (not a tax-reporting tool). All three tables reference a `portfolio_id` to allow future multi-portfolio support without schema changes.

Polygon's snapshot endpoint (`/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}?apiKey=KEY`) returns `lastTrade.p` as the most current price. For 15-minute polling, the correct tool is `gr.Timer(value=900, active=True)` introduced in Gradio v4.37.1 (June 2024). The timer's `tick` event triggers position refresh; the active state is conditioned on market hours. Market hours are detected using `pandas_market_calendars` v5.3.0 (January 2026) via `nyse.open_at_time(schedule, pd.Timestamp.now(tz='America/New_York'))`. SQLite thread safety for background access from the timer's server thread requires a new connection per thread (not shared connection).

**Primary recommendation:** Use average-cost basis for positions, a three-table SQLite schema with `UNIQUE` constraints to guard duplicate auto-execution, and `gr.Timer(value=900)` connected to a function that refreshes positions only when market is open. All signal auto-execution reads the signals table for `signal_date = today AND signal_id NOT IN (SELECT source_signal_id FROM paper_trades)` to enforce idempotency without a separate processed-signals table.

---

## User Constraints (from Phase Context)

No CONTEXT.md exists for this phase. The following are locked decisions from the project specification and STATE.md accumulated context:

### Locked Decisions
- v1 is a local Gradio demo — no AWS Lambda, S3, DynamoDB, or Terraform
- SQLite for all storage (raw sqlite3, no ORM)
- Module layout: `/paper_trading` and `/ui` directories
- `app.queue()` called before returning Blocks instance — required for gr.Progress to render during fetch
- SQLite is single source of truth for all state — no `gr.State()` for persistence
- `ON CONFLICT` clauses and `executemany` for bulk inserts (pattern from prior phases)
- All timestamps are UTC datetimes; NYSE trading day assignment via pandas_market_calendars
- `adjustment_policy_id = 'policy_a'` on all records that reference signal payloads
- Signals table schema (from Phase 4): `signal_id`, `ticker_a`, `ticker_b`, `signal_date`, `direction`, `optimal_lag`, `correlation_strength`, `stability_score`, `entry_condition`, `expected_target`, `invalidation_rule`, `sizing_tier`, `adjustment_policy_id`, `generated_at`
- Sizing tiers: `stability_score > 85` → full, `70 < score <= 85` → half
- Polygon snapshot endpoint used for current prices (15-min delayed)
- `structlog` for logging via `utils/logging.py` `get_logger()`
- `python-dotenv` + `load_dotenv()` at top of main.py before imports

### Deferred Ideas (OUT OF SCOPE)
- Real broker integration (Alpaca, TD Ameritrade, etc.)
- Automated stop-loss execution (flagged only; human makes exit decision)
- AWS deployment (v2)
- Intraday 5-minute bars

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | stdlib | Portfolio, position, trade storage | Locked decision — raw sqlite3, no ORM |
| gradio | 4.37.1+ | UI panels with `gr.Timer` for polling | `gr.Timer` introduced in v4.37.1 (June 2024); required for TRADE-05 polling |
| pandas_market_calendars | 5.3.0 | NYSE market hours detection | `open_at_time()` method for "is market open now" check; v5.3.0 released Jan 2026 uses `zoneinfo`, drops pytz |
| requests | >=2.31 (locked) | Polygon snapshot API calls | Already in stack from Phase 1; used for all Polygon HTTP calls |
| pandas | 2.2+ (locked) | DataFrame for Gradio dataframes, P&L aggregation | Already in stack; `gr.Dataframe` accepts `pd.DataFrame` directly |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| APScheduler | 3.x | Background price polling (alternative to gr.Timer approach) | Use if timer-driven approach proves insufficient; BackgroundScheduler runs independently of Gradio events |
| zoneinfo | stdlib (Python 3.9+) | ET timezone for market hours | Use `ZoneInfo('America/New_York')` when not using pandas_market_calendars |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Average-cost basis | FIFO lot tracking | FIFO requires tracking individual lots with separate buy timestamps; adds schema complexity (lot table); unnecessary for a paper trading simulator (not a tax tool). Average-cost is simpler, Alpaca uses it for intraday positions. |
| `gr.Timer(900)` + `tick` | APScheduler BackgroundScheduler | gr.Timer triggers refresh per connected client (correct for Gradio); APScheduler runs server-side regardless of UI connection. For a single-user local app, either works; `gr.Timer` is cleaner because it stops polling when UI tab is closed. |
| `pandas_market_calendars` | pytz + manual NYSE holiday list | pandas_market_calendars maintains accurate NYSE holiday/early-close calendar; manual list requires yearly maintenance and misses early closes. |

**Installation:**
```bash
uv add pandas-market-calendars ">=5.3"
# gradio, requests, pandas, sqlite3 already in pyproject.toml from prior phases
```

---

## Architecture Patterns

### Recommended Project Structure
```
paper_trading/
├── __init__.py              # Exports PaperTradingEngine class
├── engine.py                # Core engine: open_position(), close_position(), auto_execute()
├── portfolio.py             # Portfolio setup (TRADE-01): set_capital(), get_portfolio_summary()
├── price_poller.py          # Polygon snapshot fetch + market hours guard (TRADE-05)
├── pnl.py                   # P&L calculation: unrealized (TRADE-04), realized (TRADE-06)
├── db.py                    # SQLite schema creation + all DB helpers
├── models.py                # Dataclasses: Portfolio, Position, Trade

ui/
├── __init__.py
├── signal_dashboard.py      # UI-01: Signal Dashboard panel (auto-execute toggle, active signals)
├── paper_trading_panel.py   # UI-04: Paper Trading panel (positions, manual entry, trade history)
├── app.py                   # Assembles all panels into gr.Blocks, calls app.queue()
```

### Pattern 1: SQLite Schema — Three Tables

**What:** Minimal schema that satisfies all TRADE requirements without over-engineering.

**Rationale for design choices:**
- `paper_portfolio` is a single-row settings table (one portfolio in v1); `portfolio_id` future-proofs for multi-portfolio
- `paper_positions` tracks net open position per ticker with average cost; closing subtracts shares and triggers a trade record
- `paper_trades` is an append-only audit log; the `UNIQUE(portfolio_id, signal_id, side)` constraint on the auto-execution side prevents duplicate signal execution

```sql
-- Source: designed for this project's requirements

CREATE TABLE IF NOT EXISTS paper_portfolio (
    portfolio_id     INTEGER PRIMARY KEY DEFAULT 1,
    starting_capital REAL    NOT NULL,
    cash_balance     REAL    NOT NULL,
    created_at       TEXT    NOT NULL,   -- UTC ISO datetime
    updated_at       TEXT    NOT NULL    -- UTC ISO datetime
);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id     INTEGER NOT NULL DEFAULT 1,
    ticker           TEXT    NOT NULL,
    shares           REAL    NOT NULL,   -- positive = long, negative = short (future)
    avg_cost         REAL    NOT NULL,   -- weighted average cost per share
    current_price    REAL,               -- last refreshed price (NULL until first poll)
    last_price_at    TEXT,               -- UTC ISO datetime of last price refresh
    source_signal_id INTEGER,            -- FK to signals.rowid if auto-executed (NULL if manual)
    invalidation_threshold REAL,         -- copied from signal; NULL if manual trade
    opened_at        TEXT    NOT NULL,   -- UTC ISO datetime
    UNIQUE(portfolio_id, ticker)         -- one position row per ticker per portfolio
);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id     INTEGER NOT NULL DEFAULT 1,
    ticker           TEXT    NOT NULL,
    side             TEXT    NOT NULL CHECK(side IN ('buy', 'sell')),
    shares           REAL    NOT NULL,
    price            REAL    NOT NULL,   -- execution price (snapshot lastTrade.p or manual entry)
    realized_pnl     REAL,               -- NULL for opens; computed on close (TRADE-06)
    source_signal_id INTEGER,            -- FK to signals.rowid; NULL if manual
    executed_at      TEXT    NOT NULL,   -- UTC ISO datetime (TRADE-08)
    notes            TEXT                -- "auto_execute" | "manual" | "signal_invalidated"
);

-- Idempotency guard: prevent duplicate auto-execution of same signal as buy
CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_signal_buy
    ON paper_trades(source_signal_id)
    WHERE source_signal_id IS NOT NULL AND side = 'buy';

CREATE INDEX IF NOT EXISTS idx_positions_ticker ON paper_positions(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON paper_trades(executed_at);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON paper_trades(ticker);
```

### Pattern 2: Auto-Execution (TRADE-02)

**What:** Read unprocessed signals from the `signals` table and open positions for qualifying signals. "Unprocessed" means no existing `buy` trade record references that `signal_id`.

**Trigger:** Called by a button in the Signal Dashboard UI when auto-execute toggle is ON, or on a daily timer.

**Sizing tier to share quantity:** The `sizing_tier` field ('full'/'half') maps to a fraction of available cash. There is no defined "base" in the requirements — implement as a fraction of total portfolio capital:
- `full` → use up to 20% of starting capital per position (conservative single-position sizing)
- `half` → use up to 10% of starting capital per position
- The exact fractions are Claude's discretion; keep them configurable as constants in `paper_trading/engine.py`

```python
# Source: designed for this project
SIZING_FRACTIONS = {
    'full': 0.20,   # 20% of starting capital
    'half': 0.10,   # 10% of starting capital
    'quarter': 0.05,  # 5% (not currently emitted by engine, but defined for completeness)
}

def compute_share_quantity(
    starting_capital: float,
    cash_balance: float,
    sizing_tier: str,
    entry_price: float,
) -> int:
    """
    Returns integer share count. Returns 0 if insufficient cash.
    Uses floor division — never allocate more cash than available.
    """
    max_position_value = starting_capital * SIZING_FRACTIONS.get(sizing_tier, 0.10)
    affordable_value = min(max_position_value, cash_balance)
    if affordable_value <= 0 or entry_price <= 0:
        return 0
    return int(affordable_value // entry_price)
```

**Auto-execute query — idempotency via SQL NOT EXISTS:**
```python
# Source: designed for this project; uses SQLite NOT EXISTS idiom
def get_unprocessed_signals(conn: sqlite3.Connection) -> list[dict]:
    """
    Returns signals that have not yet been auto-executed (no buy trade exists for signal).
    """
    sql = """
        SELECT rowid AS signal_id, ticker_a, ticker_b, signal_date,
               direction, sizing_tier, invalidation_threshold, expected_target
        FROM signals
        WHERE signal_date >= date('now', '-7 days')   -- only recent signals
          AND NOT EXISTS (
              SELECT 1 FROM paper_trades
              WHERE paper_trades.source_signal_id = signals.rowid
                AND paper_trades.side = 'buy'
          )
        ORDER BY generated_at DESC
    """
    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]
```

### Pattern 3: Average-Cost Position Tracking

**What:** When adding shares to an existing position, update the average cost. When closing (partial or full), compute realized P&L against average cost.

**Formula (verified against Alpaca's documented approach):**
- Open / add to position: `new_avg_cost = (existing_shares * existing_avg_cost + new_shares * price) / (existing_shares + new_shares)`
- Close / reduce position: `realized_pnl = closed_shares * (close_price - avg_cost)`

```python
# Source: Alpaca position average entry price docs (https://docs.alpaca.markets/docs/position-average-entry-price-calculation)

def open_or_add_position(
    conn: sqlite3.Connection,
    portfolio_id: int,
    ticker: str,
    shares: int,
    price: float,
    source_signal_id: int | None,
    invalidation_threshold: float | None,
    executed_at: str,
) -> None:
    """
    Opens new position or adds to existing via average-cost update.
    Records a 'buy' trade in paper_trades.
    Deducts cash from paper_portfolio.
    """
    trade_value = shares * price

    # 1. Record trade
    conn.execute("""
        INSERT INTO paper_trades
            (portfolio_id, ticker, side, shares, price, realized_pnl,
             source_signal_id, executed_at, notes)
        VALUES (?, ?, 'buy', ?, ?, NULL, ?, ?, ?)
    """, (portfolio_id, ticker, shares, price, source_signal_id, executed_at,
          'auto_execute' if source_signal_id else 'manual'))

    # 2. Upsert position with average-cost update
    conn.execute("""
        INSERT INTO paper_positions
            (portfolio_id, ticker, shares, avg_cost, source_signal_id,
             invalidation_threshold, opened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(portfolio_id, ticker) DO UPDATE SET
            avg_cost = (shares * avg_cost + excluded.shares * excluded.avg_cost)
                       / (shares + excluded.shares),
            shares   = shares + excluded.shares
    """, (portfolio_id, ticker, shares, price, source_signal_id,
          invalidation_threshold, executed_at))

    # 3. Deduct cash
    conn.execute("""
        UPDATE paper_portfolio
        SET cash_balance = cash_balance - ?,
            updated_at = ?
        WHERE portfolio_id = ?
    """, (trade_value, executed_at, portfolio_id))

    conn.commit()


def close_position(
    conn: sqlite3.Connection,
    portfolio_id: int,
    ticker: str,
    shares_to_close: int,
    close_price: float,
    executed_at: str,
    notes: str = 'manual',
) -> float:
    """
    Partially or fully closes a position.
    Records a 'sell' trade with realized_pnl.
    Returns realized_pnl for this close.
    Raises ValueError if shares_to_close > shares held.
    """
    row = conn.execute("""
        SELECT shares, avg_cost FROM paper_positions
        WHERE portfolio_id = ? AND ticker = ?
    """, (portfolio_id, ticker)).fetchone()

    if row is None:
        raise ValueError(f"No open position for {ticker}")
    held_shares, avg_cost = row['shares'], row['avg_cost']

    if shares_to_close > held_shares:
        raise ValueError(
            f"Cannot close {shares_to_close} shares of {ticker}; only {held_shares} held"
        )

    realized_pnl = shares_to_close * (close_price - avg_cost)
    trade_value = shares_to_close * close_price

    # Record sell trade
    conn.execute("""
        INSERT INTO paper_trades
            (portfolio_id, ticker, side, shares, price, realized_pnl,
             source_signal_id, executed_at, notes)
        VALUES (?, ?, 'sell', ?, ?, ?, NULL, ?, ?)
    """, (portfolio_id, ticker, shares_to_close, close_price, realized_pnl,
          executed_at, notes))

    remaining = held_shares - shares_to_close
    if remaining == 0:
        # Full close — remove position row
        conn.execute("""
            DELETE FROM paper_positions WHERE portfolio_id = ? AND ticker = ?
        """, (portfolio_id, ticker))
    else:
        # Partial close — shares reduce, avg_cost stays the same
        conn.execute("""
            UPDATE paper_positions SET shares = ? WHERE portfolio_id = ? AND ticker = ?
        """, (remaining, portfolio_id, ticker))

    # Return cash
    conn.execute("""
        UPDATE paper_portfolio
        SET cash_balance = cash_balance + ?, updated_at = ?
        WHERE portfolio_id = ?
    """, (trade_value, executed_at, portfolio_id))

    conn.commit()
    return realized_pnl
```

### Pattern 4: Polygon Snapshot Endpoint (TRADE-05)

**What:** Fetch current (15-min delayed) price for one or more tickers via Polygon REST API.

**Endpoint:**
```
GET https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}?apiKey={KEY}
```

**Response structure (verified from polygon.readthedocs.io and multiple WebSearch sources):**
```json
{
  "status": "OK",
  "ticker": {
    "ticker": "AAPL",
    "todaysChangePerc": 1.23,
    "todaysChange": 2.00,
    "updated": 1637354400000000000,
    "day": {
      "o": 165.00, "h": 168.00, "l": 164.00, "c": 167.50,
      "v": 54321000, "vw": 166.25
    },
    "min": {
      "o": 167.00, "h": 167.75, "l": 166.90, "c": 167.50,
      "v": 123456, "vw": 167.25, "t": 1637354400000
    },
    "prevDay": {
      "o": 163.00, "h": 165.50, "l": 162.00, "c": 165.50,
      "v": 49876000, "vw": 163.75
    },
    "lastTrade": {
      "p": 167.50,      # price — USE THIS for current price
      "s": 100,         # size (shares)
      "t": 1637354390000000000,  # timestamp nanoseconds
      "x": 4,           # exchange ID
      "c": [14, 41]     # condition codes
    },
    "lastQuote": {
      "P": 167.51, "S": 2, "p": 167.50, "s": 1
    }
  }
}
```

**Which field to use for current price:** Use `ticker.lastTrade.p` — this is the price of the most recent trade. For the 15-min delayed use case (basic Polygon plan), this reflects the last actual trade reported by exchanges. `min.c` (current minute bar close) is an alternative if `lastTrade` is stale, but `lastTrade.p` is always the most recent trade price.

**Fallback chain (if `lastTrade.p` is absent):** `min.c` → `day.c` → `prevDay.c`. Implement this in the price extraction helper.

```python
# Source: polygon.readthedocs.io, verified field names from multiple sources
import requests

def fetch_snapshot_price(ticker: str, api_key: str) -> float | None:
    """
    Returns the most recent trade price for ticker, or None on failure.
    Uses fallback chain: lastTrade.p → min.c → day.c → prevDay.c
    """
    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
    try:
        resp = requests.get(url, params={"apiKey": api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        tick = data.get("ticker", {})

        # Fallback chain
        price = (
            (tick.get("lastTrade") or {}).get("p")
            or (tick.get("min") or {}).get("c")
            or (tick.get("day") or {}).get("c")
            or (tick.get("prevDay") or {}).get("c")
        )
        return float(price) if price is not None else None
    except Exception:
        return None  # Caller decides how to handle missing price
```

### Pattern 5: Market Hours Detection (TRADE-05)

**What:** Guard the price polling so it only runs during NYSE market hours (9:30–16:00 ET), Monday–Friday, on trading days.

**Use `pandas_market_calendars`** for holiday awareness. Version 5.3.0 (Jan 2026) uses `zoneinfo` and has dropped pytz as of v5.0.

```python
# Source: pandas_market_calendars docs (pandas-market-calendars.readthedocs.io)
import pandas as pd
import pandas_market_calendars as mcal

# Create NYSE calendar once as module-level singleton (follows project pattern from Phase 2)
_NYSE = mcal.get_calendar('NYSE')

def is_market_open() -> bool:
    """
    Returns True if NYSE is currently in regular trading hours (9:30-16:00 ET).
    Accounts for holidays and early closes.
    """
    now_et = pd.Timestamp.now(tz='America/New_York')
    today_str = now_et.strftime('%Y-%m-%d')

    try:
        schedule = _NYSE.schedule(start_date=today_str, end_date=today_str)
        if schedule.empty:
            return False  # Today is a holiday or weekend
        return _NYSE.open_at_time(schedule, now_et)
    except Exception:
        return False  # Fail closed — don't poll if calendar check fails
```

**Alternative without pandas_market_calendars** (simpler, no holiday awareness — acceptable for v1):
```python
# LOW confidence approach — misses holidays and early closes
from datetime import datetime, time
import zoneinfo

def is_market_open_simple() -> bool:
    now_et = datetime.now(tz=zoneinfo.ZoneInfo('America/New_York'))
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = time(9, 30)
    market_close = time(16, 0)
    return market_open <= now_et.time() < market_close
```

### Pattern 6: gr.Timer for 15-Minute Price Polling (TRADE-04, TRADE-05)

**What:** Use `gr.Timer` (introduced Gradio v4.37.1, June 2024) to trigger price refresh every 15 minutes. The timer's `active` state is conditioned on market hours.

**Key facts verified:**
- `gr.Timer(value=900, active=True)` — 900 seconds = 15 minutes
- `timer.tick(fn, outputs=[...])` — fires the function every tick
- `gr.Dataframe(value=fn, every=gr.Timer(900))` — component pulls fresh data on each timer tick
- `every=` parameter on components will be deprecated in favor of `gr.Timer` — use `gr.Timer` directly
- `demo.queue()` is required for timer-driven updates (already a locked project pattern)

```python
# Source: Gradio docs (gradio.app/docs/gradio/timer), PR #8505 merged June 28 2024
import gradio as gr

def refresh_positions_table():
    """Returns pd.DataFrame of current open positions with current price + unrealized P&L."""
    conn = sqlite3.connect(DB_PATH)  # New connection per call (thread safety)
    try:
        return get_open_positions_dataframe(conn)
    finally:
        conn.close()

def check_market_and_poll():
    """Called by timer tick. Refreshes prices only during market hours."""
    if not is_market_open():
        return gr.update()  # No-op during off-hours
    # Fetch prices and update positions
    poll_and_update_prices()
    return refresh_positions_table()

with gr.Blocks() as demo:
    # Approach A: Timer drives a refresh function
    price_timer = gr.Timer(value=900, active=True)
    positions_table = gr.Dataframe(
        value=refresh_positions_table,
        every=gr.Timer(900),
        headers=["Ticker", "Shares", "Avg Cost", "Current Price", "Unrealized P&L", "Exit Flag"],
        label="Open Positions"
    )

    # Approach B: Timer tick writes to DB; component re-fetches
    price_timer.tick(fn=check_market_and_poll, outputs=[positions_table])

demo.queue().launch()  # queue() is required — locked pattern
```

**Important: use Approach A** (pass function + every= to Dataframe) for the positions table — it is simpler and the Gradio docs show this as the canonical real-time dashboard pattern. Approach B is for cases where the tick function needs to update multiple components.

### Pattern 7: SQLite Thread Safety for Background Polling

**What:** The gr.Timer tick handler runs in a Gradio server thread, not the main thread. Creating a shared SQLite connection in the main thread and using it from the timer thread causes `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.

**Correct approach:** Create a new connection per function call. This is the Python `sqlite3` documented best practice.

```python
# Source: Python 3 docs (docs.python.org/3/library/sqlite3.html)
# Each thread creates its own connection — no shared connection, no check_same_thread=False

DB_PATH = "leadlag.db"  # module-level constant

def get_open_positions_dataframe() -> pd.DataFrame:
    """
    Safe to call from any thread — creates its own connection.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT ticker, shares, avg_cost, current_price,
                   ROUND((current_price - avg_cost) * shares, 2) AS unrealized_pnl,
                   invalidation_threshold
            FROM paper_positions
            WHERE portfolio_id = 1
            ORDER BY opened_at
        """).fetchall()
        return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
    finally:
        conn.close()
```

### Pattern 8: Signal Dashboard Panel (UI-01)

**What:** Displays active signals from the `signals` table with full position spec. Includes auto-execute toggle.

```python
# Source: Gradio Blocks layout pattern from official docs
import gradio as gr

def build_signal_dashboard_panel():
    with gr.Tab("Signal Dashboard"):
        with gr.Row():
            gr.Markdown("## Active Signals")
            auto_execute_toggle = gr.Checkbox(
                label="Auto-Execute New Signals",
                value=False,
                info="When enabled, qualifying signals automatically open paper positions"
            )

        signals_table = gr.Dataframe(
            value=get_active_signals_dataframe,
            every=gr.Timer(60),   # Refresh signal list every 60 seconds
            headers=[
                "Signal Date", "Leader", "Follower", "Direction",
                "Sizing Tier", "Stability", "Correlation",
                "Entry Condition", "Target", "Invalidation",
                "Auto-Executed"
            ],
            label="Active Signals (last 7 days)",
            interactive=False,
        )

        with gr.Row():
            execute_selected_btn = gr.Button("Execute Selected Signal", variant="primary")
            refresh_btn = gr.Button("Refresh Signals")

        status_msg = gr.Textbox(label="Status", interactive=False)

    return auto_execute_toggle, signals_table, execute_selected_btn, status_msg
```

### Pattern 9: Paper Trading Panel (UI-04)

**What:** Open positions table, portfolio summary, manual Buy/Sell form, closed trade history.

```python
import gradio as gr

def build_paper_trading_panel():
    with gr.Tab("Paper Trading"):
        # Portfolio summary row
        with gr.Row():
            starting_capital_input = gr.Number(
                label="Starting Capital ($)",
                value=100000,
                minimum=1000,
                step=1000,
            )
            set_capital_btn = gr.Button("Set Capital", variant="secondary")

        with gr.Row():
            cash_balance_display = gr.Number(label="Cash Balance", interactive=False)
            total_pnl_display = gr.Number(label="Total P&L", interactive=False)
            win_rate_display = gr.Number(label="Win Rate (%)", interactive=False)

        # Open positions (live refresh)
        positions_table = gr.Dataframe(
            value=get_open_positions_dataframe,
            every=gr.Timer(900),  # 15-minute refresh (TRADE-05)
            headers=["Ticker", "Shares", "Avg Cost", "Current Price",
                     "Unrealized P&L", "Exit Flag"],
            label="Open Positions",
            interactive=False,
        )

        # Manual trade entry (TRADE-03)
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Manual Trade Entry")
                ticker_input = gr.Textbox(
                    label="Ticker",
                    placeholder="e.g. AAPL",
                    max_lines=1,
                )
                shares_input = gr.Number(
                    label="Shares",
                    minimum=1,
                    step=1,
                    precision=0,
                )
                with gr.Row():
                    buy_btn = gr.Button("Buy", variant="primary")
                    sell_btn = gr.Button("Sell", variant="stop")
                trade_status = gr.Textbox(label="Trade Status", interactive=False)

        # Closed trade history (TRADE-08)
        trade_history_table = gr.Dataframe(
            value=get_trade_history_dataframe,
            every=gr.Timer(60),
            headers=["Executed At", "Ticker", "Side", "Shares",
                     "Price", "Realized P&L", "Notes"],
            label="Trade History",
            interactive=False,
        )
```

### Anti-Patterns to Avoid

- **Storing current_price in `gr.State()`**: Locked decision — SQLite is the single source of truth. Current price must live in `paper_positions.current_price`. The timer tick updates the DB; the Dataframe reads from DB.
- **Using a shared SQLite connection across threads**: The price poller runs in a timer-driven server thread. Always create a new connection per function call. Do NOT set `check_same_thread=False` on a shared connection — this is error-prone.
- **Updating unrealized P&L without refreshing `current_price` first**: The unrealized P&L is computed as `(current_price - avg_cost) * shares`. If `current_price` is NULL or stale, display "N/A" rather than 0.
- **Closing more shares than held**: The `close_position()` function must validate `shares_to_close <= held_shares` before any DB writes. Raise `ValueError` with a clear message; catch in the UI and show to user.
- **Auto-executing the same signal twice**: Rely on the `UNIQUE INDEX ON paper_trades(source_signal_id) WHERE side = 'buy'` constraint plus the NOT EXISTS query guard. Never maintain a separate "processed signals" set in Python — the DB constraint is the authoritative lock.
- **Polling prices outside market hours**: Always call `is_market_open()` at the top of the price refresh function. If market is closed, return without making any Polygon API calls.
- **Using `gr.Dataframe(interactive=True)` for live-updating tables**: Interactive mode allows user edits, which conflicts with programmatic updates. Set `interactive=False` on all live-updating tables.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NYSE market hours + holiday detection | Hardcoded holiday list + weekday check | `pandas_market_calendars` with `open_at_time()` | NYSE has ~9 holidays/year plus occasional early closes; manual list requires yearly maintenance |
| Periodic UI refresh | Thread + `time.sleep()` loop writing to shared state | `gr.Timer(value=900).tick(fn, outputs=[...])` | gr.Timer is Gradio-native, participates in the event queue, stops when client disconnects |
| Average-cost position update | Custom Python merge logic on dict | SQL `ON CONFLICT(portfolio_id, ticker) DO UPDATE SET avg_cost = weighted_formula` | DB-side computation avoids race conditions; single atomic operation |
| Price extraction from Polygon response | Custom JSON path parser | Simple `.get()` fallback chain | Response structure has nested optionals; fallback chain is 5 lines |
| Duplicate signal execution guard | Python set tracking processed IDs | `UNIQUE INDEX ON paper_trades(source_signal_id) WHERE side = 'buy'` | DB constraint is atomic and survives restarts; Python set is lost on restart |

**Key insight:** The trading engine's correctness depends on the database being the single source of truth and all mutations being atomic SQL transactions. Never maintain accounting state in Python variables — they are not durable.

---

## Common Pitfalls

### Pitfall 1: Zero Capital / Insufficient Cash Guard

**What goes wrong:** Auto-execution or manual buy attempts to open a position when `cash_balance < price * 1` (can't buy even one share). The `compute_share_quantity()` function returns 0 shares, but the caller still calls `open_or_add_position()` with 0 shares, inserting a zero-share trade record.

**Why it happens:** Developer doesn't check the return value of `compute_share_quantity()` before proceeding.

**How to avoid:** In `engine.auto_execute()` and the manual Buy handler, always check `if shares == 0: return "Insufficient cash"` before calling `open_or_add_position()`. Never insert a zero-share trade.

**Warning signs:** `paper_trades` table has rows with `shares = 0`; portfolio summary shows unexpected values.

### Pitfall 2: Snapshot Data Cleared at 3:30 AM ET

**What goes wrong:** Polygon clears snapshot data at 3:30 AM ET each day. Polling at app startup (which may happen before 4 AM ET when Polygon begins re-populating) returns `null` or stale prev-day data. The fallback chain hits `prevDay.c` and shows yesterday's close as "current price."

**Why it happens:** Polygon's own documentation notes: "Snapshot data is cleared at 3:30am EST and gets populated as data is received from the exchanges, which can happen as early as 4am EST."

**How to avoid:** The `is_market_open()` check using `pandas_market_calendars` already handles this — market opens at 9:30 AM, so polling only begins then. Pre-market data is not relevant for 15-min delayed prices. If users want pre-market display, document that `prevDay.c` is shown until market open.

**Warning signs:** Positions show yesterday's close as current price during pre-market hours.

### Pitfall 3: `gr.Dataframe` Stale on Row Update

**What goes wrong:** Known Gradio bug (tracked in issue #8160 and #10333): when a Dataframe's underlying data updates an existing row's value (not adding/removing rows), the table may not visually refresh without a full page reload in some Gradio versions between 4.16 and 4.43.

**Why it happens:** Gradio's Dataframe diff algorithm doesn't always detect cell-level changes when the row structure is identical.

**How to avoid:** Add a hidden timestamp column to the DataFrame so the row structure always changes when prices update (the timestamp column changes even if price is unchanged). Alternatively, ensure you are on Gradio >= 4.44 where this is documented as fixed.

**Warning signs:** UI shows stale prices despite successful DB updates; `current_price` in DB is fresh but table shows old value.

### Pitfall 4: Integer vs Float Share Quantities

**What goes wrong:** `int(affordable_value // entry_price)` performs floor division correctly, but elsewhere in the code `shares` may be stored as a float (e.g., `REAL` in SQLite). When comparing `shares_to_close > held_shares`, float precision causes off-by-epsilon errors that pass validation but produce unexpected fractional share records.

**Why it happens:** SQLite `REAL` type allows fractional values; Python's `//` always returns an integer, but if the value is ever converted through a `pd.DataFrame` retrieval, it becomes float64.

**How to avoid:** Enforce integer shares at the engine level. In `close_position()`, cast: `held_shares = int(row['shares'])`. All share quantities flowing through the UI should use `gr.Number(precision=0)` and be cast to `int` before calling engine methods.

**Warning signs:** Fractional share counts in position table (e.g., `shares = 99.99999` instead of `100`).

### Pitfall 5: Missing Exit Flag for Invalidated Positions (TRADE-07)

**What goes wrong:** The invalidation threshold from the signal is stored in `paper_positions.invalidation_threshold`, but the UI flag check is forgotten during position display. Positions are shown without the exit flag even when the leader has reversed beyond the threshold.

**Why it happens:** The invalidation check requires accessing the leader's current return (from the `returns_policy_a` table in Phase 2) and comparing against `invalidation_threshold`. This cross-module query is easy to overlook.

**How to avoid:** In `get_open_positions_dataframe()`, after fetching positions, perform a second query against `returns_policy_a` for the leader ticker's most recent 1d return for each position that has a non-NULL `source_signal_id`. Compare against `invalidation_threshold`. Add a boolean `exit_flag` column to the DataFrame.

**Warning signs:** Positions linked to signals never show exit flags despite obvious leader reversals.

### Pitfall 6: SQLite Row Factory Not Set

**What goes wrong:** Querying positions without `conn.row_factory = sqlite3.Row` returns plain tuples. When the DataFrame-building code does `row['ticker']` on a tuple, it raises `TypeError: tuple indices must be integers or slices, not str`.

**Why it happens:** Each new connection (per the thread-safety pattern) must re-set `row_factory`. If a helper function creates a connection and forgets `row_factory`, dict-style access fails.

**How to avoid:** Create a `get_connection()` helper in `paper_trading/db.py` that always sets `conn.row_factory = sqlite3.Row` before returning the connection.

**Warning signs:** `TypeError: tuple indices must be integers or slices, not str` during dataframe population.

---

## Code Examples

### Complete P&L Computation Query
```python
# Source: designed for this project — SQLite computed columns pattern
def get_portfolio_summary(conn: sqlite3.Connection) -> dict:
    """Returns cash, unrealized P&L, realized P&L, win rate, total P&L."""
    cash = conn.execute(
        "SELECT cash_balance, starting_capital FROM paper_portfolio WHERE portfolio_id = 1"
    ).fetchone()

    unrealized = conn.execute("""
        SELECT COALESCE(SUM((current_price - avg_cost) * shares), 0)
        FROM paper_positions
        WHERE portfolio_id = 1 AND current_price IS NOT NULL
    """).fetchone()[0]

    realized_stats = conn.execute("""
        SELECT
            COALESCE(SUM(realized_pnl), 0)          AS total_realized,
            COUNT(*) FILTER (WHERE realized_pnl > 0) AS wins,
            COUNT(*) FILTER (WHERE realized_pnl IS NOT NULL) AS total_closed
        FROM paper_trades
        WHERE portfolio_id = 1 AND side = 'sell'
    """).fetchone()

    win_rate = (
        round(realized_stats['wins'] / realized_stats['total_closed'] * 100, 1)
        if realized_stats['total_closed'] > 0 else 0.0
    )
    return {
        'cash_balance': cash['cash_balance'],
        'starting_capital': cash['starting_capital'],
        'unrealized_pnl': unrealized,
        'realized_pnl': realized_stats['total_realized'],
        'total_pnl': unrealized + realized_stats['total_realized'],
        'win_rate': win_rate,
    }
```

### Batch Price Update (after snapshot poll)
```python
# Source: sqlite3 stdlib executemany pattern (locked convention from prior phases)
def update_position_prices(
    conn: sqlite3.Connection,
    prices: dict[str, float],  # {ticker: price}
    refreshed_at: str,         # UTC ISO datetime
) -> None:
    """Bulk update current_price on all open positions."""
    rows = [
        (price, refreshed_at, ticker)
        for ticker, price in prices.items()
        if price is not None
    ]
    conn.executemany("""
        UPDATE paper_positions
        SET current_price = ?, last_price_at = ?
        WHERE ticker = ? AND portfolio_id = 1
    """, rows)
    conn.commit()
```

### gr.Timer with Market Hours Guard
```python
# Source: Gradio docs (gradio.app/docs/gradio/timer) + pandas_market_calendars docs
import gradio as gr
import pandas_market_calendars as mcal
import pandas as pd

_NYSE = mcal.get_calendar('NYSE')

def refresh_if_market_open():
    """
    Timer tick handler: polls prices only during market hours.
    Returns updated positions DataFrame.
    """
    now = pd.Timestamp.now(tz='America/New_York')
    today = now.strftime('%Y-%m-%d')
    try:
        schedule = _NYSE.schedule(start_date=today, end_date=today)
        market_open = not schedule.empty and _NYSE.open_at_time(schedule, now)
    except Exception:
        market_open = False

    if market_open:
        poll_and_update_prices()  # Calls Polygon snapshot, writes to DB

    return get_open_positions_dataframe()  # Always return fresh data from DB

with gr.Blocks() as demo:
    positions = gr.Dataframe(
        value=get_open_positions_dataframe,
        every=gr.Timer(900),
        interactive=False,
        label="Open Positions (15-min delayed prices)"
    )
    # OR explicitly connect timer:
    t = gr.Timer(value=900, active=True)
    t.tick(fn=refresh_if_market_open, outputs=[positions])

demo.queue().launch()
```

### Schema Initialization (add to existing `init_schema()`)
```python
# Source: designed for this project; follows sqlite3 pattern from prior phases
def init_paper_trading_schema(conn: sqlite3.Connection) -> None:
    """Called from existing init_schema() — adds paper trading tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_portfolio (
            portfolio_id     INTEGER PRIMARY KEY DEFAULT 1,
            starting_capital REAL    NOT NULL,
            cash_balance     REAL    NOT NULL,
            created_at       TEXT    NOT NULL,
            updated_at       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_positions (
            position_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id     INTEGER NOT NULL DEFAULT 1,
            ticker           TEXT    NOT NULL,
            shares           REAL    NOT NULL,
            avg_cost         REAL    NOT NULL,
            current_price    REAL,
            last_price_at    TEXT,
            source_signal_id INTEGER,
            invalidation_threshold REAL,
            opened_at        TEXT    NOT NULL,
            UNIQUE(portfolio_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            trade_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id     INTEGER NOT NULL DEFAULT 1,
            ticker           TEXT    NOT NULL,
            side             TEXT    NOT NULL CHECK(side IN ('buy', 'sell')),
            shares           REAL    NOT NULL,
            price            REAL    NOT NULL,
            realized_pnl     REAL,
            source_signal_id INTEGER,
            executed_at      TEXT    NOT NULL,
            notes            TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_signal_buy
            ON paper_trades(source_signal_id)
            WHERE source_signal_id IS NOT NULL AND side = 'buy';

        CREATE INDEX IF NOT EXISTS idx_positions_ticker ON paper_positions(ticker);
        CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON paper_trades(executed_at);
        CREATE INDEX IF NOT EXISTS idx_trades_ticker ON paper_trades(ticker);
    """)
    conn.commit()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `every=5` parameter on gr.Component | `every=gr.Timer(5)` | Gradio v4.37.1 (June 2024) | `every=float` deprecated in favor of `gr.Timer` object; same behavior, better control |
| pytz for timezone | `zoneinfo` (stdlib) | Python 3.9+ / pandas_market_calendars v5.0 | pandas_market_calendars v5.0 dropped pytz; use `zoneinfo.ZoneInfo('America/New_York')` or `pd.Timestamp.now(tz='America/New_York')` |
| Thread-based periodic polling | `gr.Timer` with `.tick()` | Gradio v4.37.1 | No manual threading needed; Gradio manages the execution scheduling |
| Shared SQLite connection | Per-thread connection creation | Python 3 sqlite3 docs best practice (always) | Eliminates `ProgrammingError: SQLite objects created in a thread can only be used in that same thread` |

**Deprecated/outdated for this project:**
- `pytz`: pandas_market_calendars 5.0+ uses zoneinfo; do not introduce pytz as a new dependency
- `every=float` parameter: deprecated in favor of `gr.Timer` — use `gr.Timer` from the start since we are on Gradio 4.37.1+
- APScheduler for UI-driven polling: unnecessary when `gr.Timer` exists; only use APScheduler if a background job needs to run independently of the Gradio UI connection

---

## Open Questions

1. **What is the concrete "base" for sizing tier share quantity (TRADE-02)?**
   - What we know: Sizing tiers are 'full' and 'half'; the requirements say "sizing position per the signal's sizing tier" but do not define the actual dollar amount
   - What's unclear: Does "full" mean 100% of available cash? 20% per position? Configurable by user?
   - Recommendation: Use 20% of starting capital for 'full' and 10% for 'half' as a conservative default. Expose these as configurable constants in `paper_trading/engine.py`. The capital fraction approach is industry-standard for risk management and prevents any single position from using all available cash.

2. **Does the Signal Dashboard show all signals or only signals with no auto-executed trade?**
   - What we know: UI-01 says "displays active signals with full position spec" and includes the auto-execute toggle
   - What's unclear: Whether signals already auto-executed should show with an indicator or be hidden
   - Recommendation: Show all signals from the last 7 days with an "Executed" boolean column that indicates whether a buy trade exists for that signal. This gives full visibility.

3. **How should `signals.rowid` be used as `source_signal_id`?**
   - What we know: Phase 4's `signals` table has a composite primary key `(ticker_a, ticker_b, signal_date)` with no integer PK; SQLite auto-creates a `rowid` for every table without explicit `WITHOUT ROWID`
   - What's unclear: Whether Phase 4 exposes `rowid` in any query; whether it is stable across schema recreations
   - Recommendation: Add an explicit `signal_id INTEGER PRIMARY KEY AUTOINCREMENT` column to the signals table in Phase 4's schema (or use `rowid` via `SELECT rowid, * FROM signals`). For Phase 5, use `SELECT rowid AS signal_id, ...` consistently. Document this dependency.

4. **Should the `paper_portfolio` table allow multiple portfolio rows (multi-portfolio support)?**
   - What we know: TRADE-01 says "user can set starting paper capital" (singular); v1 has one portfolio
   - What's unclear: Whether multi-portfolio is worth building into the schema now
   - Recommendation: Include `portfolio_id INTEGER PRIMARY KEY DEFAULT 1` in the schema to future-proof, but the v1 UI only creates/updates portfolio_id = 1. The `DEFAULT 1` means all queries that don't specify portfolio_id get portfolio 1 automatically.

---

## Sources

### Primary (HIGH confidence)
- `https://polygon.readthedocs.io/en/latest/Stocks.html` — `get_snapshot()`, `get_snapshot_all()`, `get_current_price()` method signatures; response structure confirmation
- `https://www.gradio.app/docs/gradio/timer` — `gr.Timer` constructor, `tick()` event, `active` parameter (verified available Gradio 4.37.1+)
- `https://www.gradio.app/guides/creating-a-realtime-dashboard-from-google-sheets` — `gr.Dataframe(fn, every=gr.Timer(N))` canonical pattern
- `https://github.com/gradio-app/gradio/pull/8505` — Timer introduced in Gradio v4.37.1, merged June 28, 2024
- `https://docs.python.org/3/library/sqlite3.html` — `check_same_thread` behavior; per-thread connection as best practice
- `https://pandas-market-calendars.readthedocs.io/en/latest/usage.html` — `open_at_time()` method, schedule API, `nyse.open_time`/`nyse.close_time`
- `https://pypi.org/project/pandas_market_calendars/` — version 5.3.0 (January 25, 2026), Python >=3.10 required

### Secondary (MEDIUM confidence)
- `https://docs.alpaca.markets/docs/position-average-entry-price-calculation` — Weighted average cost formula for positions; confirms average-cost (not FIFO) for intraday; informs `avg_cost` update formula
- WebSearch for Polygon snapshot `lastTrade.p` field — confirmed from polygon.readthedocs.io examples showing `"p": 20.506` in lastTrade object
- WebSearch for Gradio Dataframe `every=` deprecation note — confirmed in Gradio 4.44.1 docs: "`every=` will be deprecated in favor of `gr.Timer`"
- `https://www.gradio.app/guides/running-background-tasks` — APScheduler pattern for non-UI background jobs; confirms gr.Timer as the right approach for UI-driven polling

### Tertiary (LOW confidence — needs validation)
- Gradio `gr.Dataframe` stale-refresh bug (#8160, #10333) — reported in GitHub issues; fix status in latest Gradio version unverified. Add hidden timestamp column as defensive measure.
- Polygon snapshot 3:30 AM data clear behavior — cited in multiple sources but not validated against current Polygon docs (polygon.io redirects to massive.com); verify before relying on pre-market data behavior.

---

## Metadata

**Confidence breakdown:**
- SQLite schema: HIGH — designed from requirements with verified SQLite idioms (ON CONFLICT, partial unique index)
- Polygon snapshot endpoint: HIGH — URL and `lastTrade.p` field confirmed from readthedocs and multiple search sources
- gr.Timer API: HIGH — verified from official Gradio docs and the merged PR; version confirmed as 4.37.1
- Market hours detection (pandas_market_calendars): HIGH — current version 5.3.0 verified from PyPI, API verified from readthedocs
- Average-cost basis approach: HIGH — confirmed via Alpaca docs as the correct approach for intraday positions; matches requirements (paper trading, not tax tool)
- SQLite thread safety pattern: HIGH — Python stdlib docs explicitly recommend per-thread connections
- Sizing tier dollar fractions (20%/10%): LOW — Claude's recommendation; no external source defines these for this project; exposed as configurable constants

**Research date:** 2026-02-18
**Valid until:** 2026-03-20 (pandas_market_calendars, Gradio, Polygon API — 30-day window appropriate for stable libraries; Gradio version note valid as long as project stays on 4.x)
