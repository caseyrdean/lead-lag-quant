"""Gradio application for Lead-Lag Quant -- 5 tabs: Pair Management, Data Ingestion, Normalize, Signal Dashboard, Paper Trading."""

import sqlite3
from datetime import date

import gradio as gr

from ingestion_massive.ingestion import ingest_pair, ingest_ticker
from ingestion_massive.polygon_client import PolygonClient
from normalization.normalizer import normalize_all_pairs
from normalization.returns_calc import compute_returns_all_pairs
from ui.signal_dashboard import build_signal_dashboard_tab
from ui.paper_trading_panel import build_paper_trading_tab
from ui.analytics_panel import build_analytics_tab
from utils.config import AppConfig
from utils.db import get_connection, init_schema
from utils.pipeline_scheduler import PipelineScheduler


def create_app(config: AppConfig) -> gr.Blocks:
    """Build and return the Gradio Blocks application.

    Creates a PolygonClient and SQLite connection using config values,
    initialises the DB schema, and returns a fully wired gr.Blocks instance
    with queue enabled (required for gr.Progress).

    Args:
        config: AppConfig with polygon_api_key, db_path, and plan_tier.

    Returns:
        A configured gr.Blocks instance ready to launch.
    """
    client = PolygonClient(
        api_key=config.polygon_api_key,
        rate_limit_per_minute=config.rate_limit_per_minute,
    )
    conn = get_connection(config.db_path)
    init_schema(conn)

    scheduler = PipelineScheduler(conn, client, config)
    scheduler.start()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _load_pairs() -> list[list]:
        """Return all pairs from ticker_pairs as a list-of-lists for Dataframe."""
        rows = conn.execute(
            "SELECT id, leader, follower, created_at, is_active "
            "FROM ticker_pairs ORDER BY created_at DESC"
        ).fetchall()
        return [list(row) for row in rows]

    # ------------------------------------------------------------------
    # Tab 1 callbacks
    # ------------------------------------------------------------------

    def add_pairs_batch(leader: str, followers_raw: str):
        """Validate and persist one leader against multiple followers in a single action.

        Followers input is a comma-separated string (e.g. "AMD, CRWV, TSM").
        The leader is validated once via Polygon. Each follower is then validated
        and inserted individually, with per-follower status reported.

        Returns:
            Tuple of (status_log, updated_pair_table).
        """
        leader = leader.strip().upper()

        if not leader:
            return "Error: Leader ticker is required.", _load_pairs()

        if not followers_raw or not followers_raw.strip():
            return "Error: At least one Follower ticker is required.", _load_pairs()

        # Parse followers — split on commas, strip whitespace, uppercase, deduplicate
        raw_tokens = [t.strip().upper() for t in followers_raw.split(",")]
        followers = list(dict.fromkeys(t for t in raw_tokens if t))  # preserves order, dedupes

        if not followers:
            return "Error: No valid follower tickers found after parsing.", _load_pairs()

        # Validate leader once
        if client.get_ticker_details(leader) is None:
            return (
                f"Invalid leader: {leader} (not found or inactive on Polygon.io)",
                _load_pairs(),
            )

        log_lines = [f"Leader: {leader}  |  Followers to add: {', '.join(followers)}\n"]
        added = skipped = failed = 0

        for follower in followers:
            if follower == leader:
                log_lines.append(f"  SKIP  {follower} — same as leader")
                skipped += 1
                continue

            # Validate follower
            if client.get_ticker_details(follower) is None:
                log_lines.append(f"  FAIL  {follower} — not found or inactive on Polygon.io")
                failed += 1
                continue

            # Insert pair
            try:
                conn.execute(
                    "INSERT INTO ticker_pairs (leader, follower) VALUES (?, ?)",
                    (leader, follower),
                )
                conn.commit()
                log_lines.append(f"  OK    {leader}/{follower} added")
                added += 1
            except sqlite3.IntegrityError:
                log_lines.append(f"  SKIP  {leader}/{follower} already exists")
                skipped += 1

        log_lines.append(
            f"\nDone — {added} added, {skipped} skipped, {failed} failed."
        )
        return "\n".join(log_lines), _load_pairs()

    def refresh_pairs():
        """Reload and return the current pair table."""
        return _load_pairs()

    # ------------------------------------------------------------------
    # Tab 2 callbacks
    # ------------------------------------------------------------------

    def fetch_all_data(from_date: str, to_date: str, progress=gr.Progress()):
        """Trigger ingestion for all active pairs with progress feedback.

        Validates date inputs, queries active pairs, runs ingest_pair for
        each, and returns a human-readable log string.

        Args:
            from_date: Start date string in YYYY-MM-DD format.
            to_date: End date string in YYYY-MM-DD format.
            progress: Gradio progress tracker (injected automatically).

        Returns:
            Log string describing per-pair ingestion results.
        """
        # Validate date formats
        try:
            date.fromisoformat(from_date.strip())
            date.fromisoformat(to_date.strip())
        except ValueError:
            return "Error: Dates must be in YYYY-MM-DD format (e.g. 2025-01-01)."

        from_date = from_date.strip()
        to_date = to_date.strip()

        # Load active pairs
        pairs = conn.execute(
            "SELECT leader, follower FROM ticker_pairs WHERE is_active = 1"
        ).fetchall()

        if not pairs:
            return "No active pairs. Add pairs in the Pair Management tab first."

        # Collect unique tickers across ALL pairs (SPY always included per INGEST-10).
        # Fetching per-pair causes shared tickers (e.g. NVDA, SPY) to be re-fetched
        # once per pair they appear in, multiplying API calls and rate-limit wait time.
        unique_tickers: list[str] = []
        seen: set[str] = set()
        for row in pairs:
            for t in [row[0].upper(), row[1].upper(), "SPY"]:
                if t not in seen:
                    unique_tickers.append(t)
                    seen.add(t)

        total = len(unique_tickers)
        log_lines = [
            f"Starting ingestion for {len(pairs)} pair(s) [{from_date} -> {to_date}]",
            f"Unique tickers to fetch: {', '.join(unique_tickers)}\n",
        ]

        ticker_results = {}
        try:
            for i, ticker in enumerate(unique_tickers):
                progress((i / total), desc=f"Fetching {ticker} ({i+1}/{total})...")
                ticker_results[ticker] = ingest_ticker(
                    client, conn, ticker, from_date, to_date
                )
                counts = ticker_results[ticker]
                log_lines.append(
                    f"  {ticker}: aggs={counts['aggs']}, "
                    f"splits={counts['splits']}, dividends={counts['dividends']}"
                )
                progress(((i + 1) / total), desc=f"Fetching {ticker} ({i+1}/{total})...")

        except Exception as exc:
            log_lines.append(f"\nError during ingestion: {exc}")
            return "\n".join(log_lines)

        log_lines.append("\nAll tickers ingested successfully.")
        return "\n".join(log_lines)

    # ------------------------------------------------------------------
    # Tab 3 callbacks
    # ------------------------------------------------------------------

    def run_normalization(progress=gr.Progress()):
        """Run normalization + returns computation for all active pairs.

        Steps:
        1. Check for active pairs in SQLite.
        2. Run normalize_all_pairs (splits extraction, bar normalization, dividend storage).
        3. Run compute_returns_all_pairs (multi-period returns).
        4. Return human-readable log of counts.

        Returns:
            Log string describing normalization results per ticker.
        """
        pairs = conn.execute(
            "SELECT leader, follower FROM ticker_pairs WHERE is_active = 1"
        ).fetchall()

        if not pairs:
            return "No active pairs. Add pairs and fetch data first."

        log_lines = ["Starting normalization pipeline...\n"]
        progress(0.1, desc="Running normalization...")

        try:
            norm_results = normalize_all_pairs(conn)
            progress(0.6, desc="Computing returns...")
            returns_results = compute_returns_all_pairs(conn)
            progress(1.0, desc="Complete")

            log_lines.append("Normalization results:")
            for ticker, counts in sorted(norm_results.items()):
                log_lines.append(
                    f"  {ticker}: splits={counts['splits']}, "
                    f"bars={counts['bars']}, dividends={counts['dividends']}"
                )

            log_lines.append("\nReturns computation results:")
            for ticker, count in sorted(returns_results.items()):
                log_lines.append(f"  {ticker}: {count} return rows upserted")

            log_lines.append("\nNormalization complete.")
        except Exception as exc:
            log_lines.append(f"\nError during normalization: {exc}")

        return "\n".join(log_lines)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    with gr.Blocks(title="Lead-Lag Quant") as app:
        gr.Markdown("# Lead-Lag Quant")

        # --- Global pipeline status bar ---
        pipeline_status_display = gr.Textbox(
            label="Auto Data Pipeline",
            value=scheduler.get_status_label,
            interactive=False,
            lines=1,
        )
        status_timer = gr.Timer(value=30, active=True)
        status_timer.tick(fn=scheduler.get_status_label, outputs=[pipeline_status_display])

        with gr.Tab("Pair Management"):
            gr.Markdown("### Add Ticker Pairs")
            gr.Markdown(
                "Enter one **Leader** and one or more **Followers** (comma-separated). "
                "All pairs are validated against Polygon before being saved."
            )
            with gr.Row():
                leader_input = gr.Textbox(
                    label="Leader Ticker",
                    placeholder="e.g., NVDA",
                    scale=1,
                )
                followers_input = gr.Textbox(
                    label="Follower Tickers (comma-separated)",
                    placeholder="e.g., AMD, CRWV, TSM",
                    scale=3,
                )
            with gr.Row():
                add_pair_btn = gr.Button("Add Pairs", variant="primary")
                refresh_btn = gr.Button("Refresh")
            pair_status = gr.Textbox(
                label="Status",
                interactive=False,
                lines=6,
            )
            pair_table = gr.Dataframe(
                label="Active Pairs",
                headers=["ID", "Leader", "Follower", "Created", "Active"],
                interactive=False,
            )

            add_pair_btn.click(
                fn=add_pairs_batch,
                inputs=[leader_input, followers_input],
                outputs=[pair_status, pair_table],
            )
            refresh_btn.click(fn=refresh_pairs, outputs=[pair_table])

        with gr.Tab("Data Ingestion"):
            gr.Markdown("### Fetch Market Data for All Active Pairs")
            from_date_input = gr.Textbox(
                label="From Date",
                value="2020-01-01",
                placeholder="YYYY-MM-DD",
            )
            to_date_input = gr.Textbox(
                label="To Date",
                value=date.today().strftime("%Y-%m-%d"),
                placeholder="YYYY-MM-DD",
            )
            fetch_btn = gr.Button("Fetch All Pairs", variant="primary")
            fetch_log = gr.Textbox(
                label="Ingestion Log",
                lines=15,
                interactive=False,
            )

            fetch_btn.click(
                fn=fetch_all_data,
                inputs=[from_date_input, to_date_input],
                outputs=[fetch_log],
            )

        with gr.Tab("Normalize"):
            gr.Markdown("### Normalize All Active Pairs")
            gr.Markdown(
                "Applies Policy A split adjustment to raw OHLCV bars, stores dividends separately, "
                "and computes 1d/5d/10d/20d/60d returns from adj_close. Idempotent -- safe to re-run."
            )
            normalize_btn = gr.Button("Normalize All Pairs", variant="primary")
            normalize_log = gr.Textbox(
                label="Normalization Log",
                lines=15,
                interactive=False,
            )
            normalize_btn.click(
                fn=run_normalization,
                inputs=[],
                outputs=[normalize_log],
            )

        # --- Phase 5: Signal Dashboard (UI-01) ---
        build_signal_dashboard_tab(conn, config)

        # --- Phase 5: Paper Trading (UI-04) ---
        build_paper_trading_tab(conn, config)

        # --- Phase 6: Performance Analytics ---
        build_analytics_tab(conn, scheduler)

        # Load pairs on startup
        app.load(fn=refresh_pairs, outputs=[pair_table])

    app.queue()
    return app
