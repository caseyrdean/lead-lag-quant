"""Market data helpers for the comprehensive paper trading dashboard.

Provides price fetching (free-tier Polygon endpoints), SQLite price fallback,
indicator computation (MA20, MA50, RSI14, MACD), chart generation, and
signal suggestion queries.

Free-tier Polygon endpoints used:
  /v2/aggs/ticker/{ticker}/prev   -- previous trading day OHLCV
  /v3/reference/tickers/{ticker}  -- company reference data
"""

import sqlite3

import matplotlib
matplotlib.use("Agg")  # Must be before pyplot import to avoid GUI errors
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
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


def build_chart(df: pd.DataFrame, ticker: str) -> plt.Figure | None:
    """Build a 3-panel chart: Price + MAs, RSI(14), MACD.

    Returns a matplotlib Figure suitable for gr.Plot, or None if df is empty.
    Closes all prior figures to avoid memory leaks.
    """
    if df.empty:
        return None

    plt.close("all")

    bg_dark = "#1a1a2e"
    panel_bg = "#0f0f23"
    text_color = "#e0e0e0"
    grid_color = "#334466"

    fig = plt.figure(figsize=(12, 8), facecolor=bg_dark)
    gs = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)
    fig.patch.set_facecolor(bg_dark)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    x = range(len(df))

    # --- Panel 1: Price + Moving Averages ---
    ax1.set_facecolor(panel_bg)
    ax1.plot(x, df["close"], color="#00bcd4", linewidth=1.5, label="Close")
    if "ma20" in df.columns:
        ax1.plot(x, df["ma20"], color="#ff9800", linewidth=1.0, label="MA20", alpha=0.9)
    if "ma50" in df.columns:
        ax1.plot(x, df["ma50"], color="#e91e63", linewidth=1.0, label="MA50", alpha=0.9)
    ax1.set_title(
        f"{ticker} — Price & Moving Averages",
        color=text_color, fontsize=11, pad=6,
    )
    ax1.set_ylabel("Price ($)", color=text_color, fontsize=9)
    ax1.legend(
        loc="upper left", fontsize=8,
        facecolor=bg_dark, labelcolor=text_color, framealpha=0.7,
    )
    ax1.tick_params(colors=text_color, labelbottom=False)
    ax1.grid(color=grid_color, alpha=0.5, linewidth=0.5)
    for spine in ax1.spines.values():
        spine.set_color(grid_color)

    # --- Panel 2: RSI ---
    ax2.set_facecolor(panel_bg)
    if "rsi" in df.columns:
        ax2.plot(x, df["rsi"], color="#9c27b0", linewidth=1.2)
        ax2.axhline(70, color="#f44336", linewidth=0.8, linestyle="--", alpha=0.7)
        ax2.axhline(30, color="#4caf50", linewidth=0.8, linestyle="--", alpha=0.7)
        ax2.fill_between(
            x, df["rsi"], 70, where=(df["rsi"] >= 70),
            alpha=0.12, color="#f44336",
        )
        ax2.fill_between(
            x, df["rsi"], 30, where=(df["rsi"] <= 30),
            alpha=0.12, color="#4caf50",
        )
        ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI(14)", color=text_color, fontsize=9)
    ax2.tick_params(colors=text_color, labelbottom=False)
    ax2.grid(color=grid_color, alpha=0.5, linewidth=0.5)
    for spine in ax2.spines.values():
        spine.set_color(grid_color)

    # --- Panel 3: MACD ---
    ax3.set_facecolor(panel_bg)
    if "macd" in df.columns:
        ax3.plot(x, df["macd"], color="#2196f3", linewidth=1.2, label="MACD")
        ax3.plot(
            x, df["macd_signal"], color="#ff5722",
            linewidth=1.0, linestyle="--", label="Signal",
        )
        hist_colors = [
            "#4caf50" if v >= 0 else "#f44336"
            for v in df["macd_hist"]
        ]
        ax3.bar(x, df["macd_hist"], color=hist_colors, alpha=0.5, width=0.8)
        ax3.axhline(0, color=grid_color, linewidth=0.8, alpha=0.7)
        ax3.legend(
            loc="upper left", fontsize=8,
            facecolor=bg_dark, labelcolor=text_color, framealpha=0.7,
        )
    ax3.set_ylabel("MACD", color=text_color, fontsize=9)
    ax3.grid(color=grid_color, alpha=0.5, linewidth=0.5)
    for spine in ax3.spines.values():
        spine.set_color(grid_color)

    # X-axis date labels on bottom panel only
    n = len(df)
    step = max(1, n // 8)
    tick_positions = list(range(0, n, step))
    if "trading_day" in df.columns:
        tick_labels = [str(df["trading_day"].iloc[i])[:10] for i in tick_positions]
    else:
        tick_labels = [str(i) for i in tick_positions]
    ax3.set_xticks(tick_positions)
    ax3.set_xticklabels(tick_labels, rotation=30, fontsize=7, color=text_color)

    fig.subplots_adjust(left=0.07, right=0.97, top=0.94, bottom=0.10)
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


def build_portfolio_value_chart(df: pd.DataFrame) -> plt.Figure | None:
    """Build a trading P&L chart (stocks only — excludes idle cash).

    Baseline is 0 (break-even). Green fill = profit, red fill = loss.
    Latest P&L annotated with sign prefix.

    Returns a matplotlib Figure or None if df has fewer than 2 rows.
    """
    if df.empty or len(df) < 2:
        return None

    plt.close("all")

    bg = "#1a1a2e"
    panel_bg = "#0f0f23"
    text_color = "#e0e0e0"
    grid_color = "#334466"

    fig, ax = plt.subplots(figsize=(13, 4), facecolor=bg)
    ax.set_facecolor(panel_bg)

    x = range(len(df))
    values = df["value"].tolist()

    ax.plot(x, values, color="#00bcd4", linewidth=2.0, zorder=3)

    # Green fill above 0, red fill below 0
    ax.fill_between(
        x, values, 0,
        where=[v >= 0 for v in values],
        alpha=0.18, color="#4caf50", zorder=2,
    )
    ax.fill_between(
        x, values, 0,
        where=[v < 0 for v in values],
        alpha=0.18, color="#f44336", zorder=2,
    )

    # Break-even reference line
    ax.axhline(
        0, color="#888", linewidth=0.9,
        linestyle="--", alpha=0.7, label="Break-even",
    )

    # Annotate latest P&L with green "+" or red "-" prefix
    latest = values[-1]
    if latest >= 0:
        ann_text = f"  +${latest:,.2f}"
        ann_color = "#4caf50"
    else:
        ann_text = f"  -${abs(latest):,.2f}"
        ann_color = "#f44336"
    ax.annotate(ann_text, xy=(len(df) - 1, latest), color=ann_color, fontsize=9, va="center")

    ax.set_title(
        "Trading P&L Over Time  (Stocks Only — Excludes Idle Cash)",
        color=text_color, fontsize=11, pad=6,
    )
    ax.set_ylabel("P&L ($)", color=text_color, fontsize=9)
    ax.legend(loc="upper left", fontsize=8, facecolor=bg, labelcolor=text_color, framealpha=0.7)
    ax.tick_params(colors=text_color)
    ax.grid(color=grid_color, alpha=0.5, linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_color(grid_color)

    # X-axis date labels
    n = len(df)
    step = max(1, n // 8)
    tick_positions = list(range(0, n, step))
    tick_labels = [df["date"].iloc[i] for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=30, fontsize=7, color=text_color)

    fig.patch.set_facecolor(bg)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.90, bottom=0.18)
    return fig


def build_correlation_chart(
    conn: sqlite3.Connection,
    leader: str,
    followers: list[str],
    days: int = 180,
) -> plt.Figure | None:
    """Build a normalized price comparison chart: leader vs follower stocks.

    All series are indexed to 100 at their first available date so relative
    performance is directly comparable on one axis.

    Args:
        conn: SQLite connection.
        leader: The reference ticker (plotted thicker in gold).
        followers: Follower tickers to overlay.
        days: Number of trading days of history to fetch.

    Returns:
        matplotlib Figure, or None if no data is available.
    """
    tickers = [leader] + [f for f in followers if f != leader]

    # Fetch close series for each ticker
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

    plt.close("all")

    bg = "#1a1a2e"
    panel_bg = "#0f0f23"
    text_color = "#e0e0e0"
    grid_color = "#334466"
    follower_palette = [
        "#ff9800", "#e91e63", "#4caf50",
        "#9c27b0", "#00bcd4", "#ff5722", "#03a9f4",
    ]

    fig, ax = plt.subplots(figsize=(13, 6), facecolor=bg)
    ax.set_facecolor(panel_bg)

    x = range(len(normalized))

    # Leader — thick gold reference line
    if leader in normalized.columns:
        ax.plot(
            x, normalized[leader],
            color="#ffd700", linewidth=2.5,
            label=f"{leader} (leader)", zorder=5,
        )

    # Followers — coloured lines
    color_idx = 0
    for ticker in followers:
        if ticker in normalized.columns:
            color = follower_palette[color_idx % len(follower_palette)]
            ax.plot(
                x, normalized[ticker],
                color=color, linewidth=1.8,
                label=ticker, alpha=0.9,
            )
            color_idx += 1

    # Baseline reference
    ax.axhline(100, color=grid_color, linewidth=0.8, linestyle="--", alpha=0.5)

    follower_str = ", ".join(followers) if followers else "none"
    ax.set_title(
        f"Correlation View — Leader: {leader}  |  Positions: {follower_str}",
        color=text_color, fontsize=11, pad=8,
    )
    ax.set_ylabel("Indexed Price (start = 100)", color=text_color, fontsize=9)
    ax.legend(
        loc="upper left", fontsize=9,
        facecolor=bg, labelcolor=text_color, framealpha=0.75,
    )
    ax.tick_params(colors=text_color)
    ax.grid(color=grid_color, alpha=0.5, linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_color(grid_color)

    # X-axis date labels
    n = len(normalized)
    step = max(1, n // 8)
    tick_positions = list(range(0, n, step))
    tick_labels = [str(normalized.index[i])[:10] for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=30, fontsize=7, color=text_color)

    fig.patch.set_facecolor(bg)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.92, bottom=0.12)
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
