"""Reads raw dividend records from raw_api_responses and writes to dividends table.

Per NORM-02 (Policy A): dividends are stored for reference only and are NEVER
applied to price calculations. normalized_bars contains split-adjusted prices only.
"""
import json
import sqlite3
from utils.logging import get_logger


def store_dividends_for_ticker(conn: sqlite3.Connection, ticker: str) -> int:
    """Extract dividend records and upsert into dividends table.

    Copies retrieved_at from raw_api_responses as fetched_at.

    Args:
        conn: Active SQLite connection with dividends table created.
        ticker: Ticker symbol to extract dividends for.

    Returns:
        Number of dividend records upserted.
    """
    log = get_logger("normalization.dividend_storer").bind(ticker=ticker)
    rows = conn.execute(
        "SELECT response_json, retrieved_at FROM raw_api_responses "
        "WHERE ticker=? AND endpoint='dividends' ORDER BY retrieved_at DESC LIMIT 1",
        (ticker,)
    ).fetchall()

    count = 0
    for row in rows:
        body, retrieved_at = row["response_json"], row["retrieved_at"]
        data = json.loads(body)
        dividends = data.get("results", [])
        records = [
            (
                ticker,
                div["ex_date"],
                div.get("cash_amount"),
                div.get("currency"),
                div.get("dividend_type"),
                div.get("pay_date"),
                div.get("record_date"),
                retrieved_at,
            )
            for div in dividends
        ]
        conn.executemany(
            """
            INSERT INTO dividends
                (ticker, ex_date, cash_amount, currency, dividend_type,
                 pay_date, record_date, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, ex_date) DO UPDATE SET
                cash_amount=excluded.cash_amount,
                fetched_at=excluded.fetched_at
            """,
            records,
        )
        count += len(records)
    conn.commit()
    log.info("dividends_stored", count=count)
    return count
