"""Ingestion orchestrator for fetching and storing Polygon.io market data."""

import json
import sqlite3

import requests

from ingestion_massive.polygon_client import PolygonClient
from utils.logging import get_logger


def store_raw_response(
    conn: sqlite3.Connection,
    ticker: str,
    endpoint: str,
    request_params: dict,
    response_json: str,
) -> None:
    """Store a raw API response in raw_api_responses with idempotent upsert.

    Uses ON CONFLICT DO UPDATE so re-running ingestion updates existing rows
    rather than raising errors or creating duplicates.

    Args:
        conn: Active SQLite connection.
        ticker: Ticker symbol the response belongs to.
        endpoint: API endpoint name (e.g., "aggs", "splits", "dividends").
        request_params: The parameters sent with the request (serialized to
            deterministic JSON for deduplication).
        response_json: The raw JSON response body as a string.
    """
    params_str = json.dumps(request_params, sort_keys=True)
    conn.execute(
        """
        INSERT INTO raw_api_responses (ticker, endpoint, request_params, response_json, retrieved_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT (ticker, endpoint, request_params)
        DO UPDATE SET
            response_json = excluded.response_json,
            retrieved_at = excluded.retrieved_at
        """,
        (ticker, endpoint, params_str, response_json),
    )
    conn.commit()


