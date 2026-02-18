"""Relative Strength computation between leader and follower tickers (FEAT-04).

RS = rolling_cumulative_return(leader, 10d) - rolling_cumulative_return(follower, 10d)
Cumulative return: product of (1 + r_i) - 1 over the window.

Both tickers read from returns_policy_a (1d returns).
min_periods=window enforces full-window requirement: partial windows -> NaN -> NULL.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger
from features.db import upsert_relative_strength

_RS_WINDOW = 10  # 10-session rolling window per FEAT-04


def _rolling_cumulative_return(returns: pd.Series, window: int) -> pd.Series:
    """Compute rolling cumulative return: prod(1 + r_i) - 1 over window bars.

    min_periods=window ensures partial windows produce NaN (stored as NULL).
    raw=True passes numpy array to lambda for speed.
    """
    return returns.rolling(window=window, min_periods=window).apply(
        lambda x: (1 + x).prod() - 1, raw=True
    )


def compute_relative_strength_for_pair(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    window: int = _RS_WINDOW,
) -> int:
    """Compute rolling RS for (ticker_a, ticker_b) and upsert to features_relative_strength.

    Args:
        conn: Active SQLite connection with returns_policy_a populated.
        ticker_a: Leader ticker.
        ticker_b: Follower ticker.
        window: Rolling window in sessions. Default 10 per FEAT-04.

    Returns:
        Number of rows upserted.
    """
    log = get_logger("features.relative_strength").bind(
        ticker_a=ticker_a, ticker_b=ticker_b
    )

    def _load_1d_returns(ticker: str) -> pd.Series:
        df = pd.read_sql_query(
            "SELECT trading_day, return_1d FROM returns_policy_a "
            "WHERE ticker=? ORDER BY trading_day ASC",
            conn,
            params=(ticker,),
        )
        if df.empty:
            return pd.Series(dtype=float, name=ticker)
        return df.set_index("trading_day")["return_1d"].rename(ticker)

    ret_a = _load_1d_returns(ticker_a)
    ret_b = _load_1d_returns(ticker_b)

    if ret_a.empty or ret_b.empty:
        log.warning("missing_returns")
        return 0

    # Align to common trading days
    combined = pd.concat([ret_a, ret_b], axis=1, join="inner")
    combined.columns = ["a", "b"]

    cum_a = _rolling_cumulative_return(combined["a"], window)
    cum_b = _rolling_cumulative_return(combined["b"], window)
    rs = cum_a - cum_b

    rows = [
        (ticker_a, ticker_b, day, None if pd.isna(val) else float(val))
        for day, val in rs.items()
    ]

    count = upsert_relative_strength(conn, rows)
    log.info("rs_complete", rows=count)
    return count
