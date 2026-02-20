"""Comprehensive Paper Trading Dashboard (UI-04).

Provides:
  - Stock lookup: prev close price + company info from Polygon (free tier)
  - Price chart with MA20, MA50, RSI(14), MACD via matplotlib
  - Buy/sell orders using the looked-up price (stored in gr.State)
  - Portfolio summary: cash, unrealized P&L, realized P&L, total P&L, win rate
  - Reset Capital (collapsible accordion)
  - Open positions table with 15-min auto-refresh via gr.Timer
  - Algorithm signal suggestions from the signals table
  - Full trade history
"""

import sqlite3
from datetime import datetime, timezone

import gradio as gr
import pandas as pd

from paper_trading.engine import (
    close_position,
    get_open_positions_display,
    get_portfolio_summary,
    get_trade_history_display,
    open_or_add_position,
    set_capital,
)
from paper_trading.market_data import (
    build_chart,
    build_correlation_chart,
    build_portfolio_value_chart,
    compute_indicators,
    fetch_prev_close,
    fetch_ticker_info,
    get_last_known_price,
    get_performance_table,
    get_portfolio_value_history,
    get_price_history,
    get_signal_suggestions,
    period_to_days,
    PERFORMANCE_COLUMNS,
    SIGNAL_COLUMNS,
)
from paper_trading.price_poller import get_market_status_label
from utils.config import AppConfig
from utils.logging import get_logger

log = get_logger("ui.paper_trading_panel")

POSITION_COLUMNS = [
    "Ticker",
    "Shares",
    "Avg Cost",
    "Current Price",
    "Unrealized P&L",
    "Exit Flag",
]

HISTORY_COLUMNS = [
    "Executed At",
    "Ticker",
    "Side",
    "Shares",
    "Price",
    "Realized P&L",
    "Notes",
]


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _get_positions_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """Build open positions DataFrame."""
    try:
        positions = get_open_positions_display(conn)
        if not positions:
            return pd.DataFrame(columns=POSITION_COLUMNS)
        data = []
        for pos in positions:
            cp = pos.get("current_price")
            unr = pos.get("unrealized_pnl")
            data.append([
                pos["ticker"],
                int(pos["shares"]),
                round(pos["avg_cost"], 2),
                round(cp, 2) if cp is not None else None,
                round(unr, 2) if unr is not None else None,
                "EXIT" if pos.get("exit_flag") else "",
            ])
        return pd.DataFrame(data, columns=POSITION_COLUMNS)
    except Exception as exc:
        log.error("get_positions_df_failed", error=str(exc)[:200])
        return pd.DataFrame(columns=POSITION_COLUMNS)


def _get_history_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """Build trade history DataFrame."""
    try:
        trades = get_trade_history_display(conn)
        if not trades:
            return pd.DataFrame(columns=HISTORY_COLUMNS)
        data = []
        for trade in trades:
            realized = trade.get("realized_pnl")
            data.append([
                trade.get("executed_at", ""),
                trade.get("ticker", ""),
                trade.get("side", ""),
                int(trade.get("shares", 0)),
                round(trade.get("price", 0), 2),
                round(realized, 2) if realized is not None else "",
                trade.get("notes", ""),
            ])
        return pd.DataFrame(data, columns=HISTORY_COLUMNS)
    except Exception as exc:
        log.error("get_history_df_failed", error=str(exc)[:200])
        return pd.DataFrame(columns=HISTORY_COLUMNS)


