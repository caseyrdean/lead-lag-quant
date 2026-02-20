"""Gradio tab builder for the Performance Analytics dashboard.

All data sourced from SQLite — no API calls made here.
"""

import sqlite3

import gradio as gr

from paper_trading.analytics import (
    build_equity_drawdown_chart,
    build_monthly_heatmap_chart,
    build_pnl_distribution_chart,
    build_ticker_pnl_chart,
    get_risk_metrics,
    get_ticker_breakdown,
    get_trade_stats,
    TICKER_BREAKDOWN_COLUMNS,
)


def build_analytics_tab(conn: sqlite3.Connection, scheduler=None) -> None:
    """Build and wire the Analytics tab inside an existing gr.Blocks context."""

    with gr.Tab("Analytics"):
        gr.Markdown("## Performance Analytics")
        refresh_btn = gr.Button("Refresh Analytics", variant="primary")

        # ----------------------------------------------------------------
        # Trade Statistics
        # ----------------------------------------------------------------
        gr.Markdown("### Trade Statistics")
        with gr.Row():
            total_closed = gr.Number(label="Total Closed", value=0, interactive=False)
            wins_num = gr.Number(label="Wins", value=0, interactive=False)
            losses_num = gr.Number(label="Losses", value=0, interactive=False)
            win_rate_num = gr.Number(label="Win Rate (%)", value=0, interactive=False)
        with gr.Row():
            profit_factor_num = gr.Number(label="Profit Factor", value=0, interactive=False)
            payoff_ratio_num = gr.Number(label="Payoff Ratio", value=0, interactive=False)
            expectancy_num = gr.Number(label="Expectancy ($)", value=0, interactive=False)
            total_pnl_num = gr.Number(label="Total Realized P&L ($)", value=0, interactive=False)
        with gr.Row():
            best_trade_num = gr.Number(label="Best Trade ($)", value=0, interactive=False)
            worst_trade_num = gr.Number(label="Worst Trade ($)", value=0, interactive=False)
            avg_trade_num = gr.Number(label="Avg Trade P&L ($)", value=0, interactive=False)

        # ----------------------------------------------------------------
        # Risk Metrics
        # ----------------------------------------------------------------
        gr.Markdown("### Risk Metrics")
        with gr.Row():
            sharpe_num = gr.Number(label="Sharpe Ratio (Ann.)", value=0, interactive=False)
            max_dd_dollar_num = gr.Number(label="Max Drawdown ($)", value=0, interactive=False)
            max_dd_pct_num = gr.Number(label="Max Drawdown (%)", value=0, interactive=False)
            calmar_num = gr.Number(label="Calmar Ratio", value=0, interactive=False)
            recovery_num = gr.Number(label="Recovery Factor", value=0, interactive=False)

        # ----------------------------------------------------------------
        # Equity Curve & Drawdown
        # ----------------------------------------------------------------
        gr.Markdown("### Equity Curve & Drawdown")
        period_radio = gr.Radio(
            choices=["1D", "1W", "1M", "3M", "6M", "1Y", "YTD", "5Y"],
            value="6M",
            label="Period",
        )
        equity_chart = gr.Plot(label="Equity Curve & Drawdown")

        # ----------------------------------------------------------------
        # Trade Analytics (side by side)
        # ----------------------------------------------------------------
        gr.Markdown("### Trade Analytics")
        with gr.Row():
            with gr.Column(scale=1):
                trade_dist_chart = gr.Plot(label="P&L Distribution")
            with gr.Column(scale=1):
                ticker_bar_chart = gr.Plot(label="P&L by Ticker")

        # ----------------------------------------------------------------
        # Monthly P&L Heatmap
        # ----------------------------------------------------------------
        gr.Markdown("### Monthly P&L Heatmap")
        monthly_heatmap_chart = gr.Plot(label="Monthly Heatmap")

        # ----------------------------------------------------------------
        # Per-Ticker Breakdown
        # ----------------------------------------------------------------
        gr.Markdown("### Per-Ticker Breakdown")
        ticker_breakdown_table = gr.Dataframe(
            headers=TICKER_BREAKDOWN_COLUMNS,
            interactive=False,
            label="Ticker Breakdown",
        )

        # ----------------------------------------------------------------
        # Callbacks
        # ----------------------------------------------------------------

        def refresh_all(period: str):
            stats = get_trade_stats(conn)
            risk = get_risk_metrics(conn)
            return (
                stats["total_closed"],
                stats["winning"],
                stats["losing"],
                stats["win_rate"],
                stats["profit_factor"],
                stats["payoff_ratio"],
                stats["expectancy"],
                stats["total_realized_pnl"],
                stats["best_trade"],
                stats["worst_trade"],
                stats["avg_trade"],
                risk["sharpe_ratio"],
                risk["max_drawdown_dollar"],
                risk["max_drawdown_pct"],
                risk["calmar_ratio"],
                risk["recovery_factor"],
                build_equity_drawdown_chart(conn, period=period),
                build_pnl_distribution_chart(conn),
                build_ticker_pnl_chart(conn),
                build_monthly_heatmap_chart(conn),
                get_ticker_breakdown(conn),
            )

        def equity_period_change(period: str):
            return build_equity_drawdown_chart(conn, period=period)

        all_outputs = [
            total_closed,
            wins_num,
            losses_num,
            win_rate_num,
            profit_factor_num,
            payoff_ratio_num,
            expectancy_num,
            total_pnl_num,
            best_trade_num,
            worst_trade_num,
            avg_trade_num,
            sharpe_num,
            max_dd_dollar_num,
            max_dd_pct_num,
            calmar_num,
            recovery_num,
            equity_chart,
            trade_dist_chart,
            ticker_bar_chart,
            monthly_heatmap_chart,
            ticker_breakdown_table,
        ]

        # Auto-refresh all metrics every 5 minutes
        analytics_timer = gr.Timer(value=300, active=True)
        analytics_timer.tick(fn=refresh_all, inputs=[period_radio], outputs=all_outputs)

        refresh_btn.click(fn=refresh_all, inputs=[period_radio], outputs=all_outputs)
        period_radio.change(
            fn=equity_period_change,
            inputs=[period_radio],
            outputs=[equity_chart],
        )
