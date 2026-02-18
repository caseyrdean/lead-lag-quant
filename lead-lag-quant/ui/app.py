"""Gradio application for Lead-Lag Quant -- Pair Management and Data Ingestion panels."""

import sqlite3
from datetime import date

import gradio as gr

from ingestion_massive.ingestion import ingest_pair
from ingestion_massive.polygon_client import PolygonClient
from utils.config import AppConfig
from utils.db import get_connection, init_schema


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

    def add_pair(leader: str, follower: str):
        """Validate and persist a new ticker pair.

        Steps:
        1. Normalise inputs (strip + uppercase).
        2. Reject empty or identical tickers.
        3. Validate both tickers via Polygon reference API.
        4. Insert into ticker_pairs; catch duplicates gracefully.

        Returns:
            Tuple of (status_message, updated_pair_table).
        """
        leader = leader.strip().upper()
        follower = follower.strip().upper()

        if not leader or not follower:
            return "Error: Both Leader and Follower tickers are required.", _load_pairs()

        if leader == follower:
            return "Error: Leader and Follower must be different tickers.", _load_pairs()

        # Validate leader
        leader_details = client.get_ticker_details(leader)
        if leader_details is None:
            return (
                f"Invalid ticker: {leader} (not found or inactive on Polygon.io)",
                _load_pairs(),
            )

        # Validate follower
        follower_details = client.get_ticker_details(follower)
        if follower_details is None:
            return (
                f"Invalid ticker: {follower} (not found or inactive on Polygon.io)",
                _load_pairs(),
            )

        # Persist pair
        try:
            conn.execute(
                "INSERT INTO ticker_pairs (leader, follower) VALUES (?, ?)",
                (leader, follower),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return (
                f"Pair {leader}/{follower} already exists.",
                _load_pairs(),
            )

        return f"Pair {leader}/{follower} added successfully.", _load_pairs()

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

        total = len(pairs)
        log_lines = [f"Starting ingestion for {total} pair(s) [{from_date} -> {to_date}]\n"]

        try:
            for i, row in enumerate(pairs):
                leader, follower = row[0], row[1]
                progress((i / total), desc=f"Fetching {leader}/{follower}...")

                results = ingest_pair(
                    client, conn, leader, follower, from_date, to_date
                )

                # Summarise per-ticker results
                for ticker, counts in results.items():
                    log_lines.append(
                        f"  {ticker}: aggs={counts['aggs']}, "
                        f"splits={counts['splits']}, dividends={counts['dividends']}"
                    )

                progress(((i + 1) / total), desc=f"Fetching {leader}/{follower}...")
                log_lines.append(f"Pair {leader}/{follower} complete.\n")

        except Exception as exc:
            log_lines.append(f"\nError during ingestion: {exc}")
            return "\n".join(log_lines)

        log_lines.append("All pairs ingested successfully.")
        return "\n".join(log_lines)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    with gr.Blocks(title="Lead-Lag Quant") as app:
        gr.Markdown("# Lead-Lag Quant")

        with gr.Tab("Pair Management"):
            gr.Markdown("### Add Ticker Pair")
            with gr.Row():
                leader_input = gr.Textbox(
                    label="Leader Ticker",
                    placeholder="e.g., NVDA",
                )
                follower_input = gr.Textbox(
                    label="Follower Ticker",
                    placeholder="e.g., CRWV",
                )
            with gr.Row():
                add_pair_btn = gr.Button("Add Pair", variant="primary")
                refresh_btn = gr.Button("Refresh")
            pair_status = gr.Textbox(label="Status", interactive=False)
            pair_table = gr.Dataframe(
                label="Active Pairs",
                headers=["ID", "Leader", "Follower", "Created", "Active"],
                interactive=False,
            )

            add_pair_btn.click(
                fn=add_pair,
                inputs=[leader_input, follower_input],
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

        # Load pairs on startup
        app.load(fn=refresh_pairs, outputs=[pair_table])

    app.queue()
    return app