def _get_summary(conn: sqlite3.Connection) -> tuple[float, float, float, float, float]:
    """Return (cash, unrealized_pnl, realized_pnl, total_pnl, win_rate)."""
    try:
        s = get_portfolio_summary(conn)
        return (
            s.get("cash_balance", 0.0),
            s.get("unrealized_pnl", 0.0),
            s.get("realized_pnl", 0.0),
            s.get("total_pnl", 0.0),
            s.get("win_rate", 0.0),
        )
    except Exception as exc:
        log.error("get_summary_failed", error=str(exc)[:200])
        return (0.0, 0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Tab builder
# ---------------------------------------------------------------------------

def build_paper_trading_tab(conn: sqlite3.Connection, config: AppConfig) -> None:
    """Build the comprehensive Paper Trading tab inside the current gr.Blocks context.

    Args:
        conn: SQLite connection with check_same_thread=False.
        config: AppConfig with polygon_api_key.
    """

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def lookup_callback(ticker: str, chart_period: str = "6M"):
        """Look up a ticker: fetch prev close, company info, and draw chart.

        Outputs:
            company_info_display, price_display, chart_plot,
            ticker_state, price_state, trade_status
        """
        if not ticker or not ticker.strip():
            return ("", "Enter a ticker above and click Lookup.", None, "", 0.0, "")

        ticker = ticker.strip().upper()

        # Company info from Polygon reference endpoint (free tier)
        info = fetch_ticker_info(ticker, config.polygon_api_key)
        info_str = (
            f"{info['name']}  |  {info['exchange']}  "
            f"|  {info['sector']}  |  Market Cap: {info['market_cap_str']}"
        )

        # Price: prev close from Polygon, fall back to last known SQLite close
        price = fetch_prev_close(ticker, config.polygon_api_key)
        price_note = ""
        if price is None:
            price = get_last_known_price(conn, ticker)
            price_note = " (last known close)"

        if price is None or price <= 0:
            price_str = "Price unavailable"
            price = 0.0
        else:
            price_str = f"${price:.2f}{price_note}"

        # Chart from normalized_bars using selected period
        days = period_to_days(chart_period)
        df = get_price_history(conn, ticker, days=days)
        chart_fig = None
        if not df.empty:
            df = compute_indicators(df)
            chart_fig = build_chart(df, ticker)

        trade_status = (
            f"Loaded: {ticker} @ {price_str}" if price > 0
            else f"Loaded: {ticker} (no price available — set capital and ingest data)"
        )

        return (info_str, price_str, chart_fig, ticker, float(price), trade_status)

    def chart_period_callback(ticker: str, chart_period: str):
        """Redraw the stock chart immediately when the period radio changes.

        Outputs: chart_plot
        """
        if not ticker or not ticker.strip():
            return None
        days = period_to_days(chart_period)
        df = get_price_history(conn, ticker.strip().upper(), days=days)
        if df.empty:
            return None
        df = compute_indicators(df)
        return build_chart(df, ticker.strip().upper())

    def buy_callback(ticker_state: str, price_state: float, shares: float):
        """Execute a buy order using the looked-up ticker and price.

        Outputs:
            trade_status, positions_table,
            cash, unrealized, realized, total_pnl, winrate,
            history_table
        """
        def _err(msg):
            return (msg, _get_positions_df(conn), *_get_summary(conn), _get_history_df(conn))

        if not ticker_state:
            return _err("Error: Look up a ticker first, then click Buy.")
        if price_state <= 0:
            return _err(f"Error: No valid price loaded for {ticker_state}.")

        shares_int = int(shares) if shares else 0
        if shares_int <= 0:
            return _err("Error: Shares must be greater than 0.")

        try:
            now_utc = datetime.now(timezone.utc).isoformat()
            open_or_add_position(
                conn,
                portfolio_id=1,
                ticker=ticker_state,
                shares=shares_int,
                price=price_state,
                source_signal_id=None,
                invalidation_threshold=None,
                executed_at=now_utc,
            )
            status = (
                f"Bought {shares_int} shares of {ticker_state}"
                f" at ${price_state:.2f}"
            )
            return (status, _get_positions_df(conn), *_get_summary(conn), _get_history_df(conn))
        except Exception as exc:
            log.error("buy_callback_failed", error=str(exc)[:200])
            return _err(f"Error: {exc}")

    def sell_callback(ticker_state: str, price_state: float, shares: float):
        """Execute a sell order using the looked-up ticker and price.

        Outputs:
            trade_status, positions_table,
            cash, unrealized, realized, total_pnl, winrate,
            history_table
        """
        def _err(msg):
            return (msg, _get_positions_df(conn), *_get_summary(conn), _get_history_df(conn))

        if not ticker_state:
            return _err("Error: Look up a ticker first, then click Sell.")
        if price_state <= 0:
            return _err(f"Error: No valid price loaded for {ticker_state}.")

        shares_int = int(shares) if shares else 0
        if shares_int <= 0:
            return _err("Error: Shares must be greater than 0.")

        try:
            now_utc = datetime.now(timezone.utc).isoformat()
            realized_pnl = close_position(
                conn,
                portfolio_id=1,
                ticker=ticker_state,
                shares_to_close=shares_int,
                close_price=price_state,
                executed_at=now_utc,
                notes="manual",
            )
            status = (
                f"Sold {shares_int} shares of {ticker_state}"
                f" at ${price_state:.2f}."
                f" Realized P&L: ${realized_pnl:.2f}"
            )
            return (status, _get_positions_df(conn), *_get_summary(conn), _get_history_df(conn))
        except ValueError as exc:
            return _err(f"Error: {exc}")
        except Exception as exc:
            log.error("sell_callback_failed", error=str(exc)[:200])
            return _err(f"Error: {exc}")

    def set_capital_callback(amount: float):
        """Set or reset starting capital.

        Outputs: capital_status, cash, unrealized, realized, total_pnl, winrate
        """
        try:
            if amount < 1000:
                return ("Error: Minimum starting capital is $1,000.", *_get_summary(conn))
            set_capital(conn, float(amount))
            cash, unr, real, total, wr = _get_summary(conn)
            return (f"Capital set to ${amount:,.2f}", cash, unr, real, total, wr)
        except Exception as exc:
            log.error("set_capital_failed", error=str(exc)[:200])
            return (f"Error: {exc}", *_get_summary(conn))

    def refresh_callback(portfolio_period: str = "6M"):
        """Refresh positions, portfolio summary, performance table, and chart from DB.

        Prices are kept current by the BackgroundPricePoller daemon; this
        callback is a pure DB read — no Polygon API calls made here.

        Outputs:
            positions_table, cash, unrealized, realized, total_pnl, winrate,
            performance_table, portfolio_chart, market_status
        """
        hist_df = get_portfolio_value_history(conn, lookback_days=period_to_days(portfolio_period))
        portfolio_fig = build_portfolio_value_chart(hist_df)
        perf_df = get_performance_table(conn)
        status_label = get_market_status_label(conn)

        return (_get_positions_df(conn), *_get_summary(conn), perf_df, portfolio_fig, status_label)

    def portfolio_period_callback(portfolio_period: str):
        """Immediately redraw the portfolio P&L chart when the period radio changes.

        Outputs: portfolio_chart
        """
        hist_df = get_portfolio_value_history(conn, lookback_days=period_to_days(portfolio_period))
        return build_portfolio_value_chart(hist_df)

    def refresh_signals_callback():
        """Reload algorithm signal suggestions."""
        return get_signal_suggestions(conn)

    def load_correlation_chart_callback(leader_ticker: str, corr_period: str):
        """Build the correlation chart for a selected leader.

        Plots all active pairs registered with this leader — no portfolio
        ownership check. Useful for pre-trade analysis on any tracked pair.

        Outputs: (correlation_chart, correlation_status)
        """
        if not leader_ticker or not leader_ticker.strip():
            return None, "Enter a leader ticker and click Load."

        leader = leader_ticker.strip().upper()

        # Pairs where this ticker is the leader
        pair_rows = conn.execute(
            "SELECT follower FROM ticker_pairs WHERE leader = ? AND is_active = 1",
            (leader,),
        ).fetchall()
        pair_followers = {row[0] for row in pair_rows}

        if not pair_followers:
            return None, f"No active pairs found with {leader} as leader."

        followers = sorted(pair_followers)
        status = f"Leader: {leader}  |  Tracked pairs: {', '.join(followers)}"

        fig = build_correlation_chart(conn, leader, followers, days=period_to_days(corr_period))
        if fig is None:
            return None, f"No price data found for {leader} or its followers."

        return fig, status

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    with gr.Tab("Paper Trading"):
        gr.Markdown("## Paper Trading Dashboard")

        # Persistent state for current lookup
        ticker_state = gr.State(value="")
        price_state = gr.State(value=0.0)

        # Hidden timer — fires every 30 s; reads fresh prices written by the
        # BackgroundPricePoller daemon (no Polygon API calls from this timer).
        price_timer = gr.Timer(value=30, active=True)

        # ══════════════════════════════════════════════════════════════
        # SECTION 1 — PAIR RESEARCH
        # ══════════════════════════════════════════════════════════════
        gr.Markdown("### 1. Pair Research")
        gr.Markdown(
            "Compare all registered pairs against a leader to visualise relative "
            "performance. Useful before deciding which stock to trade."
        )
        with gr.Row():
            corr_leader_input = gr.Textbox(
                label="Leader Ticker",
                placeholder="e.g. NVDA",
                max_lines=1,
                scale=3,
            )
            corr_period_radio = gr.Radio(
                label="Period",
                choices=["1D", "1W", "1M", "3M", "6M", "1Y", "YTD", "5Y"],
                value="6M",
                scale=3,
            )
            load_corr_btn = gr.Button("Load Chart", variant="primary", scale=1)

        correlation_status = gr.Textbox(
            label="", value="", interactive=False, lines=1,
        )
        correlation_chart = gr.Plot(label="Pair Correlation Chart", value=None)

        gr.Markdown("---")

        # ══════════════════════════════════════════════════════════════
        # SECTION 2 — STOCK ANALYSIS & TRADE EXECUTION
        # ══════════════════════════════════════════════════════════════
        gr.Markdown("### 2. Stock Analysis & Trade Execution")
        gr.Markdown(
            "Look up a ticker to load its price, chart, and company details. "
            "Algorithm signals are shown alongside so you can act on them immediately."
        )

        # ── Stock Lookup ───────────────────────────────────────────────
        with gr.Row():
            ticker_input = gr.Textbox(
                label="Ticker Symbol",
                placeholder="e.g. NVDA",
                max_lines=1,
                scale=5,
            )
            lookup_btn = gr.Button("Lookup", variant="primary", scale=1)

        with gr.Row():
            company_info_display = gr.Textbox(
                label="Company Info",
                value="",
                interactive=False,
                lines=1,
                scale=4,
            )
            price_display = gr.Textbox(
                label="Prev Close Price",
                value="",
                interactive=False,
                lines=1,
                scale=1,
            )

        # ── Chart period toggle ────────────────────────────────────────
        chart_period_radio = gr.Radio(
            label="Chart Period",
            choices=["1D", "1W", "1M", "3M", "6M", "1Y", "YTD", "5Y"],
            value="6M",
        )

        # ── Chart (left) + Algorithm Signals (right) side by side ─────
        with gr.Row():
            with gr.Column(scale=3):
                chart_plot = gr.Plot(label="Price Chart (MA20, MA50 · RSI · MACD)", value=None)

            with gr.Column(scale=2):
                gr.Markdown("#### Algorithm Signal Suggestions")
                gr.Markdown(
                    "Signals from the lead-lag engine. "
                    "Look up the **Follower** ticker to act on a signal."
                )
                refresh_signals_btn = gr.Button("Refresh Signals", variant="secondary")
                signals_table = gr.Dataframe(
                    value=lambda: get_signal_suggestions(conn),
                    headers=SIGNAL_COLUMNS,
                    label="Recent Signals (last 30 days)",
                    interactive=False,
                )

        # ── Place Order ────────────────────────────────────────────────
        gr.Markdown("#### Place Order")
        gr.Markdown(
            "Uses the price loaded above. Look up a ticker first, then set shares and buy or sell."
        )
        with gr.Row():
            shares_input = gr.Number(
                label="Shares",
                value=1,
                minimum=1,
                step=1,
                precision=0,
                scale=3,
            )
            buy_btn = gr.Button("Buy", variant="primary", scale=1)
            sell_btn = gr.Button("Sell", variant="stop", scale=1)

        trade_status = gr.Textbox(label="Order Status", value="", interactive=False)

        gr.Markdown("---")

        # ══════════════════════════════════════════════════════════════
        # SECTION 3 — ACTIVE POSITIONS
        # ══════════════════════════════════════════════════════════════
        gr.Markdown("### 3. Active Positions")
        gr.Markdown(
            "Prices update automatically every 5 minutes. "
            "When the market is closed, the most recent closing price from your "
            "ingested data is shown and held until the market reopens. "
            "Click **Refresh** to update immediately."
        )
        with gr.Row():
            refresh_btn = gr.Button("Refresh Positions & Portfolio", variant="secondary", scale=3)
            market_status_display = gr.Textbox(
                label="Market Status",
                value=lambda: get_market_status_label(conn),
                interactive=False,
                lines=1,
                scale=5,
            )

        positions_table = gr.Dataframe(
            value=lambda: _get_positions_df(conn),
            headers=POSITION_COLUMNS,
            label="Open Positions",
            interactive=False,
        )

        gr.Markdown("---")

        # ══════════════════════════════════════════════════════════════
        # SECTION 4 — PORTFOLIO SUMMARY
        # ══════════════════════════════════════════════════════════════
        gr.Markdown("### 4. Portfolio Summary")
        gr.Markdown(
            "Live overview of capital, P&L, and per-position performance. "
            "Updates on every Refresh."
        )

        # Key metrics row
        with gr.Row():
            cash_display = gr.Number(
                label="Cash Balance ($)", value=0.0,
                interactive=False, precision=2,
            )
            unrealized_display = gr.Number(
                label="Unrealized P&L ($)", value=0.0,
                interactive=False, precision=2,
            )
            realized_display = gr.Number(
                label="Realized P&L ($)", value=0.0,
                interactive=False, precision=2,
            )
            total_pnl_display = gr.Number(
                label="Total P&L ($)", value=0.0,
                interactive=False, precision=2,
            )
            winrate_display = gr.Number(
                label="Win Rate (%)", value=0.0,
                interactive=False, precision=1,
            )

        # Per-position returns table
        performance_table = gr.Dataframe(
            value=lambda: get_performance_table(conn),
            headers=PERFORMANCE_COLUMNS,
            label="Position Performance — Total & Daily Returns",
            interactive=False,
        )

        # Portfolio P&L period toggle
        portfolio_period_radio = gr.Radio(
            label="P&L Chart Period",
            choices=["1D", "1W", "1M", "3M", "6M", "1Y", "YTD", "5Y"],
            value="6M",
        )

        # Portfolio P&L chart
        portfolio_chart = gr.Plot(label="Trading P&L Over Time", value=None)

        gr.Markdown(
            "> **Note:** This chart shows combined realized and unrealized P&L from "
            "stock trades only — idle cash is excluded. "
            "The **0 line** is break-even. "
            "**Green** = net profit from stock activity. **Red** = net loss. "
            "All historical buys and sells are reflected."
        )

        # Reset Capital (collapsible — keep out of the way)
        with gr.Accordion("Reset Capital", open=False):
            gr.Markdown(
                "Set a new starting capital to reset the portfolio. "
                "This wipes all positions and trade history."
            )
            with gr.Row():
                capital_input = gr.Number(
                    label="Starting Capital ($)",
                    value=100000,
                    minimum=1000,
                    step=1000,
                    scale=4,
                )
                set_capital_btn = gr.Button("Set Capital", variant="secondary", scale=1)
            capital_status = gr.Textbox(label="Status", value="", interactive=False)

        gr.Markdown("---")

        # ══════════════════════════════════════════════════════════════
        # SECTION 5 — TRADE HISTORY
        # ══════════════════════════════════════════════════════════════
        gr.Markdown("### 5. Trade History")
        gr.Markdown("Full log of every buy and sell executed in this portfolio.")
        history_table = gr.Dataframe(
            value=lambda: _get_history_df(conn),
            headers=HISTORY_COLUMNS,
            label="Trade History",
            interactive=False,
        )

        # ------------------------------------------------------------------
        # Event wiring
        # ------------------------------------------------------------------

        lookup_btn.click(
            fn=lookup_callback,
            inputs=[ticker_input, chart_period_radio],
            outputs=[
                company_info_display,
                price_display,
                chart_plot,
                ticker_state,
                price_state,
                trade_status,
            ],
        )

        chart_period_radio.change(
            fn=chart_period_callback,
            inputs=[ticker_state, chart_period_radio],
            outputs=[chart_plot],
        )

        buy_btn.click(
            fn=buy_callback,
            inputs=[ticker_state, price_state, shares_input],
            outputs=[
                trade_status,
                positions_table,
                cash_display,
                unrealized_display,
                realized_display,
                total_pnl_display,
                winrate_display,
                history_table,
            ],
        )

        sell_btn.click(
            fn=sell_callback,
            inputs=[ticker_state, price_state, shares_input],
            outputs=[
                trade_status,
                positions_table,
                cash_display,
                unrealized_display,
                realized_display,
                total_pnl_display,
                winrate_display,
                history_table,
            ],
        )

        set_capital_btn.click(
            fn=set_capital_callback,
            inputs=[capital_input],
            outputs=[
                capital_status,
                cash_display,
                unrealized_display,
                realized_display,
                total_pnl_display,
                winrate_display,
            ],
        )

        refresh_btn.click(
            fn=refresh_callback,
            inputs=[portfolio_period_radio],
            outputs=[
                positions_table,
                cash_display,
                unrealized_display,
                realized_display,
                total_pnl_display,
                winrate_display,
                performance_table,
                portfolio_chart,
                market_status_display,
            ],
        )

        price_timer.tick(
            fn=refresh_callback,
            inputs=[portfolio_period_radio],
            outputs=[
                positions_table,
                cash_display,
                unrealized_display,
                realized_display,
                total_pnl_display,
                winrate_display,
                performance_table,
                portfolio_chart,
                market_status_display,
            ],
        )
        price_timer.tick(
            fn=refresh_signals_callback,
            outputs=[signals_table],
        )

        portfolio_period_radio.change(
            fn=portfolio_period_callback,
            inputs=[portfolio_period_radio],
            outputs=[portfolio_chart],
        )

        refresh_signals_btn.click(
            fn=refresh_signals_callback,
            outputs=[signals_table],
        )

        load_corr_btn.click(
            fn=load_correlation_chart_callback,
            inputs=[corr_leader_input, corr_period_radio],
            outputs=[correlation_chart, correlation_status],
        )
