"""Rolling 20-day volatility per ticker (FEAT-05).

volatility_20d = rolling std(return_1d, window=20, ddof=1)
First (window-1) rows produce NaN -> stored as NULL.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger
from features.db import upsert_volatility

_VOL_WINDOW = 20  # 20-session rolling window per FEAT-05


def compute_volatility_for_ticker(
    conn: sqlite3.Connection,
    ticker: str,
    window: int = _VOL_WINDOW,
) -> int:
    """Compute rolling 20d volatility for one ticker and upsert to features_volatility.

    Args:
        conn: Active SQLite connection with returns_policy_a populated.
        ticker: Ticker symbol.
        window: Rolling window in sessions. Default 20 per FEAT-05.

    Returns:
        Number of rows upserted.
    """
    log = get_logger("features.volatility").bind(ticker=ticker)

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
    # min_periods=window: first (window-1) rows produce NaN -> stored as NULL
    df["volatility_20d"] = df["return_1d"].rolling(
        window=window, min_periods=window
    ).std(ddof=1)

    rows = [
        (ticker, day, None if pd.isna(val) else float(val))
        for day, val in df["volatility_20d"].items()
    ]

    count = upsert_volatility(conn, rows)
    log.info("volatility_complete", rows=count)
    return count
