"""Rolling z-score standardization of returns per ticker (FEAT-06).

zscore = (return_1d - rolling_mean(20d)) / rolling_std(20d, ddof=1)
First (window-1) rows produce NaN -> stored as NULL.
When rolling_std == 0 (flat period), zscore is NaN -> stored as NULL.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger
from features.db import upsert_zscore

_ZSCORE_WINDOW = 20  # 20-session rolling window per FEAT-06


def compute_zscore_for_ticker(
    conn: sqlite3.Connection,
    ticker: str,
    window: int = _ZSCORE_WINDOW,
) -> int:
    """Compute rolling z-score for one ticker and upsert to features_zscore.

    Args:
        conn: Active SQLite connection with returns_policy_a populated.
        ticker: Ticker symbol.
        window: Rolling window in sessions. Default 20 per FEAT-06.

    Returns:
        Number of rows upserted.
    """
    log = get_logger("features.zscore").bind(ticker=ticker)

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
    roll = df["return_1d"].rolling(window=window, min_periods=window)
    mu = roll.mean()
    sigma = roll.std(ddof=1)

    # NaN when sigma == 0 (flat period) or insufficient history — stored as NULL
    zscore = (df["return_1d"] - mu) / sigma

    rows = [
        (ticker, day, None if pd.isna(val) else float(val))
        for day, val in zscore.items()
    ]

    count = upsert_zscore(conn, rows)
    log.info("zscore_complete", rows=count)
    return count
