"""SQLite insert/upsert helpers for all 5 feature tables.

All helpers use ON CONFLICT DO UPDATE (upsert) for idempotency.
All use executemany for bulk performance.
NULL values are passed as Python None — sqlite3 maps None -> NULL.
"""
import sqlite3
from collections.abc import Iterable
from utils.logging import get_logger


def upsert_cross_correlation(
    conn: sqlite3.Connection,
    rows: Iterable[tuple],
) -> int:
    """Upsert cross-correlation rows.

    rows: (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
    Returns count of rows processed.
    """
    sql = """
        INSERT INTO features_cross_correlation
            (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker_a, ticker_b, trading_day, lag) DO UPDATE SET
            correlation=excluded.correlation,
            p_value=excluded.p_value,
            is_significant=excluded.is_significant
    """
    rows_list = list(rows)
    conn.executemany(sql, rows_list)
    conn.commit()
    return len(rows_list)


def upsert_relative_strength(
    conn: sqlite3.Connection,
    rows: Iterable[tuple],
) -> int:
    """Upsert relative strength rows.

    rows: (ticker_a, ticker_b, trading_day, rs_value)
    """
    sql = """
        INSERT INTO features_relative_strength
            (ticker_a, ticker_b, trading_day, rs_value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker_a, ticker_b, trading_day) DO UPDATE SET
            rs_value=excluded.rs_value
    """
    rows_list = list(rows)
    conn.executemany(sql, rows_list)
    conn.commit()
    return len(rows_list)


def upsert_volatility(
    conn: sqlite3.Connection,
    rows: Iterable[tuple],
) -> int:
    """Upsert volatility rows.

    rows: (ticker, trading_day, volatility_20d)
    """
    sql = """
        INSERT INTO features_volatility
            (ticker, trading_day, volatility_20d)
        VALUES (?, ?, ?)
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            volatility_20d=excluded.volatility_20d
    """
    rows_list = list(rows)
    conn.executemany(sql, rows_list)
    conn.commit()
    return len(rows_list)


def upsert_zscore(
    conn: sqlite3.Connection,
    rows: Iterable[tuple],
) -> int:
    """Upsert z-score rows.

    rows: (ticker, trading_day, zscore_return)
    """
    sql = """
        INSERT INTO features_zscore
            (ticker, trading_day, zscore_return)
        VALUES (?, ?, ?)
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            zscore_return=excluded.zscore_return
    """
    rows_list = list(rows)
    conn.executemany(sql, rows_list)
    conn.commit()
    return len(rows_list)


def upsert_lagged_returns(
    conn: sqlite3.Connection,
    rows: Iterable[tuple],
) -> int:
    """Upsert lagged return rows.

    rows: (ticker, trading_day, lag, return_value)
    """
    sql = """
        INSERT INTO features_lagged_returns
            (ticker, trading_day, lag, return_value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker, trading_day, lag) DO UPDATE SET
            return_value=excluded.return_value
    """
    rows_list = list(rows)
    conn.executemany(sql, rows_list)
    conn.commit()
    return len(rows_list)
