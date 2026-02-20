"""Market data helpers for the comprehensive paper trading dashboard.

Provides price fetching (free-tier Polygon endpoints), SQLite price fallback,
indicator computation (MA20, MA50, RSI14, MACD), chart generation, and
signal suggestion queries.

Free-tier Polygon endpoints used:
  /v2/aggs/ticker/{ticker}/prev   -- previous trading day OHLCV
  /v3/reference/tickers/{ticker}  -- company reference data
"""

import sqlite3

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import requests

from utils.logging import get_logger

log = get_logger("paper_trading.market_data")

_POLYGON_BASE = "https://api.polygon.io"

SIGNAL_COLUMNS = [
    "Signal Date",
    "Leader",
    "Follower",
    "Direction",
    "Sizing Tier",
    "Stability",
    "Correlation",
    "Target",
    "Invalidation",
    "Warning",
]


def period_to_days(period: str) -> int:
    """Convert a period string to a number of calendar days for history queries.

    "1D"->2, "1W"->7, "1M"->30, "3M"->90, "6M"->180,
    "1Y"->365, "YTD"->days since Jan 1, "5Y"->1825.
    """
    from datetime import date as _date

    if period == "1D":
        return 2
    if period == "1W":
        return 7
    if period == "1M":
        return 30
    if period == "3M":
        return 90
    if period == "6M":
        return 180
    if period == "1Y":
        return 365
    if period == "YTD":
        today = _date.today()
        jan1 = _date(today.year, 1, 1)
        return max(2, (today - jan1).days + 1)
    if period == "5Y":
        return 1825
    return 180


