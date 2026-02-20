"""Analytics computations for the paper trading performance dashboard.

All data comes from SQLite — no API calls.
"""

import sqlite3
import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd

from paper_trading.market_data import get_portfolio_value_history
from utils.logging import get_logger

log = get_logger("paper_trading.analytics")

# ---------------------------------------------------------------------------
# Dark-theme color constants (matches market_data.py style)
# ---------------------------------------------------------------------------
BG = "#1a1a2e"
PANEL = "#0f0f23"
TEXT = "#e0e0e0"
GRID = "#334466"
GREEN = "#4caf50"
RED = "#f44336"
CYAN = "#00bcd4"

TICKER_BREAKDOWN_COLUMNS = [
    "Ticker",
    "Trades",
    "Win Rate (%)",
    "Total P&L ($)",
    "Avg P&L ($)",
    "Best ($)",
    "Worst ($)",
]


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def get_trade_stats(conn: sqlite3.Connection, portfolio_id: int = 1) -> dict:
    """Compute trade-level statistics from closed (sell) trades.

    Returns a dict with keys:
        total_closed, winning, losing, win_rate, profit_factor, payoff_ratio,
        best_trade, worst_trade, avg_trade, total_realized_pnl, expectancy
    Returns all-zeros dict if no sell trades exist.
    """
    rows = conn.execute(
        "SELECT realized_pnl FROM paper_trades "
        "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = ?",
        (portfolio_id,),
    ).fetchall()

    zero = {
        "total_closed": 0,
        "winning": 0,
        "losing": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "payoff_ratio": 0.0,
        "best_trade": 0.0,
        "worst_trade": 0.0,
        "avg_trade": 0.0,
        "total_realized_pnl": 0.0,
        "expectancy": 0.0,
    }

    if not rows:
        return zero

    pnl_values = [r[0] for r in rows]
    wins = [v for v in pnl_values if v > 0]
    losses = [v for v in pnl_values if v <= 0]

    total_closed = len(pnl_values)
    winning = len(wins)
    losing = len(losses)
    win_rate = (winning / total_closed) * 100 if total_closed > 0 else 0.0
    loss_rate = losing / total_closed if total_closed > 0 else 0.0

    gross_wins = sum(wins)
    gross_losses = sum(losses)  # <= 0

    profit_factor = gross_wins / abs(gross_losses) if gross_losses != 0 else float("inf")

    avg_win = gross_wins / winning if winning > 0 else 0.0
    avg_loss = abs(gross_losses) / losing if losing > 0 else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss != 0 else float("inf")

    best_trade = max(pnl_values)
    worst_trade = min(pnl_values)
    avg_trade = sum(pnl_values) / total_closed

    expectancy = (win_rate / 100 * avg_win) - (loss_rate * avg_loss)

    return {
        "total_closed": total_closed,
        "winning": winning,
        "losing": losing,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "avg_trade": avg_trade,
        "total_realized_pnl": sum(pnl_values),
        "expectancy": expectancy,
    }


def get_risk_metrics(
    conn: sqlite3.Connection, portfolio_id: int = 1, lookback_days: int = 365
) -> dict:
    """Compute portfolio-level risk metrics from value history.

    Returns a dict with keys:
        sharpe_ratio, max_drawdown_dollar, max_drawdown_pct, calmar_ratio,
        recovery_factor
    Returns all-zeros dict if fewer than 2 data points.
    """
    zero = {
        "sharpe_ratio": 0.0,
        "max_drawdown_dollar": 0.0,
        "max_drawdown_pct": 0.0,
        "calmar_ratio": 0.0,
        "recovery_factor": 0.0,
    }

    df = get_portfolio_value_history(conn, portfolio_id, lookback_days)
    if df.empty or len(df) < 2:
        return zero

    series = df["value"].astype(float)

    daily_delta = series.diff().dropna()
    std = daily_delta.std()
    mean = daily_delta.mean()
    sharpe_ratio = (mean / std) * math.sqrt(252) if std != 0 else 0.0

    running_peak = series.cummax()
    dd_dollar = series - running_peak  # <= 0
    dd_pct = dd_dollar / running_peak.replace(0, float("nan")) * 100

    max_drawdown_dollar = float(dd_dollar.min())
    max_drawdown_pct = float(dd_pct.min()) if not dd_pct.isna().all() else 0.0

    total_return = float(series.iloc[-1])
    calmar_ratio = (
        total_return / abs(max_drawdown_pct)
        if max_drawdown_pct != 0
        else 0.0
    )

    stats = get_trade_stats(conn, portfolio_id)
    total_realized_pnl = stats["total_realized_pnl"]
    recovery_factor = (
        total_realized_pnl / abs(max_drawdown_dollar)
        if max_drawdown_dollar != 0
        else 0.0
    )

    return {
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown_dollar": round(max_drawdown_dollar, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "calmar_ratio": round(calmar_ratio, 4),
        "recovery_factor": round(recovery_factor, 4),
    }


