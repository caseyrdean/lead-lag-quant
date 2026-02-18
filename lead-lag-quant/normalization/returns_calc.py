"""Compute multi-period rolling returns from adj_close and store in returns_policy_a.

Returns are computed per NORM-04: 1d, 5d, 10d, 20d, 60d using pandas pct_change(periods=N).
Exclusively from adj_close. adjustment_policy_id = 'policy_a' on every row.

Critical: process ONE ticker at a time. Never load multiple tickers into one DataFrame
and call pct_change() -- pct_change is positional and bleeds across ticker boundaries.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger


_RETURN_PERIODS = {
    "return_1d": 1,
    "return_5d": 5,
    "return_10d": 10,
    "return_20d": 20,
    "return_60d": 60,
}


def compute_returns_for_ticker(conn: sqlite3.Connection, ticker: str) -> int:
    """Read normalized adj_close for one ticker, compute rolling returns, upsert.

    Uses pct_change(periods=N, fill_method=None) per pandas >= 2.1 requirement.
    fill_method='ffill' or fill_method='pad' are deprecated -- do NOT use them.

    First N rows per period will have NaN returns (insufficient history). These
    are stored as NULL in SQLite, which is correct behavior.

    Args:
        conn: Active SQLite connection with normalized_bars and returns_policy_a tables.
        ticker: Ticker to compute returns for.

    Returns:
        Number of rows upserted into returns_policy_a.
    """
    log = get_logger("normalization.returns_calc").bind(ticker=ticker)

    df = pd.read_sql_query(
        "SELECT trading_day, adj_close FROM normalized_bars "
        "WHERE ticker=? ORDER BY trading_day ASC",
        conn,
        params=(ticker,),
    )

    if df.empty:
        log.info("no_normalized_bars", ticker=ticker)
        return 0

    df = df.set_index("trading_day")

    # Compute each period independently -- fill_method=None avoids FutureWarning
    for col, n in _RETURN_PERIODS.items():
        df[col] = df["adj_close"].pct_change(periods=n, fill_method=None)

    df["ticker"] = ticker
    df["adjustment_policy_id"] = "policy_a"
    df = df.reset_index()  # trading_day back as column

    records = []
    for _, row in df.iterrows():
        records.append((
            ticker,
            row["trading_day"],
            None if pd.isna(row["return_1d"])  else float(row["return_1d"]),
            None if pd.isna(row["return_5d"])  else float(row["return_5d"]),
            None if pd.isna(row["return_10d"]) else float(row["return_10d"]),
            None if pd.isna(row["return_20d"]) else float(row["return_20d"]),
            None if pd.isna(row["return_60d"]) else float(row["return_60d"]),
        ))

    conn.executemany(
        """
        INSERT INTO returns_policy_a
            (ticker, trading_day, return_1d, return_5d, return_10d,
             return_20d, return_60d, adjustment_policy_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'policy_a')
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            return_1d=excluded.return_1d,
            return_5d=excluded.return_5d,
            return_10d=excluded.return_10d,
            return_20d=excluded.return_20d,
            return_60d=excluded.return_60d,
            adjustment_policy_id=excluded.adjustment_policy_id
        """,
        records,
    )
    conn.commit()
    log.info("returns_computed", count=len(records))
    return len(records)


def compute_returns_all_pairs(conn: sqlite3.Connection) -> dict:
    """Compute returns for all unique tickers across active pairs, including SPY.

    Args:
        conn: Active SQLite connection.

    Returns:
        Dict keyed by ticker, each value is the count of rows upserted.
    """
    log = get_logger("normalization.returns_calc")
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

    results = {}
    for ticker in sorted(tickers):
        results[ticker] = compute_returns_for_ticker(conn, ticker)

    log.info("compute_returns_all_pairs_complete", tickers=list(results.keys()))
    return results
