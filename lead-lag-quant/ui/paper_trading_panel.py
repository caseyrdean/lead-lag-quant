"""Paper Trading tab for Gradio UI (UI-04).

Provides capital setup, manual trade entry (buy/sell), open positions
with live 15-minute price refresh via gr.Timer, portfolio summary,
and trade history display.
"""

import sqlite3
from datetime import datetime, timezone

import gradio as gr
import pandas as pd

from paper_trading.engine import (
    set_capital,
    open_or_add_position,
    close_position,
    get_portfolio_summary,
    get_open_positions_display,
    get_trade_history_display,
    compute_share_quantity,
)
from paper_trading.price_poller import poll_and_update_prices, fetch_snapshot_price
from paper_trading.db import check_exit_flags
from utils.config import AppConfig
from utils.logging import get_logger

log = get_logger("ui.paper_trading_panel")

# Column definitions
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


def _get_positions_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """Convert open positions to a display DataFrame.

    Formats prices to 2 decimal places and exit flags as 'EXIT' or empty string.

    Returns:
        DataFrame with position details.
    """
    try:
        positions = get_open_positions_display(conn)
        if not positions:
            return pd.DataFrame(columns=POSITION_COLUMNS)

        data = []
        for pos in positions:
            current_price = pos.get("current_price")
            unrealized = pos.get("unrealized_pnl")
            data.append([
                pos["ticker"],
                int(pos["shares"]),
                round(pos["avg_cost"], 2),
                round(current_price, 2) if current_price is not None else None,
                round(unrealized, 2) if unrealized is not None else None,
                "EXIT" if pos.get("exit_flag") else "",
            ])

        return pd.DataFrame(data, columns=POSITION_COLUMNS)

    except Exception:
        log.exception("get_positions_dataframe_failed")
        return pd.DataFrame(columns=POSITION_COLUMNS)


def _get_history_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """Convert trade history to a display DataFrame.

    Returns:
        DataFrame with trade history details.
    """
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

    except Exception:
        log.exception("get_history_dataframe_failed")
        return pd.DataFrame(columns=HISTORY_COLUMNS)


def _get_summary_values(conn: sqlite3.Connection) -> tuple[float, float, float]:
    """Get portfolio summary values.

    Returns:
        Tuple of (cash_balance, total_pnl, win_rate).
    """
    try:
        summary = get_portfolio_summary(conn)
        return (
            summary.get("cash_balance", 0.0),
            summary.get("total_pnl", 0.0),
            summary.get("win_rate", 0.0),
        )
    except Exception:
        log.exception("get_summary_values_failed")
        return (0.0, 0.0, 0.0)


