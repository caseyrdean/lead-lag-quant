"""Signal Dashboard tab for Gradio UI (UI-01).

Displays active signals from the last 7 days with execution status
and provides an auto-execute toggle for opening paper positions.
"""

import sqlite3

import gradio as gr
import pandas as pd

from paper_trading.engine import auto_execute_signals, get_open_positions_display
from paper_trading.db import get_unprocessed_signals
from utils.config import AppConfig
from utils.logging import get_logger

log = get_logger("ui.signal_dashboard")

# Column names for the signals DataFrame
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
    "Generated At",
    "Executed",
]


def _get_active_signals_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """Query signals from the last 7 days and mark execution status.

    For each signal, checks whether a buy trade exists in paper_trades
    for that signal_id to populate the 'Executed' column.

    Returns:
        DataFrame with signal details and execution status.
    """
    try:
        rows = conn.execute(
            """
            SELECT
                s.rowid AS signal_id,
                s.ticker_a,
                s.ticker_b,
                s.signal_date,
                s.direction,
                s.sizing_tier,
                s.stability_score,
                s.correlation_strength,
                s.expected_target,
                s.invalidation_threshold,
                s.generated_at,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM paper_trades pt
                        WHERE pt.source_signal_id = s.rowid
                          AND pt.side = 'buy'
                    ) THEN 'Yes'
                    ELSE 'No'
                END AS executed
            FROM signals s
            WHERE s.signal_date >= date('now', '-7 days')
            ORDER BY s.generated_at DESC
            """
        ).fetchall()

        if not rows:
            return pd.DataFrame(columns=SIGNAL_COLUMNS)

        data = []
        for row in rows:
            row_dict = dict(row)
            data.append([
                row_dict["signal_date"],
                row_dict["ticker_a"],
                row_dict["ticker_b"],
                row_dict["direction"],
                row_dict["sizing_tier"],
                round(row_dict["stability_score"], 3) if row_dict["stability_score"] is not None else None,
                round(row_dict["correlation_strength"], 3) if row_dict["correlation_strength"] is not None else None,
                round(row_dict["expected_target"], 4) if row_dict["expected_target"] is not None else None,
                round(row_dict["invalidation_threshold"], 4) if row_dict["invalidation_threshold"] is not None else None,
                row_dict["generated_at"],
                row_dict["executed"],
            ])

        return pd.DataFrame(data, columns=SIGNAL_COLUMNS)

    except Exception:
        log.exception("get_active_signals_failed")
        return pd.DataFrame(columns=SIGNAL_COLUMNS)


def build_signal_dashboard_tab(conn: sqlite3.Connection, config: AppConfig) -> None:
    """Build the Signal Dashboard tab inside the current gr.Blocks context.

    Creates a gr.Tab with:
    - Auto-execute toggle checkbox
    - Active signals table (last 7 days)
    - Execute and Refresh buttons
    - Status message display

    Args:
        conn: SQLite connection with check_same_thread=False.
        config: AppConfig with polygon_api_key.
    """

    def refresh_signals_callback() -> pd.DataFrame:
        """Reload the signals table."""
        return _get_active_signals_dataframe(conn)

    def execute_signals_callback(
        auto_execute_enabled: bool,
    ) -> tuple[str, pd.DataFrame]:
        """Execute unprocessed signals if auto-execute is enabled.

        Returns:
            Tuple of (status message, refreshed signals table).
        """
        if not auto_execute_enabled:
            return (
                "Auto-execute is OFF. Enable the toggle first.",
                _get_active_signals_dataframe(conn),
            )

        try:
            results = auto_execute_signals(conn, config.polygon_api_key)
            status = f"Executed {len(results)} signal(s)."
            if results:
                tickers = ", ".join(r["ticker"] for r in results)
                status += f" Tickers: {tickers}"
        except ValueError as exc:
            status = f"Error: {exc}"
        except Exception:
            log.exception("execute_signals_failed")
            status = "Error executing signals. Check logs for details."

        return status, _get_active_signals_dataframe(conn)

    with gr.Tab("Signal Dashboard"):
        gr.Markdown("## Signal Dashboard")

        with gr.Row():
            auto_execute_toggle = gr.Checkbox(
                label="Auto-Execute New Signals",
                value=False,
                info="When enabled, qualifying signals auto-open paper positions",
            )

        signals_table = gr.Dataframe(
            value=refresh_signals_callback,
            headers=SIGNAL_COLUMNS,
            interactive=False,
            label="Active Signals (last 7 days)",
        )

        with gr.Row():
            execute_btn = gr.Button("Execute New Signals", variant="primary")
            refresh_signals_btn = gr.Button("Refresh")

        status_msg = gr.Textbox(label="Status", interactive=False)

        # Event wiring
        execute_btn.click(
            fn=execute_signals_callback,
            inputs=[auto_execute_toggle],
            outputs=[status_msg, signals_table],
        )
        refresh_signals_btn.click(
            fn=refresh_signals_callback,
            outputs=[signals_table],
        )
