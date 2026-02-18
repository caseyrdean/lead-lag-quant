"""Reads raw aggregate bars from raw_api_responses, applies Policy A split adjustment,
and writes to normalized_bars."""
import json
import sqlite3
from normalization.split_adjuster import get_adjustment_factor_for_bar
from normalization.timestamp_utils import unix_ms_to_trading_day
from utils.logging import get_logger


def normalize_bars_for_ticker(conn: sqlite3.Connection, ticker: str) -> int:
    """Normalize all raw agg bars for a ticker and upsert into normalized_bars.

    Steps:
    1. Load all agg pages from raw_api_responses for this ticker.
    2. For each bar: convert Unix-ms timestamp to NYSE trading_day string.
    3. For each bar: call get_adjustment_factor_for_bar(conn, ticker, trading_day).
    4. Apply adjustment: adj_price = raw_price * factor, adj_volume = raw_volume / factor
       (VERIFY empirically on first run: for the most recent bars, factor should be 1.0
        and adj_close should equal close -- if not, swap multiply/divide).
    5. Upsert into normalized_bars using executemany().

    Args:
        conn: Active SQLite connection with normalized_bars table created.
        ticker: Ticker symbol to normalize.

    Returns:
        Number of bar rows upserted.
    """
    log = get_logger("normalization.bar_normalizer").bind(ticker=ticker)

    # Load all agg pages for this ticker
    rows = conn.execute(
        "SELECT response_json FROM raw_api_responses "
        "WHERE ticker=? AND endpoint='aggs' ORDER BY retrieved_at ASC",
        (ticker,)
    ).fetchall()

    bars = []
    for row in rows:
        data = json.loads(row["response_json"])
        bars.extend(data.get("results", []))

    if not bars:
        log.info("no_agg_bars_found", ticker=ticker)
        return 0

    records = []
    for bar in bars:
        trading_day = unix_ms_to_trading_day(bar["t"])
        factor = get_adjustment_factor_for_bar(conn, ticker, trading_day)

        # Policy A: split-adjust prices by multiplying by factor.
        # factor = 1.0 for tickers with no splits or for bars after all splits.
        # Volume is inverse: divide by factor.
        adj_open   = bar["o"] * factor
        adj_high   = bar["h"] * factor
        adj_low    = bar["l"] * factor
        adj_close  = bar["c"] * factor
        adj_volume = bar["v"] / factor if factor != 0 else bar["v"]

        records.append((
            ticker,
            trading_day,
            bar["o"],   # raw open
            bar["h"],   # raw high
            bar["l"],   # raw low
            bar["c"],   # raw close
            adj_open,
            adj_high,
            adj_low,
            adj_close,
            adj_volume,
            bar.get("vw"),   # vwap (may be absent)
            bar.get("n"),    # transactions (may be absent)
        ))

    conn.executemany(
        """
        INSERT INTO normalized_bars
            (ticker, trading_day, open, high, low, close,
             adj_open, adj_high, adj_low, adj_close, adj_volume,
             vwap, transactions, adjustment_policy_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'policy_a')
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            adj_open=excluded.adj_open,
            adj_high=excluded.adj_high,
            adj_low=excluded.adj_low,
            adj_close=excluded.adj_close,
            adj_volume=excluded.adj_volume,
            adjustment_policy_id=excluded.adjustment_policy_id
        """,
        records,
    )
    conn.commit()
    log.info("bars_normalized", count=len(records))
    return len(records)