def log_ingestion(
    conn: sqlite3.Connection,
    ticker: str,
    endpoint: str,
    date_from: str | None,
    date_to: str | None,
    status: str,
    records_fetched: int = 0,
    error_message: str | None = None,
) -> int:
    """Insert an ingestion log row and return its row id.

    Args:
        conn: Active SQLite connection.
        ticker: Ticker symbol being ingested.
        endpoint: API endpoint name.
        date_from: Start date for the fetch (may be None for reference data).
        date_to: End date for the fetch (may be None for reference data).
        status: One of "started", "completed", "failed".
        records_fetched: Number of records returned by the API.
        error_message: Error details if status is "failed".

    Returns:
        The row id (INTEGER PRIMARY KEY) of the inserted row.
    """
    if status == "completed":
        cursor = conn.execute(
            """
            INSERT INTO ingestion_log
                (ticker, endpoint, date_from, date_to, status, records_fetched,
                 error_message, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (ticker, endpoint, date_from, date_to, status, records_fetched, error_message),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO ingestion_log
                (ticker, endpoint, date_from, date_to, status, records_fetched, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, endpoint, date_from, date_to, status, records_fetched, error_message),
        )
    conn.commit()
    return cursor.lastrowid


def update_ingestion_log(
    conn: sqlite3.Connection,
    log_id: int,
    status: str,
    records_fetched: int = 0,
    error_message: str | None = None,
) -> None:
    """Update an existing ingestion log row with final status and counts.

    Args:
        conn: Active SQLite connection.
        log_id: Row id of the ingestion_log row to update.
        status: Final status: "completed" or "failed".
        records_fetched: Total records returned by the API.
        error_message: Error details if status is "failed".
    """
    conn.execute(
        """
        UPDATE ingestion_log
        SET status = ?,
            records_fetched = ?,
            error_message = ?,
            completed_at = datetime('now')
        WHERE id = ?
        """,
        (status, records_fetched, error_message, log_id),
    )
    conn.commit()


def ingest_ticker(
    client: PolygonClient,
    conn: sqlite3.Connection,
    ticker: str,
    from_date: str,
    to_date: str,
    progress_callback=None,
) -> dict:
    """Fetch and store aggs, splits, and dividends for a single ticker.

    For each endpoint:
    1. Logs ingestion start.
    2. Calls the appropriate client method.
    3. Stores each raw response page via store_raw_response.
    4. Updates ingestion log with final status.

    Errors on individual endpoints are caught and logged; remaining
    endpoints are still attempted.

    Args:
        client: Configured PolygonClient instance.
        conn: Active SQLite connection with schema initialized.
        ticker: Stock ticker to fetch data for.
        from_date: Start date for aggregate bars (YYYY-MM-DD).
        to_date: End date for aggregate bars (YYYY-MM-DD).
        progress_callback: Optional callable called after each endpoint
            completes (receives ticker and endpoint name as args).

    Returns:
        Dict with keys "ticker", "aggs", "splits", "dividends" -- each
        value is the record count fetched (0 on failure).
    """
    log = get_logger("ingestion").bind(ticker=ticker)
    counts = {"ticker": ticker, "aggs": 0, "splits": 0, "dividends": 0}

    # --- Aggregate bars ---
    log_id = log_ingestion(
        conn, ticker, "aggs", from_date, to_date, "started"
    )
    try:
        results, raw_responses = client.get_aggs(ticker, from_date, to_date)
        for page_idx, page in enumerate(raw_responses):
            params_key = {
                "ticker": ticker,
                "from": from_date,
                "to": to_date,
                "page": page_idx,
            }
            store_raw_response(
                conn, ticker, "aggs", params_key, json.dumps(page)
            )
        counts["aggs"] = len(results)
        update_ingestion_log(conn, log_id, "completed", records_fetched=len(results))
        log.info("aggs_fetched", count=len(results))
    except Exception as exc:
        update_ingestion_log(conn, log_id, "failed", error_message=str(exc))
        log.error("aggs_failed", error=str(exc))

    if progress_callback:
        progress_callback(ticker, "aggs")

    # --- Stock splits ---
    log_id = log_ingestion(conn, ticker, "splits", None, None, "started")
    try:
        results, raw_responses = client.get_splits(ticker)
        for page_idx, page in enumerate(raw_responses):
            params_key = {"ticker": ticker, "page": page_idx}
            store_raw_response(
                conn, ticker, "splits", params_key, json.dumps(page)
            )
        counts["splits"] = len(results)
        update_ingestion_log(conn, log_id, "completed", records_fetched=len(results))
        log.info("splits_fetched", count=len(results))
    except Exception as exc:
        update_ingestion_log(conn, log_id, "failed", error_message=str(exc))
        log.error("splits_failed", error=str(exc))

    if progress_callback:
        progress_callback(ticker, "splits")

    # --- Dividends ---
    log_id = log_ingestion(conn, ticker, "dividends", None, None, "started")
    try:
        results, raw_responses = client.get_dividends(ticker)
        for page_idx, page in enumerate(raw_responses):
            params_key = {"ticker": ticker, "page": page_idx}
            store_raw_response(
                conn, ticker, "dividends", params_key, json.dumps(page)
            )
        counts["dividends"] = len(results)
        update_ingestion_log(conn, log_id, "completed", records_fetched=len(results))
        log.info("dividends_fetched", count=len(results))
    except Exception as exc:
        update_ingestion_log(conn, log_id, "failed", error_message=str(exc))
        log.error("dividends_failed", error=str(exc))

    if progress_callback:
        progress_callback(ticker, "dividends")

    return counts


def ingest_pair(
    client: PolygonClient,
    conn: sqlite3.Connection,
    leader: str,
    follower: str,
    from_date: str,
    to_date: str,
    progress_callback=None,
) -> dict:
    """Fetch and store all data for a ticker pair, always including SPY.

    Per INGEST-10, SPY is always included in every pair fetch regardless
    of whether leader or follower is SPY (no duplicate fetches).

    Args:
        client: Configured PolygonClient instance.
        conn: Active SQLite connection with schema initialized.
        leader: Leader ticker symbol.
        follower: Follower ticker symbol.
        from_date: Start date for aggregate bars (YYYY-MM-DD).
        to_date: End date for aggregate bars (YYYY-MM-DD).
        progress_callback: Optional callable forwarded to ingest_ticker.

    Returns:
        Dict keyed by ticker with per-ticker result dicts from ingest_ticker.
    """
    log = get_logger("ingestion").bind(leader=leader, follower=follower)

    # Deduplicated set: {leader, follower, SPY}
    tickers = list({leader.upper(), follower.upper(), "SPY"})
    log.info("ingest_pair_start", tickers=tickers)

    results = {}
    for ticker in tickers:
        log.info("ingesting_ticker", ticker=ticker)
        results[ticker] = ingest_ticker(
            client, conn, ticker, from_date, to_date, progress_callback
        )

    log.info("ingest_pair_complete", tickers=list(results.keys()))
    return results