def build_paper_trading_tab(conn: sqlite3.Connection, config: AppConfig) -> None:
    """Build the Paper Trading tab inside the current gr.Blocks context.

    Creates a gr.Tab with:
    - Capital setup (starting capital input + set button)
    - Portfolio summary (cash, P&L, win rate)
    - Open positions table with 15-min auto-refresh via gr.Timer
    - Manual trade entry (ticker, shares, buy/sell buttons)
    - Trade history table

    Args:
        conn: SQLite connection with check_same_thread=False.
        config: AppConfig with polygon_api_key.
    """

    # --- Callback functions (closures over conn and config) ---

    def set_capital_callback(
        amount: float,
    ) -> tuple[str, float, float, float]:
        """Set starting capital and return updated summary.

        Returns:
            Tuple of (status_msg, cash_balance, total_pnl, win_rate).
        """
        try:
            if amount < 1000:
                return "Error: Minimum starting capital is $1,000.", 0.0, 0.0, 0.0
            set_capital(conn, float(amount))
            cash, pnl, wr = _get_summary_values(conn)
            return f"Starting capital set to ${amount:,.2f}", cash, pnl, wr
        except Exception as exc:
            log.exception("set_capital_failed")
            return f"Error: {exc}", 0.0, 0.0, 0.0

    def buy_callback(
        ticker: str, shares: float,
    ) -> tuple[str, pd.DataFrame, float, float, float, pd.DataFrame]:
        """Execute a manual buy order.

        Returns:
            Tuple of (status, positions_table, cash, pnl, winrate, history_table).
        """
        try:
            if not ticker or not ticker.strip():
                return (
                    "Error: Ticker is required.",
                    _get_positions_dataframe(conn),
                    *_get_summary_values(conn),
                    _get_history_dataframe(conn),
                )

            ticker = ticker.strip().upper()
            shares_int = int(shares) if shares else 0

            if shares_int <= 0:
                return (
                    "Error: Shares must be greater than 0.",
                    _get_positions_dataframe(conn),
                    *_get_summary_values(conn),
                    _get_history_dataframe(conn),
                )

            # Fetch current price
            price = fetch_snapshot_price(ticker, config.polygon_api_key)
            if price is None:
                return (
                    f"Error: Could not fetch price for {ticker}. Check ticker or API key.",
                    _get_positions_dataframe(conn),
                    *_get_summary_values(conn),
                    _get_history_dataframe(conn),
                )

            now_utc = datetime.now(timezone.utc).isoformat()
            open_or_add_position(
                conn,
                portfolio_id=1,
                ticker=ticker,
                shares=shares_int,
                price=price,
                source_signal_id=None,
                invalidation_threshold=None,
                executed_at=now_utc,
            )

            status = f"Bought {shares_int} shares of {ticker} at ${price:.2f}"
            return (
                status,
                _get_positions_dataframe(conn),
                *_get_summary_values(conn),
                _get_history_dataframe(conn),
            )

        except Exception as exc:
            log.exception("buy_callback_failed")
            return (
                f"Error: {exc}",
                _get_positions_dataframe(conn),
                *_get_summary_values(conn),
                _get_history_dataframe(conn),
            )

    def sell_callback(
        ticker: str, shares: float,
    ) -> tuple[str, pd.DataFrame, float, float, float, pd.DataFrame]:
        """Execute a manual sell order.

        Returns:
            Tuple of (status, positions_table, cash, pnl, winrate, history_table).
        """
        try:
            if not ticker or not ticker.strip():
                return (
                    "Error: Ticker is required.",
                    _get_positions_dataframe(conn),
                    *_get_summary_values(conn),
                    _get_history_dataframe(conn),
                )

            ticker = ticker.strip().upper()
            shares_int = int(shares) if shares else 0

            if shares_int <= 0:
                return (
                    "Error: Shares must be greater than 0.",
                    _get_positions_dataframe(conn),
                    *_get_summary_values(conn),
                    _get_history_dataframe(conn),
                )

            # Fetch current price
            price = fetch_snapshot_price(ticker, config.polygon_api_key)
            if price is None:
                return (
                    f"Error: Could not fetch price for {ticker}. Check ticker or API key.",
                    _get_positions_dataframe(conn),
                    *_get_summary_values(conn),
                    _get_history_dataframe(conn),
                )

            now_utc = datetime.now(timezone.utc).isoformat()
            realized_pnl = close_position(
                conn,
                portfolio_id=1,
                ticker=ticker,
                shares_to_close=shares_int,
                close_price=price,
                executed_at=now_utc,
                notes="manual",
            )

            status = f"Sold {shares_int} shares of {ticker} at ${price:.2f}. Realized P&L: ${realized_pnl:.2f}"
            return (
                status,
                _get_positions_dataframe(conn),
                *_get_summary_values(conn),
                _get_history_dataframe(conn),
            )

        except ValueError as exc:
            return (
                f"Error: {exc}",
                _get_positions_dataframe(conn),
                *_get_summary_values(conn),
                _get_history_dataframe(conn),
            )
        except Exception as exc:
            log.exception("sell_callback_failed")
            return (
                f"Error: {exc}",
                _get_positions_dataframe(conn),
                *_get_summary_values(conn),
                _get_history_dataframe(conn),
            )

    def refresh_prices_callback() -> pd.DataFrame:
        """Poll for updated prices and return refreshed positions table.

        Connected to gr.Timer for 15-minute auto-refresh during market hours.
        """
        try:
            poll_and_update_prices(conn, config.polygon_api_key)
        except Exception:
            log.exception("refresh_prices_callback_failed")
        return _get_positions_dataframe(conn)

    def load_positions() -> pd.DataFrame:
        """Load positions on tab initialization."""
        return _get_positions_dataframe(conn)

    def load_history() -> pd.DataFrame:
        """Load trade history on tab initialization."""
        return _get_history_dataframe(conn)

    def load_summary() -> tuple[float, float, float]:
        """Load portfolio summary on tab initialization."""
        return _get_summary_values(conn)

    # --- Layout ---

    with gr.Tab("Paper Trading"):
        gr.Markdown("## Paper Trading")

        # Capital setup row (TRADE-01)
        with gr.Row():
            starting_capital_input = gr.Number(
                label="Starting Capital ($)",
                value=100000,
                minimum=1000,
                step=1000,
            )
            set_capital_btn = gr.Button("Set Capital", variant="secondary")

        # Portfolio summary row
        with gr.Row():
            cash_display = gr.Number(
                label="Cash Balance",
                interactive=False,
                precision=2,
            )
            pnl_display = gr.Number(
                label="Total P&L",
                interactive=False,
                precision=2,
            )
            winrate_display = gr.Number(
                label="Win Rate (%)",
                interactive=False,
                precision=1,
            )

        # Open positions with 15-min auto-refresh (TRADE-04, TRADE-05)
        price_timer = gr.Timer(value=900, active=True)
        positions_table = gr.Dataframe(
            value=load_positions,
            headers=POSITION_COLUMNS,
            label="Open Positions (prices refresh every 15 min during market hours)",
            interactive=False,
        )

        # Wire timer to refresh positions
        price_timer.tick(
            fn=refresh_prices_callback,
            outputs=[positions_table],
        )

        # Manual trade entry (TRADE-03)
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Manual Trade")
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
                trade_status = gr.Textbox(
                    label="Trade Status",
                    interactive=False,
                )

        # Trade history (TRADE-08)
        history_table = gr.Dataframe(
            value=load_history,
            headers=HISTORY_COLUMNS,
            label="Trade History",
            interactive=False,
        )

        # Event wiring
        set_capital_btn.click(
            fn=set_capital_callback,
            inputs=[starting_capital_input],
            outputs=[trade_status, cash_display, pnl_display, winrate_display],
        )
        buy_btn.click(
            fn=buy_callback,
            inputs=[ticker_input, shares_input],
            outputs=[
                trade_status,
                positions_table,
                cash_display,
                pnl_display,
                winrate_display,
                history_table,
            ],
        )
        sell_btn.click(
            fn=sell_callback,
            inputs=[ticker_input, shares_input],
            outputs=[
                trade_status,
                positions_table,
                cash_display,
                pnl_display,
                winrate_display,
                history_table,
            ],
        )
