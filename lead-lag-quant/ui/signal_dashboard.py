"""Signal Dashboard tab for Gradio UI (UI-01).

Displays active signals from the last 7 days with execution status
and provides an auto-execute toggle for opening paper positions.
"""

import sqlite3

import gradio as gr
import pandas as pd

from features.pipeline import compute_features_all_pairs
from leadlag_engine.pipeline import run_engine_for_all_pairs
from paper_trading.engine import auto_execute_signals
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
    "Warning",
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
                s.data_warning,
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
                row_dict["data_warning"] or "",
                row_dict["generated_at"],
                row_dict["executed"],
            ])

        return pd.DataFrame(data, columns=SIGNAL_COLUMNS)

    except Exception as exc:
        log.error("get_active_signals_failed", error=str(exc)[:200])
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

    def run_analysis_callback() -> tuple[str, pd.DataFrame]:
        """Run Phase 3 + Phase 4 pipeline to generate signals.

        Returns:
            Tuple of (log string, refreshed signals table).
        """
        try:
            log_lines = ["Running feature engineering..."]
            feat_results = compute_features_all_pairs(conn)
            pairs_done = len(feat_results.get("pairs", {}))
            tickers_done = len(feat_results.get("tickers", {}))
            log_lines.append(f"  Features computed: {pairs_done} pair(s), {tickers_done} ticker(s)")

            log_lines.append("\nRunning lead-lag engine...")
            result = run_engine_for_all_pairs(conn)
            signals = result.get("signals", [])
            summaries = result.get("pair_summaries", [])

            log_lines.append(f"  Pairs analyzed: {len(summaries)}")
            for s in summaries:
                icon = {"signal": "[SIGNAL]", "gated": "[gated]", "skipped": "[skipped]"}.get(s["outcome"], "")
                line = f"  {icon} {s['ticker_a']}/{s['ticker_b']}: {s['reason']}"
                if s.get("data_warning"):
                    line += f"  !! {s['data_warning']}"
                log_lines.append(line)

            log_lines.append(f"\nSignals generated: {len(signals)}")
            log_lines.append("Analysis complete.")
            return "\n".join(log_lines), _get_active_signals_dataframe(conn)
        except Exception as exc:
            log.error("run_analysis_failed", error=str(exc)[:200])
            return f"Error running analysis: {exc}", _get_active_signals_dataframe(conn)

    def refresh_signals_callback() -> pd.DataFrame:
        """Reload the signals table."""
        return _get_active_signals_dataframe(conn)

    def execute_signals_callback() -> tuple[str, pd.DataFrame]:
        """Execute all unprocessed signals into paper positions.

        Returns:
            Tuple of (status message, refreshed signals table).
        """
        try:
            results = auto_execute_signals(conn, config.polygon_api_key)
            if not results:
                status = "No unprocessed signals to execute. Run Analysis first, or signals may already be executed."
            else:
                tickers = ", ".join(r["ticker"] for r in results)
                status = f"Executed {len(results)} signal(s). Tickers: {tickers}"
        except ValueError as exc:
            status = f"Error: {exc}"
        except Exception as exc:
            log.error("execute_signals_failed", error=str(exc)[:200])
            status = f"Error executing signals: {exc}"

        return status, _get_active_signals_dataframe(conn)

    with gr.Tab("Signal Dashboard"):
        gr.Markdown("## Signal Dashboard")

        with gr.Row():
            run_analysis_btn = gr.Button("Run Analysis", variant="primary")
            execute_btn = gr.Button("Execute New Signals", variant="secondary")
            refresh_signals_btn = gr.Button("Refresh")

        analysis_log = gr.Textbox(
            label="Analysis Log",
            value="",
            lines=6,
            interactive=False,
        )

        signals_table = gr.Dataframe(
            value=refresh_signals_callback,
            headers=SIGNAL_COLUMNS,
            interactive=False,
            label="Active Signals (last 7 days)",
        )

        status_msg = gr.Textbox(label="Status", value="", interactive=False)

        # Auto-refresh signals every 60 seconds
        signal_timer = gr.Timer(value=60, active=True)
        signal_timer.tick(fn=refresh_signals_callback, outputs=[signals_table])

        # Event wiring
        run_analysis_btn.click(
            fn=run_analysis_callback,
            outputs=[analysis_log, signals_table],
        )
        execute_btn.click(
            fn=execute_signals_callback,
            outputs=[status_msg, signals_table],
        )
        refresh_signals_btn.click(
            fn=refresh_signals_callback,
            outputs=[signals_table],
        )
