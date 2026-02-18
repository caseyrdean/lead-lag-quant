"""Split record extraction and per-bar historical adjustment factor lookup."""
import json
import sqlite3
from utils.logging import get_logger


def extract_splits_to_table(conn: sqlite3.Connection, ticker: str) -> int:
    """Read raw splits JSON from raw_api_responses, upsert into splits table.

    Copies retrieved_at from raw_api_responses as fetched_at per NORM-05
    (enables point-in-time backtest isolation).

    Args:
        conn: Active SQLite connection with splits table created.
        ticker: Ticker to extract splits for.

    Returns:
        Number of split records upserted.
    """
    log = get_logger("normalization.split_adjuster").bind(ticker=ticker)
    rows = conn.execute(
        "SELECT response_json, retrieved_at FROM raw_api_responses "
        "WHERE ticker=? AND endpoint='splits' ORDER BY retrieved_at DESC LIMIT 1",
        (ticker,)
    ).fetchall()

    count = 0
    for row in rows:
        body, retrieved_at = row["response_json"], row["retrieved_at"]
        data = json.loads(body)
        splits = data.get("results", [])
        records = [
            (
                ticker,
                split["execution_date"],
                split["split_from"],
                split["split_to"],
                split.get("historical_adjustment_factor"),
                split.get("adjustment_type"),
                retrieved_at,
            )
            for split in splits
        ]
        conn.executemany(
            """
            INSERT INTO splits
                (ticker, execution_date, split_from, split_to,
                 historical_adjustment_factor, adjustment_type, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, execution_date) DO UPDATE SET
                historical_adjustment_factor=excluded.historical_adjustment_factor,
                adjustment_type=excluded.adjustment_type,
                fetched_at=excluded.fetched_at
            """,
            records,
        )
        count += len(records)
    conn.commit()
    log.info("splits_extracted", count=count)
    return count


def get_adjustment_factor_for_bar(
    conn: sqlite3.Connection, ticker: str, bar_date: str
) -> float:
    """Return the cumulative backward adjustment factor for a bar on bar_date.

    Policy A uses Polygon's historical_adjustment_factor from the splits table.
    This is the factor for splits that executed AFTER bar_date (i.e., the
    cumulative product of all split_to/split_from ratios after bar_date).

    CRITICAL -- multiply vs divide verification at implementation time:
    Polygon docs say "multiply the unadjusted price by historical_adjustment_factor".
    At runtime, verify: for the most recent bar, adj_close should approximate raw close.
    If adj_close = raw_close * factor produces adj approximately equal to raw only when
    factor approximately equals 1.0 (most recent bars), then multiply is correct.
    bar_normalizer.py uses this function and must validate the direction empirically.

    Strategy: find the split with execution_date > bar_date and the smallest
    execution_date (i.e., the next split after this bar). Its
    historical_adjustment_factor is the cumulative factor for this bar.
    If no splits exist after bar_date, factor = 1.0 (no adjustment needed).

    For tickers with no splits at all: returns 1.0 (NORM-05 base case).

    Args:
        conn: Active SQLite connection.
        ticker: Ticker symbol.
        bar_date: Trading day as 'YYYY-MM-DD'.

    Returns:
        Float adjustment factor. 1.0 means no adjustment.
    """
    row = conn.execute(
        """
        SELECT historical_adjustment_factor
        FROM splits
        WHERE ticker = ?
          AND execution_date > ?
        ORDER BY execution_date ASC
        LIMIT 1
        """,
        (ticker, bar_date),
    ).fetchone()

    if row is None or row["historical_adjustment_factor"] is None:
        return 1.0
    return float(row["historical_adjustment_factor"])
