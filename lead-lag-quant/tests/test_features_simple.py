"""Tests for features FEAT-04 through FEAT-07: RS, volatility, z-score, lagged returns."""
import numpy as np
import pandas as pd
import pytest

from features.relative_strength import compute_relative_strength_for_pair, _RS_WINDOW
from features.volatility import compute_volatility_for_ticker, _VOL_WINDOW
from features.zscore import compute_zscore_for_ticker, _ZSCORE_WINDOW
from features.lagged_returns import compute_lagged_returns_for_ticker, _LAG_OFFSETS


def _insert_1d_returns(conn, ticker, days, returns_1d):
    """Insert 1d return rows into returns_policy_a for testing."""
    rows = [
        (ticker, day, ret, None, None, None, None)
        for day, ret in zip(days, returns_1d)
    ]
    conn.executemany(
        """
        INSERT INTO returns_policy_a
            (ticker, trading_day, return_1d, return_5d, return_10d,
             return_20d, return_60d, adjustment_policy_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'policy_a')
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            return_1d=excluded.return_1d
        """,
        rows,
    )
    conn.commit()


def _make_days(n: int) -> list[str]:
    """Generate n synthetic trading day strings."""
    return [f"2023-{(i // 28 + 1):02d}-{(i % 28 + 1):02d}" for i in range(n)]


# --- Relative Strength (FEAT-04) ---

def test_rs_row_count(tmp_db):
    """RS must produce one row per aligned trading day."""
    rng = np.random.default_rng(42)
    n = 80
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "LEAD", days, rng.normal(0, 0.01, n))
    _insert_1d_returns(tmp_db, "FOLL", days, rng.normal(0, 0.01, n))

    count = compute_relative_strength_for_pair(tmp_db, "LEAD", "FOLL")
    assert count == n


def test_rs_first_window_minus_one_are_null(tmp_db):
    """First (window-1) RS rows must be NULL — insufficient history."""
    rng = np.random.default_rng(3)
    n = 50
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "LDR", days, rng.normal(0, 0.01, n))
    _insert_1d_returns(tmp_db, "FLR", days, rng.normal(0, 0.01, n))

    compute_relative_strength_for_pair(tmp_db, "LDR", "FLR")

    early_rows = tmp_db.execute(
        "SELECT rs_value FROM features_relative_strength "
        "WHERE ticker_a='LDR' AND ticker_b='FLR' "
        f"ORDER BY trading_day ASC LIMIT {_RS_WINDOW - 1}"
    ).fetchall()
    for row in early_rows:
        assert row["rs_value"] is None, f"Expected NULL, got {row['rs_value']}"


def test_rs_empty_ticker_returns_zero(tmp_db):
    """RS for a ticker with no returns must return 0 without error."""
    count = compute_relative_strength_for_pair(tmp_db, "MISSING_A", "MISSING_B")
    assert count == 0


# --- Volatility (FEAT-05) ---

def test_volatility_row_count(tmp_db):
    """Volatility must produce one row per trading day."""
    rng = np.random.default_rng(5)
    n = 60
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "VOL_T", days, rng.normal(0, 0.01, n))

    count = compute_volatility_for_ticker(tmp_db, "VOL_T")
    assert count == n


def test_volatility_early_rows_are_null(tmp_db):
    """First (window-1) volatility rows must be NULL."""
    rng = np.random.default_rng(7)
    n = 50
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "VOL_E", days, rng.normal(0, 0.01, n))

    compute_volatility_for_ticker(tmp_db, "VOL_E")

    early = tmp_db.execute(
        "SELECT volatility_20d FROM features_volatility WHERE ticker='VOL_E' "
        f"ORDER BY trading_day ASC LIMIT {_VOL_WINDOW - 1}"
    ).fetchall()
    for row in early:
        assert row["volatility_20d"] is None


def test_volatility_window_rows_are_non_null(tmp_db):
    """Rows at index >= window must have non-NULL volatility (for non-flat returns)."""
    rng = np.random.default_rng(9)
    n = 60
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "VOL_N", days, rng.normal(0, 0.01, n))

    compute_volatility_for_ticker(tmp_db, "VOL_N")

    late_rows = tmp_db.execute(
        "SELECT volatility_20d FROM features_volatility WHERE ticker='VOL_N' "
        f"ORDER BY trading_day ASC LIMIT {n} OFFSET {_VOL_WINDOW}"
    ).fetchall()
    assert any(r["volatility_20d"] is not None for r in late_rows)


# --- Z-Score (FEAT-06) ---

def test_zscore_row_count(tmp_db):
    """Z-score must produce one row per trading day."""
    rng = np.random.default_rng(11)
    n = 60
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "ZSC_T", days, rng.normal(0, 0.01, n))

    count = compute_zscore_for_ticker(tmp_db, "ZSC_T")
    assert count == n


def test_zscore_early_rows_are_null(tmp_db):
    """First (window-1) z-score rows must be NULL."""
    rng = np.random.default_rng(13)
    n = 50
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "ZSC_E", days, rng.normal(0, 0.01, n))

    compute_zscore_for_ticker(tmp_db, "ZSC_E")

    early = tmp_db.execute(
        "SELECT zscore_return FROM features_zscore WHERE ticker='ZSC_E' "
        f"ORDER BY trading_day ASC LIMIT {_ZSCORE_WINDOW - 1}"
    ).fetchall()
    for row in early:
        assert row["zscore_return"] is None


# --- Lagged Returns (FEAT-07) ---

def test_lagged_returns_offset_count(tmp_db):
    """Must produce one row per (day, lag) for 10 lags (-5 to +5 excl. 0)."""
    rng = np.random.default_rng(15)
    n = 30
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "LAG_T", days, rng.normal(0, 0.01, n))

    count = compute_lagged_returns_for_ticker(tmp_db, "LAG_T")
    assert count == n * len(_LAG_OFFSETS)


def test_lagged_returns_lags_stored(tmp_db):
    """All 10 lag offsets must appear in features_lagged_returns."""
    rng = np.random.default_rng(17)
    n = 30
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "LAG_L", days, rng.normal(0, 0.01, n))

    compute_lagged_returns_for_ticker(tmp_db, "LAG_L")

    stored_lags = {
        r["lag"] for r in tmp_db.execute(
            "SELECT DISTINCT lag FROM features_lagged_returns WHERE ticker='LAG_L'"
        ).fetchall()
    }
    expected_lags = set(_LAG_OFFSETS)
    assert stored_lags == expected_lags, f"Expected {expected_lags}, got {stored_lags}"


def test_lagged_returns_edges_are_null(tmp_db):
    """Leading/trailing edge rows for extreme lags must be NULL (insufficient neighbors)."""
    rng = np.random.default_rng(19)
    n = 20
    days = _make_days(n)
    _insert_1d_returns(tmp_db, "LAG_E", days, rng.normal(0, 0.01, n))

    compute_lagged_returns_for_ticker(tmp_db, "LAG_E")

    # Last 5 rows for lag=-5 should be NULL (forward shift past end of series)
    edge_rows = tmp_db.execute(
        "SELECT return_value FROM features_lagged_returns "
        "WHERE ticker='LAG_E' AND lag=-5 "
        "ORDER BY trading_day DESC LIMIT 5"
    ).fetchall()
    assert any(r["return_value"] is None for r in edge_rows)