def get_ticker_breakdown(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> pd.DataFrame:
    """Return per-ticker trade statistics for closed trades.

    Columns: Ticker, Trades, Win Rate (%), Total P&L ($), Avg P&L ($),
             Best ($), Worst ($).
    Sorted descending by Total P&L.
    """
    rows = conn.execute(
        "SELECT ticker, realized_pnl FROM paper_trades "
        "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = ?",
        (portfolio_id,),
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=TICKER_BREAKDOWN_COLUMNS)

    df = pd.DataFrame(rows, columns=["ticker", "realized_pnl"])

    records = []
    for ticker, grp in df.groupby("ticker"):
        pnl = grp["realized_pnl"].tolist()
        wins = [v for v in pnl if v > 0]
        total = len(pnl)
        records.append(
            {
                "Ticker": ticker,
                "Trades": total,
                "Win Rate (%)": round((len(wins) / total) * 100, 1) if total else 0.0,
                "Total P&L ($)": round(sum(pnl), 2),
                "Avg P&L ($)": round(sum(pnl) / total, 2) if total else 0.0,
                "Best ($)": round(max(pnl), 2),
                "Worst ($)": round(min(pnl), 2),
            }
        )

    result = pd.DataFrame(records, columns=TICKER_BREAKDOWN_COLUMNS)
    return result.sort_values("Total P&L ($)", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _dark_layout(fig: go.Figure, title: str = "", height: int = 500) -> None:
    """Apply consistent dark theme to a Plotly figure in-place."""
    fig.update_layout(
        title=dict(text=title, font=dict(color=TEXT, size=13)),
        paper_bgcolor=BG,
        plot_bgcolor=PANEL,
        font=dict(color=TEXT),
        height=height,
        hovermode="x unified",
        legend=dict(bgcolor=BG, bordercolor=GRID, font=dict(color=TEXT)),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, showgrid=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, showgrid=True)


def build_equity_drawdown_chart(
    conn: sqlite3.Connection, portfolio_id: int = 1, period: str = "6M"
) -> go.Figure | None:
    """Build an interactive 2-panel equity curve + drawdown chart.

    Hover shows date and exact value on each panel.
    Returns None if fewer than 2 data points.
    """
    from paper_trading.market_data import period_to_days

    lookback_days = period_to_days(period)
    df = get_portfolio_value_history(conn, portfolio_id, lookback_days)

    if df.empty or len(df) < 2:
        return None

    dates = df["date"].tolist()
    values = df["value"].astype(float).tolist()

    running_peak = df["value"].astype(float).cummax()
    dd_pct = (
        (df["value"].astype(float) - running_peak)
        / running_peak.replace(0, float("nan"))
        * 100
    ).fillna(0.0).tolist()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.03,
    )

    # --- Top panel: cumulative P&L ---
    fig.add_trace(go.Scatter(
        x=dates, y=[max(v, 0) for v in values],
        fill="tozeroy", fillcolor="rgba(76,175,80,0.2)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=[min(v, 0) for v in values],
        fill="tozeroy", fillcolor="rgba(244,67,54,0.2)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=values,
        name="Cumulative P&L",
        line=dict(color=CYAN, width=1.5),
        hovertemplate="%{x}<br>P&L: $%{y:,.2f}<extra>Cumulative P&L</extra>",
    ), row=1, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color=TEXT, line_width=0.8, opacity=0.5, row=1, col=1)

    # --- Bottom panel: drawdown % ---
    fig.add_trace(go.Scatter(
        x=dates, y=dd_pct,
        name="Drawdown %",
        fill="tozeroy", fillcolor="rgba(244,67,54,0.6)",
        line=dict(color=RED, width=0.8),
        hovertemplate="%{x}<br>Drawdown: %{y:.2f}%<extra>Drawdown</extra>",
    ), row=2, col=1)

    _dark_layout(fig, title=f"Equity Curve ({period})", height=550)
    fig.update_yaxes(title_text="Cumulative P&L ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)
    return fig


def build_pnl_distribution_chart(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> go.Figure | None:
    """Interactive histogram of realized P&L per closed trade.

    Green bars for wins, red bars for losses, shared bin edges.
    Hover shows P&L range and count.
    Returns None if no closed trades.
    """
    rows = conn.execute(
        "SELECT realized_pnl FROM paper_trades "
        "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = ?",
        (portfolio_id,),
    ).fetchall()

    if not rows:
        return None

    pnl = np.array([r[0] for r in rows], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    n_bins = min(20, len(pnl))
    bin_edges = np.histogram_bin_edges(pnl, bins=n_bins)
    bin_size = float(bin_edges[1] - bin_edges[0]) if len(bin_edges) > 1 else 1.0

    fig = go.Figure()

    if len(wins) > 0:
        fig.add_trace(go.Histogram(
            x=wins, name="Wins",
            marker_color=GREEN, opacity=0.75,
            xbins=dict(start=float(bin_edges[0]), end=float(bin_edges[-1]), size=bin_size),
            hovertemplate="P&L: $%{x:.2f}<br>Count: %{y}<extra>Wins</extra>",
        ))
    if len(losses) > 0:
        fig.add_trace(go.Histogram(
            x=losses, name="Losses",
            marker_color=RED, opacity=0.75,
            xbins=dict(start=float(bin_edges[0]), end=float(bin_edges[-1]), size=bin_size),
            hovertemplate="P&L: $%{x:.2f}<br>Count: %{y}<extra>Losses</extra>",
        ))

    fig.add_vline(x=0, line_dash="dash", line_color=TEXT, line_width=1.2, opacity=0.7)

    _dark_layout(fig, title="P&L Distribution", height=400)
    fig.update_layout(barmode="overlay", hovermode="x", xaxis_title="Realized P&L ($)", yaxis_title="Frequency")
    return fig


def build_ticker_pnl_chart(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> go.Figure | None:
    """Interactive horizontal bar chart of total realized P&L per ticker.

    Bars sorted descending (winners on top). Green >= 0, red < 0.
    Hover shows the ticker name and exact P&L.
    Returns None if no closed trades.
    """
    rows = conn.execute(
        "SELECT ticker, SUM(realized_pnl) FROM paper_trades "
        "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = ? "
        "GROUP BY ticker",
        (portfolio_id,),
    ).fetchall()

    if not rows:
        return None

    # Sort ascending so highest value ends up on top after autorange="reversed"
    paired = sorted(rows, key=lambda r: r[1])
    tickers_sorted = [r[0] for r in paired]
    totals_sorted = [r[1] for r in paired]
    n_tickers = len(tickers_sorted)

    colors = [GREEN if v >= 0 else RED for v in totals_sorted]

    fig = go.Figure(go.Bar(
        x=totals_sorted,
        y=tickers_sorted,
        orientation="h",
        marker_color=colors,
        opacity=0.85,
        text=[f"${v:,.2f}" for v in totals_sorted],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>P&L: $%{x:,.2f}<extra></extra>",
    ))

    fig.add_vline(x=0, line_color=GRID, line_width=0.8, opacity=0.7)

    _dark_layout(fig, title="P&L by Ticker", height=max(350, 50 * n_tickers + 100))
    fig.update_layout(hovermode="closest", xaxis_title="Total Realized P&L ($)")
    fig.update_yaxes(autorange="reversed")
    return fig


def build_monthly_heatmap_chart(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> go.Figure | None:
    """Interactive monthly P&L heatmap (months × years).

    Colormap: RED → dark → GREEN, centered at 0.
    Hover shows month, year, and exact P&L.
    Returns None if no closed trades.
    """
    rows = conn.execute(
        "SELECT strftime('%Y', executed_at) AS yr, "
        "       strftime('%m', executed_at) AS mo, "
        "       SUM(realized_pnl) "
        "FROM paper_trades "
        "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = ? "
        "GROUP BY yr, mo",
        (portfolio_id,),
    ).fetchall()

    if not rows:
        return None

    records = [(r[0], int(r[1]), r[2]) for r in rows]
    years = sorted(set(r[0] for r in records))
    month_abbrevs = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # Build grid: rows=months (1-12), cols=years
    grid = [[None] * len(years) for _ in range(12)]
    year_idx = {y: i for i, y in enumerate(years)}
    for yr, mo, total in records:
        grid[mo - 1][year_idx[yr]] = total

    finite_vals = [v for row in grid for v in row if v is not None]
    if not finite_vals:
        return None

    vmin = float(min(finite_vals))
    vmax = float(max(finite_vals))
    if vmin >= 0:
        vmin = -1.0
    if vmax <= 0:
        vmax = 1.0

    # Position 0 on the colorscale
    zero_frac = (0.0 - vmin) / (vmax - vmin)
    colorscale = [[0.0, RED], [zero_frac, PANEL], [1.0, GREEN]]

    # Replace None with NaN for Plotly; build hover and annotation text
    grid_display = [[v if v is not None else float("nan") for v in row] for row in grid]
    annot = [[f"${v:,.0f}" if v is not None else "" for v in row] for row in grid]
    hover = [
        [
            f"{month_abbrevs[mi]} {years[yi]}<br>P&L: ${grid[mi][yi]:,.0f}"
            if grid[mi][yi] is not None else "No trades"
            for yi in range(len(years))
        ]
        for mi in range(12)
    ]

    fig = go.Figure(go.Heatmap(
        z=grid_display,
        x=years,
        y=month_abbrevs,
        colorscale=colorscale,
        zmin=vmin,
        zmax=vmax,
        text=annot,
        texttemplate="%{text}",
        hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>",
        showscale=True,
        colorbar=dict(title="P&L ($)", tickfont=dict(color=TEXT), titlefont=dict(color=TEXT)),
    ))

    _dark_layout(fig, title="Monthly P&L Heatmap", height=500)
    fig.update_layout(hovermode="closest")
    return fig