def fetch_prev_close(ticker: str, api_key: str) -> float | None:
    """Fetch previous trading day close price from Polygon (free tier).

    Uses /v2/aggs/ticker/{ticker}/prev which is available on the free plan.
    Returns close price as float, or None on failure.
    """
    url = f"{_POLYGON_BASE}/v2/aggs/ticker/{ticker}/prev"
    try:
        resp = requests.get(url, params={"apiKey": api_key}, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            price = results[0].get("c") or results[0].get("vw")
            return float(price) if price else None
        return None
    except Exception as exc:
        log.error("fetch_prev_close_failed", ticker=ticker, error=str(exc)[:200])
        return None


def fetch_ticker_info(ticker: str, api_key: str) -> dict:
    """Fetch company reference data from Polygon (free tier).

    Uses /v3/reference/tickers/{ticker}.
    Returns dict with name, exchange, sector, market_cap_str.
    Falls back to minimal data on failure.
    """
    url = f"{_POLYGON_BASE}/v3/reference/tickers/{ticker}"
    try:
        resp = requests.get(url, params={"apiKey": api_key}, timeout=10)
        resp.raise_for_status()
        r = resp.json().get("results", {})
        market_cap = r.get("market_cap")
        if market_cap and market_cap >= 1e9:
            cap_str = f"${market_cap / 1e9:.2f}B"
        elif market_cap and market_cap >= 1e6:
            cap_str = f"${market_cap / 1e6:.1f}M"
        else:
            cap_str = "N/A"
        return {
            "name": r.get("name", ticker),
            "exchange": r.get("primary_exchange", ""),
            "sector": r.get("sic_description", ""),
            "market_cap_str": cap_str,
        }
    except Exception as exc:
        log.error("fetch_ticker_info_failed", ticker=ticker, error=str(exc)[:200])
        return {"name": ticker, "exchange": "", "sector": "", "market_cap_str": "N/A"}


def get_last_known_price(conn: sqlite3.Connection, ticker: str) -> float | None:
    """Get last adj_close from normalized_bars as a price fallback.

    Used when Polygon API is unavailable (e.g. free-tier 403 on snapshot).
    """
    try:
        row = conn.execute(
            "SELECT adj_close FROM normalized_bars"
            " WHERE ticker = ? ORDER BY trading_day DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        return float(row[0]) if row else None
    except Exception as exc:
        log.error("get_last_known_price_failed", ticker=ticker, error=str(exc)[:200])
        return None


def get_price_history(
    conn: sqlite3.Connection, ticker: str, days: int = 180
) -> pd.DataFrame:
    """Query adjusted price history from normalized_bars.

    Returns a chronologically-ordered DataFrame with columns:
    trading_day (datetime), open, high, low, close, volume.
    Returns empty DataFrame if no data found.
    """
    try:
        df = pd.read_sql_query(
            """
            SELECT trading_day,
                   adj_open  AS open,
                   adj_high  AS high,
                   adj_low   AS low,
                   adj_close AS close,
                   adj_volume AS volume
            FROM normalized_bars
            WHERE ticker = ?
            ORDER BY trading_day DESC
            LIMIT ?
            """,
            conn,
            params=(ticker, days),
        )
        if df.empty:
            return pd.DataFrame()
        # Reverse to chronological order
        df = df.iloc[::-1].reset_index(drop=True)
        df["trading_day"] = pd.to_datetime(df["trading_day"])
        return df
    except Exception as exc:
        log.error("get_price_history_failed", ticker=ticker, error=str(exc)[:200])
        return pd.DataFrame()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators to a price DataFrame.

    Adds: MA20, MA50, RSI(14), MACD(12,26,9) with signal and histogram.
    Input DataFrame must have a 'close' column.
    Returns a copy with indicator columns added.
    """
    if df.empty or len(df) < 2:
        return df

    df = df.copy()
    close = df["close"]

    # Moving averages
    df["ma20"] = close.rolling(window=20, min_periods=1).mean()
    df["ma50"] = close.rolling(window=50, min_periods=1).mean()

    # RSI(14) using exponential moving average (Wilder's smoothing)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD(12, 26) with 9-period signal line
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    return df


def _dark_layout(fig: go.Figure, title: str = "", height: int = 500) -> None:
    """Apply consistent dark theme to a Plotly figure in-place."""
    fig.update_layout(
        title=dict(text=title, font=dict(color="#e0e0e0", size=13)),
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#0f0f23",
        font=dict(color="#e0e0e0"),
        height=height,
        hovermode="x unified",
        legend=dict(
            bgcolor="#1a1a2e", bordercolor="#334466",
            font=dict(color="#e0e0e0"),
        ),
    )
    fig.update_xaxes(gridcolor="#334466", zerolinecolor="#334466", showgrid=True)
    fig.update_yaxes(gridcolor="#334466", zerolinecolor="#334466", showgrid=True)


def build_chart(df: pd.DataFrame, ticker: str) -> go.Figure | None:
    """Build an interactive 3-panel chart: Price + MAs, RSI(14), MACD.

    Hover shows the ticker name, date, and value for each trace.
    Returns a Plotly Figure suitable for gr.Plot, or None if df is empty.
    """
    if df.empty:
        return None

    dates = (
        df["trading_day"].dt.strftime("%Y-%m-%d").tolist()
        if "trading_day" in df.columns
        else list(range(len(df)))
    )

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.02,
    )

    # --- Panel 1: Price + Moving Averages ---
    fig.add_trace(go.Scatter(
        x=dates, y=df["close"].round(2),
        name=f"{ticker} Close",
        line=dict(color="#00bcd4", width=1.5),
        hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>Close: $%{{y:.2f}}<extra></extra>",
    ), row=1, col=1)

    if "ma20" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["ma20"].round(2),
            name="MA20",
            line=dict(color="#ff9800", width=1.0),
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>MA20: $%{{y:.2f}}<extra></extra>",
        ), row=1, col=1)

    if "ma50" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["ma50"].round(2),
            name="MA50",
            line=dict(color="#e91e63", width=1.0),
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>MA50: $%{{y:.2f}}<extra></extra>",
        ), row=1, col=1)

    # --- Panel 2: RSI ---
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["rsi"].round(2),
            name="RSI(14)",
            line=dict(color="#9c27b0", width=1.2),
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>RSI: %{{y:.1f}}<extra></extra>",
        ), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="#f44336", line_width=0.8, opacity=0.7, row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#4caf50", line_width=0.8, opacity=0.7, row=2, col=1)

    # --- Panel 3: MACD ---
    if "macd" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["macd"].round(4),
            name="MACD",
            line=dict(color="#2196f3", width=1.2),
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>MACD: %{{y:.4f}}<extra></extra>",
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=df["macd_signal"].round(4),
            name="Signal",
            line=dict(color="#ff5722", width=1.0, dash="dash"),
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>Signal: %{{y:.4f}}<extra></extra>",
        ), row=3, col=1)
        hist_colors = ["#4caf50" if v >= 0 else "#f44336" for v in df["macd_hist"]]
        fig.add_trace(go.Bar(
            x=dates, y=df["macd_hist"].round(4),
            name="Histogram",
            marker_color=hist_colors,
            opacity=0.5,
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>Hist: %{{y:.4f}}<extra></extra>",
        ), row=3, col=1)

    _dark_layout(fig, title=f"{ticker} — Price & Moving Averages", height=600)
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="RSI(14)", range=[0, 100], row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    return fig


PERFORMANCE_COLUMNS = [
    "Ticker",
    "Shares",
    "Avg Cost",
    "Last Close",
    "Market Value",
    "Total Return ($)",
    "Total Return (%)",
    "Daily Return ($)",
    "Daily Return (%)",
]


def get_performance_table(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> pd.DataFrame:
    """Build per-position performance table with total and daily returns.

    Uses normalized_bars for last two closes so figures are available even
    when the price poller hasn't run (i.e. outside market hours).

    Returns a DataFrame with PERFORMANCE_COLUMNS.
    """
    try:
        positions = conn.execute(
            "SELECT ticker, shares, avg_cost FROM paper_positions WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchall()

        if not positions:
            return pd.DataFrame(columns=PERFORMANCE_COLUMNS)

        data = []
        for pos in positions:
            ticker = pos[0]
            shares = float(pos[1])
            avg_cost = float(pos[2])

            # Last two closes for this ticker
            closes = conn.execute(
                """
                SELECT adj_close FROM normalized_bars
                WHERE ticker = ?
                ORDER BY trading_day DESC
                LIMIT 2
                """,
                (ticker,),
            ).fetchall()

            if not closes:
                continue

            last_close = float(closes[0][0])
            prev_close = float(closes[1][0]) if len(closes) > 1 else last_close

            market_value = last_close * shares
            total_ret_dollar = (last_close - avg_cost) * shares
            total_ret_pct = (last_close - avg_cost) / avg_cost * 100 if avg_cost else 0.0
            daily_ret_dollar = (last_close - prev_close) * shares
            daily_ret_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0

            data.append([
                ticker,
                int(shares),
                round(avg_cost, 2),
                round(last_close, 2),
                round(market_value, 2),
                round(total_ret_dollar, 2),
                round(total_ret_pct, 2),
                round(daily_ret_dollar, 2),
                round(daily_ret_pct, 2),
            ])

        return pd.DataFrame(data, columns=PERFORMANCE_COLUMNS)

    except Exception as exc:
        log.error("get_performance_table_failed", error=str(exc)[:200])
        return pd.DataFrame(columns=PERFORMANCE_COLUMNS)


def get_portfolio_value_history(
    conn: sqlite3.Connection, portfolio_id: int = 1, lookback_days: int = 180
) -> pd.DataFrame:
    """Reconstruct trading P&L for every trading day in the lookback window.

    Shows stock trade performance only — idle cash is excluded entirely.

    Algorithm:
      1. Walk ALL trades chronologically (not just the window) so the initial
         position state at window-start is always correct.
      2. For each trading day in the window compute:
           value = cumulative_realized_pnl
                   + sum((adj_close - avg_cost) * shares  for open positions)
      3. Baseline is 0 (break-even). Positive = net profit, negative = net loss.

    Returns a DataFrame with columns: date (str), value (float).
    """
    try:
        exists = conn.execute(
            "SELECT 1 FROM paper_portfolio WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()
        if exists is None:
            return pd.DataFrame(columns=["date", "value"])

        # All trades in chronological order (no date filter — need full history)
        trade_rows = conn.execute(
            """
            SELECT ticker, side, shares, price,
                   substr(executed_at, 1, 10) AS trade_date
            FROM paper_trades
            WHERE portfolio_id = ?
            ORDER BY executed_at ASC
            """,
            (portfolio_id,),
        ).fetchall()
        trades = [
            dict(zip(["ticker", "side", "shares", "price", "trade_date"], r))
            for r in trade_rows
        ]

        # Trading days within the lookback window
        days_rows = conn.execute(
            """
            SELECT DISTINCT trading_day FROM normalized_bars
            WHERE trading_day >= date(
                (SELECT MAX(trading_day) FROM normalized_bars), ? || ' days'
            )
            ORDER BY trading_day ASC
            """,
            (f"-{lookback_days}",),
        ).fetchall()
        trading_days = [r[0] for r in days_rows]

        if not trading_days:
            return pd.DataFrame(columns=["date", "value"])

        # Pre-load close prices for the window
        price_rows = conn.execute(
            """
            SELECT ticker, trading_day, adj_close FROM normalized_bars
            WHERE trading_day >= date(
                (SELECT MAX(trading_day) FROM normalized_bars), ? || ' days'
            )
            """,
            (f"-{lookback_days}",),
        ).fetchall()
        prices: dict[tuple, float] = {(r[0], r[1]): float(r[2]) for r in price_rows}

        # Walk forward tracking positions [shares, avg_cost] and realized P&L
        positions: dict[str, list[float]] = {}  # ticker → [shares, avg_cost]
        cumulative_realized = 0.0
        trade_idx = 0
        records = []

        for day in trading_days:
            # Apply all trades on or before this day
            while trade_idx < len(trades) and trades[trade_idx]["trade_date"] <= day:
                t = trades[trade_idx]
                ticker = t["ticker"]
                shares = float(t["shares"])
                price = float(t["price"])

                if t["side"] == "buy":
                    if ticker in positions:
                        old_shares, old_avg = positions[ticker]
                        new_shares = old_shares + shares
                        positions[ticker] = [
                            new_shares,
                            (old_shares * old_avg + shares * price) / new_shares,
                        ]
                    else:
                        positions[ticker] = [shares, price]
                else:
                    # Sell: realise P&L on the closed portion
                    if ticker in positions:
                        _, avg_cost = positions[ticker]
                        cumulative_realized += (price - avg_cost) * shares
                        remaining = positions[ticker][0] - shares
                        if remaining <= 0:
                            positions.pop(ticker, None)
                        else:
                            positions[ticker][0] = remaining

                trade_idx += 1

            # Unrealized P&L for open positions priced on this day
            unrealized = sum(
                (prices[(ticker, day)] - avg_cost) * shares
                for ticker, (shares, avg_cost) in positions.items()
                if (ticker, day) in prices
            )

            records.append({
                "date": day,
                "value": round(cumulative_realized + unrealized, 2),
            })

        return pd.DataFrame(records)

    except Exception as exc:
        log.error("get_portfolio_value_history_failed", error=str(exc)[:200])
        return pd.DataFrame(columns=["date", "value"])


def build_portfolio_value_chart(df: pd.DataFrame) -> go.Figure | None:
    """Build an interactive trading P&L chart (stocks only — excludes idle cash).

    Baseline is 0 (break-even). Green fill = profit, red fill = loss.
    Hover shows date and exact P&L value.
    Returns a Plotly Figure or None if df has fewer than 2 rows.
    """
    if df.empty or len(df) < 2:
        return None

    dates = df["date"].tolist()
    values = df["value"].tolist()

    fig = go.Figure()

    # Green fill for positive region, red for negative
    fig.add_trace(go.Scatter(
        x=dates, y=[max(v, 0) for v in values],
        fill="tozeroy", fillcolor="rgba(76,175,80,0.18)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=[min(v, 0) for v in values],
        fill="tozeroy", fillcolor="rgba(244,67,54,0.18)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))

    # P&L line
    fig.add_trace(go.Scatter(
        x=dates, y=values,
        name="Portfolio P&L",
        line=dict(color="#00bcd4", width=2.0),
        hovertemplate="%{x}<br>P&L: $%{y:,.2f}<extra>Portfolio P&L</extra>",
    ))

    fig.add_hline(y=0, line_dash="dash", line_color="#888888", line_width=0.9, opacity=0.7)

    _dark_layout(fig, title="Trading P&L Over Time  (Stocks Only — Excludes Idle Cash)", height=350)
    fig.update_yaxes(title_text="P&L ($)")
    return fig


def build_correlation_chart(
    conn: sqlite3.Connection,
    leader: str,
    followers: list[str],
    days: int = 180,
) -> go.Figure | None:
    """Build an interactive normalized price comparison chart.

    All series are indexed to 100 at their first available date.
    Hover shows the ticker name, date, and indexed value for every line.

    Args:
        conn: SQLite connection.
        leader: The reference ticker (plotted thicker in gold).
        followers: Follower tickers to overlay.
        days: Number of trading days of history to fetch.

    Returns:
        Plotly Figure, or None if no data is available.
    """
    tickers = [leader] + [f for f in followers if f != leader]

    raw: dict[str, pd.Series] = {}
    for ticker in tickers:
        df = get_price_history(conn, ticker, days=days)
        if not df.empty:
            raw[ticker] = df.set_index("trading_day")["close"]

    if not raw:
        return None

    combined = pd.DataFrame(raw).dropna(how="all")
    if combined.empty or len(combined) < 2:
        return None

    # Normalize each column: first valid value → 100
    normalized = combined.copy()
    for col in normalized.columns:
        first_idx = normalized[col].first_valid_index()
        if first_idx is not None:
            base = normalized[col][first_idx]
            if base and base != 0:
                normalized[col] = normalized[col] / base * 100

    follower_palette = [
        "#ff9800", "#e91e63", "#4caf50",
        "#9c27b0", "#00bcd4", "#ff5722", "#03a9f4",
    ]

    date_strs = [str(d)[:10] for d in normalized.index]
    fig = go.Figure()

    # Leader — thick gold reference line
    if leader in normalized.columns:
        fig.add_trace(go.Scatter(
            x=date_strs,
            y=normalized[leader].round(2),
            name=f"{leader} (leader)",
            line=dict(color="#ffd700", width=2.5),
            hovertemplate=f"<b>{leader} (leader)</b><br>%{{x}}<br>Indexed: %{{y:.2f}}<extra></extra>",
        ))

    # Followers — coloured lines
    for i, ticker in enumerate(followers):
        if ticker in normalized.columns:
            color = follower_palette[i % len(follower_palette)]
            fig.add_trace(go.Scatter(
                x=date_strs,
                y=normalized[ticker].round(2),
                name=ticker,
                line=dict(color=color, width=1.8),
                opacity=0.9,
                hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>Indexed: %{{y:.2f}}<extra></extra>",
            ))

    fig.add_hline(y=100, line_dash="dash", line_color="#334466", line_width=0.8, opacity=0.5)

    follower_str = ", ".join(followers) if followers else "none"
    _dark_layout(
        fig,
        title=f"Correlation View — Leader: {leader}  |  Positions: {follower_str}",
        height=450,
    )
    fig.update_yaxes(title_text="Indexed Price (start = 100)")
    return fig


def get_signal_suggestions(conn: sqlite3.Connection, days: int = 30) -> pd.DataFrame:
    """Query recent signals for the algorithm suggestion panel.

    Returns signals from the last `days` days ordered by generated_at DESC.
    """
    try:
        rows = conn.execute(
            """
            SELECT signal_date, ticker_a, ticker_b, direction,
                   sizing_tier, stability_score, correlation_strength,
                   expected_target, invalidation_threshold, data_warning
            FROM signals
            WHERE signal_date >= date('now', ? || ' days')
            ORDER BY generated_at DESC
            """,
            (f"-{days}",),
        ).fetchall()

        if not rows:
            return pd.DataFrame(columns=SIGNAL_COLUMNS)

        data = []
        for row in rows:
            row = dict(row)
            data.append([
                row["signal_date"],
                row["ticker_a"],
                row["ticker_b"],
                row["direction"],
                row["sizing_tier"],
                round(row["stability_score"], 1) if row["stability_score"] is not None else None,
                round(row["correlation_strength"], 3) if row["correlation_strength"] is not None else None,
                round(row["expected_target"], 4) if row["expected_target"] is not None else None,
                round(row["invalidation_threshold"], 4) if row["invalidation_threshold"] is not None else None,
                row["data_warning"] or "",
            ])
        return pd.DataFrame(data, columns=SIGNAL_COLUMNS)

    except Exception as exc:
        log.error("get_signal_suggestions_failed", error=str(exc)[:200])
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
