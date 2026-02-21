# Lead-Lag Quant

A quantitative pairs trading platform that detects when one stock statistically leads another and generates paper trading signals based on that relationship.

The core idea: if Stock A consistently moves before Stock B does — measured across dozens of trading days — that predictive lag can be identified, scored, and traded. The platform handles the full pipeline from raw data ingestion through signal generation, paper trade execution, and performance analytics.

---

## What It Does

**Data layer.** Pulls unadjusted OHLCV bars, stock splits, and dividends from Polygon.io for every pair you register. Split adjustments are applied backwards (Policy A) so closing prices are historically consistent. Multi-period returns (1d, 5d, 10d, 20d, 60d) are computed and stored.

**Feature engineering.** Each ticker's returns are residualized against SPY to strip out the broad market factor. Rolling 60-day cross-correlations are computed at lags -5 to +5 trading sessions with Bonferroni correction (alpha 0.05 across 11 tests) to control false positives.

**Lead-lag detection.** For each pair, the optimal lag is identified from the stored correlations. A five-component stability score (0-100) is computed from lag persistence, walk-forward out-of-sample performance, rolling confirmation, regime stability, and lag drift.

**Signal generation.** A signal is only generated when stability is at or above 50 and absolute correlation is at or above 0.50. Signals carry a sizing tier — full (20% of capital), half (10%), or quarter (5%) — determined by how strong the relationship is. Each signal includes an expected target price and an invalidation threshold.

**Paper trading.** Signals are auto-executed into a simulated portfolio. Positions track average cost, current price, and unrealized P&L. A background thread fetches live prices from Polygon every 60 seconds during market hours and falls back to the most recent closing price outside of them.

**Analytics.** The analytics tab shows Sharpe ratio, max drawdown (dollar and percent), Calmar ratio, recovery factor, profit factor, win rate, and per-ticker breakdown. Charts include equity curve with drawdown overlay, P&L distribution, P&L by ticker, and a monthly P&L heatmap.

---

## Requirements

- Python 3.12 or higher
- A [Polygon.io](https://polygon.io) API key (free tier works)
- `uv` for dependency management (or standard pip)

Free tier gives you 5 API requests per minute. The rate limiter respects this automatically; ingestion just takes longer with a lot of pairs.

---

## Setup

```bash
git clone https://github.com/caseyrdean/lead-lag-quant.git
cd lead-lag-quant

# Install dependencies
uv sync

# Create a .env file with your API key
echo "POLYGON_API_KEY=your_key_here" > .env
```

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `POLYGON_API_KEY` | required | Polygon.io API key |
| `DB_PATH` | `data/market_data.db` | Path to the SQLite database |
| `PLAN_TIER` | `free` | `free` or `paid` (affects rate limit validation) |

---

## Running

```bash
uv run python main.py
```

Open `http://localhost:7860` in a browser.

---

## Workflow

Work through the tabs left to right:

1. **Pair Management** — Add leader and follower tickers. Both are validated against Polygon before being saved. You can add multiple followers at once with a comma-separated list.

2. **Data Ingestion** — Set a date range and fetch OHLCV data for all active pairs. SPY is always fetched as a benchmark. Progress updates per ticker.

3. **Normalize** — Apply split adjustments and compute multi-period returns. Safe to re-run at any time.

4. **Signal Dashboard** — Click Run Analysis to compute features and run the lead-lag engine. Signals from the past 7 days are shown in a table with direction, sizing tier, stability score, and execution status.

5. **Paper Trading** — Look up individual tickers, execute trades manually or let the system auto-execute signals, track open positions with live P&L, and review trade history.

6. **Analytics** — Full performance breakdown for the paper trading portfolio.

After the initial setup, the pipeline runs automatically each trading day after 5pm ET so data and signals stay current without manual intervention.

---

## Architecture

```
Polygon API
    |
ingestion_massive/      — fetch and store raw OHLCV, splits, dividends
    |
normalization/          — split-adjust bars, compute returns
    |
features/               — SPY residualization, rolling cross-correlations
    |
leadlag_engine/         — optimal lag detection, stability scoring, signal gating
    |
paper_trading/          — portfolio management, price polling, analytics
    |
ui/                     — Gradio interface (6 tabs)

utils/
  pipeline_scheduler.py       — daily background pipeline (ingest → signals)
  background_price_poller.py  — live price refresh every 60s during market hours
```

**Database:** SQLite with WAL mode. All state lives in `data/market_data.db`. The schema covers raw ingestion logs, normalized bars, returns, cross-correlation features, generated signals, and the paper trading portfolio.

---

## Signal Logic

A signal passes the gate when both conditions hold:

- Stability score >= 50
- Absolute correlation >= 0.50

Sizing:
- **Full** (20% of capital): stability >= 60 and |corr| >= 0.70
- **Half** (10% of capital): stability >= 50 and |corr| >= 0.50

The invalidation threshold is set at twice the mean absolute 1-day return of the leader over the lookback window. If the follower moves beyond that threshold, the position is flagged for exit.

---

## Limitations

- Paper trading only. No broker integration for live execution.
- Free-tier Polygon users will see slower ingestion due to the 5 req/min cap. Paid tier is faster.
- The minimum useful history is around 60 trading days per pair. Stability scores are most meaningful above 120 days.
- Price updates are not tick-level. During market hours, position prices refresh every 60 seconds via the Polygon snapshot endpoint. Outside market hours, the most recent closing price from the database is used.
- No slippage or commissions are modeled in the paper trading simulation.
- SPY is required as a benchmark for residualization. If SPY data is missing, feature computation will fail.
