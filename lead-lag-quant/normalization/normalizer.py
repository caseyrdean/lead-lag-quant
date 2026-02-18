"""Orchestrates the full normalization pipeline for a ticker or all active pairs.

Pipeline per ticker:
1. extract_splits_to_table    -- raw splits -> splits table (NORM-01, NORM-05)
2. normalize_bars_for_ticker  -- raw aggs + splits -> normalized_bars (NORM-01, NORM-03, NORM-06)
3. store_dividends_for_ticker -- raw dividends -> dividends table (NORM-02)
"""
import sqlite3
from normalization.split_adjuster import extract_splits_to_table
from normalization.bar_normalizer import normalize_bars_for_ticker
from normalization.dividend_storer import store_dividends_for_ticker
from utils.logging import get_logger


def normalize_ticker(conn: sqlite3.Connection, ticker: str) -> dict:
    """Run the full normalization pipeline for one ticker.

    Args:
        conn: Active SQLite connection with all normalization tables created.
        ticker: Ticker symbol to normalize.

    Returns:
        Dict with keys: 'splits', 'bars', 'dividends' -- each the count upserted.
    """
    log = get_logger("normalization.normalizer").bind(ticker=ticker)
    log.info("normalize_ticker_start")

    splits_count = extract_splits_to_table(conn, ticker)
    bars_count = normalize_bars_for_ticker(conn, ticker)
    dividends_count = store_dividends_for_ticker(conn, ticker)

    result = {
        "splits": splits_count,
        "bars": bars_count,
        "dividends": dividends_count,
    }
    log.info("normalize_ticker_complete", **result)
    return result


def normalize_all_pairs(conn: sqlite3.Connection) -> dict:
    """Run normalization for all unique tickers across all active pairs, including SPY.

    Queries ticker_pairs, collects unique tickers (leader + follower + SPY for each pair),
    and calls normalize_ticker for each.

    Args:
        conn: Active SQLite connection.

    Returns:
        Dict keyed by ticker, each value is the result dict from normalize_ticker.
    """
    log = get_logger("normalization.normalizer")
    rows = conn.execute(
        "SELECT leader, follower FROM ticker_pairs WHERE is_active = 1"
    ).fetchall()

    tickers = set()
    for row in rows:
        tickers.add(row["leader"])
        tickers.add(row["follower"])
        tickers.add("SPY")

    if not tickers:
        log.info("no_active_pairs")
        return {}

    log.info("normalize_all_pairs_start", tickers=list(tickers))
    results = {}
    for ticker in sorted(tickers):
        results[ticker] = normalize_ticker(conn, ticker)

    log.info("normalize_all_pairs_complete", tickers=list(results.keys()))
    return results
