"""Lagged return offsets per ticker (FEAT-07).

Computes return_1d shifted at offsets +/-1 through +/-5 (10 offsets, excluding 0).
One row per (ticker, trading_day, lag) in features_lagged_returns.

Positive lag N: return N bars into the past (shift(+N)) — backward-looking.
Negative lag N: return N bars into the future (shift(-N)) — forward-looking.
NaN at leading/trailing edges -> stored as NULL.

NOTE: forward-looking lags are valid for cross-correlation discovery but
MUST NOT be used as same-day prediction features in live signals (look-ahead).
Phase 4 (lead-lag engine) enforces this; Phase 3 only stores the data.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger
from features.db import upsert_lagged_returns

# All offsets: -5 to +5, excluding 0 (10 offsets total)
_LAG_OFFSETS = [lag for lag in range(-5, 6) if lag != 0]


def compute_lagged_returns_for_ticker(
    conn: sqlite3.Connection,
    ticker: str,
    offsets: list[int] | None = None,
) -> int:
    """Compute lagged returns at all offsets and upsert to features_lagged_returns.

    Args:
        conn: Active SQLite connection with returns_policy_a populated.
        ticker: Ticker symbol.
        offsets: List of integer lag offsets. Default: -5 to +5 excluding 0.

    Returns:
        Number of rows upserted (n_days * n_offsets).
    """
    if offsets is None:
        offsets = _LAG_OFFSETS

    log = get_logger("features.lagged_returns").bind(ticker=ticker)

    df = pd.read_sql_query(
        "SELECT trading_day, return_1d FROM returns_policy_a "
        "WHERE ticker=? ORDER BY trading_day ASC",
        conn,
        params=(ticker,),
    )

    if df.empty:
        log.info("no_returns")
        return 0

    df = df.set_index("trading_day")
    series = df["return_1d"]
    days = series.index.tolist()

    rows: list[tuple] = []
    for lag in offsets:
        # shift(lag): positive lag shifts down (backward look), negative lag shifts up (forward look)
        # lag=+5 -> shift(5) -> first 5 rows NaN (need 5 prior bars)
        # lag=-5 -> shift(-5) -> last 5 rows NaN (need 5 future bars)
        shifted = series.shift(lag)
        for day, val in zip(days, shifted):
            rows.append((
                ticker,
                day,
                lag,
                None if pd.isna(val) else float(val),
            ))

    count = upsert_lagged_returns(conn, rows)
    log.info("lagged_returns_complete", rows=count, offsets=len(offsets))
    return count
