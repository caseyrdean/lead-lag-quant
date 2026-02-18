"""Tests for features.residualize and features.cross_correlation (FEAT-01, FEAT-02, FEAT-03)."""
import math
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from utils.db import init_schema
from features.residualize import residualize_against_spy
from features.cross_correlation import (
    compute_rolling_xcorr_for_pair,
    BONFERRONI_THRESHOLD,
    N_LAGS,
    BONFERRONI_ALPHA,
    _pearsonr_at_lag,
)


# --- Bonferroni constant ---

def test_bonferroni_threshold_value():
    """BONFERRONI_THRESHOLD must equal 0.05 / 11 per FEAT-03."""
    expected = 0.05 / 11
    assert abs(BONFERRONI_THRESHOLD - expected) < 1e-12


def test_bonferroni_n_lags():
    """N_LAGS must be 11 (lags -5 to +5 inclusive)."""
    assert N_LAGS == 11


# --- residualize_against_spy ---

def test_residualize_returns_same_length():
    """Residuals must have same length as input series."""
    rng = np.random.default_rng(42)
    n = 120
    spy = pd.Series(rng.normal(0, 0.01, n), name="SPY")
    ticker = pd.Series(0.8 * spy + rng.normal(0, 0.005, n), name="AAPL")
    resid = residualize_against_spy(ticker, spy, window=60)
    assert len(resid) == n


def test_residualize_first_window_minus_one_are_nan():
    """First (window-1) residuals must be NaN -- insufficient history."""
    rng = np.random.default_rng(7)
    n = 100
    window = 60
    spy = pd.Series(rng.normal(0, 0.01, n))
    ticker = pd.Series(0.5 * spy + rng.normal(0, 0.01, n))
    resid = residualize_against_spy(ticker, spy, window=window)
    # First window-1 rows are NaN
    assert resid.iloc[:window - 1].isna().all(), "Expected NaN for early rows"
    # Rows from window onwards should mostly be non-NaN
    assert resid.iloc[window:].notna().any(), "Expected non-NaN after warm-up"


def test_residualize_raises_on_misaligned_index():
    """Misaligned indices must raise ValueError."""
    rng = np.random.default_rng(1)
    spy = pd.Series(rng.normal(0, 0.01, 80), index=range(80))
    ticker = pd.Series(rng.normal(0, 0.01, 70), index=range(70))
    with pytest.raises(ValueError, match="identical indices"):
        residualize_against_spy(ticker, spy, window=60)


# --- _pearsonr_at_lag ---

def test_pearsonr_lag0_matches_direct():
    """pearsonr at lag 0 must equal direct scipy.stats.pearsonr result."""
    rng = np.random.default_rng(5)
    a = rng.normal(0, 1, 60)
    b = rng.normal(0, 1, 60)
    r_direct, p_direct = stats.pearsonr(a, b)
    r_lag, p_lag = _pearsonr_at_lag(a, b, lag=0)
    assert abs(r_lag - r_direct) < 1e-10
    assert abs(p_lag - p_direct) < 1e-10


def test_pearsonr_positive_lag_slices_correctly():
    """At lag +1: a[1:] vs b[:-1] (b leads a by 1 bar)."""
    rng = np.random.default_rng(9)
    a = rng.normal(0, 1, 60)
    b = np.roll(a, 1) + rng.normal(0, 0.1, 60)  # b leads a by 1
    r_lag1, _ = _pearsonr_at_lag(a, b, lag=1)
    r_lag0, _ = _pearsonr_at_lag(a, b, lag=0)
    # lag+1 should show stronger correlation when b leads a by exactly 1
    assert r_lag1 > r_lag0, "Expected lag+1 to show stronger correlation"


# --- compute_rolling_xcorr_for_pair (integration) ---

def _insert_returns(conn, ticker, days, returns_1d):
    """Helper: insert 1d return rows into returns_policy_a."""
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


def test_xcorr_stores_rows_in_db(tmp_db):
    """compute_rolling_xcorr_for_pair must store rows in features_cross_correlation."""
    rng = np.random.default_rng(11)
    n = 120
    days = [f"2023-{(i // 20 + 1):02d}-{(i % 20 + 1):02d}" for i in range(n)]
    spy_ret = rng.normal(0, 0.01, n)
    a_ret = 0.7 * spy_ret + rng.normal(0, 0.005, n)
    b_ret = 0.6 * spy_ret + rng.normal(0, 0.005, n)

    _insert_returns(tmp_db, "SPY", days, spy_ret)
    _insert_returns(tmp_db, "AAA", days, a_ret)
    _insert_returns(tmp_db, "BBB", days, b_ret)

    count = compute_rolling_xcorr_for_pair(tmp_db, "AAA", "BBB")
    assert count > 0, "Expected rows to be stored"

    # Each window-date produces 11 lag rows
    rows = tmp_db.execute(
        "SELECT * FROM features_cross_correlation WHERE ticker_a='AAA' AND ticker_b='BBB'"
    ).fetchall()
    assert len(rows) > 0
    lags_found = {r["lag"] for r in rows}
    assert lags_found == set(range(-5, 6)), f"Expected lags -5..5, got {lags_found}"


def test_xcorr_is_significant_uses_bonferroni(tmp_db):
    """is_significant flag must use BONFERRONI_THRESHOLD, not raw 0.05."""
    rng = np.random.default_rng(13)
    n = 120
    days = [f"2023-{(i // 20 + 1):02d}-{(i % 20 + 1):02d}" for i in range(n)]
    spy_ret = rng.normal(0, 0.01, n)
    # Highly correlated pair to force some significant lags
    a_ret = 0.9 * spy_ret + rng.normal(0, 0.001, n)
    b_ret = np.concatenate([[0], a_ret[:-1]])  # b is a shifted by 1 bar

    _insert_returns(tmp_db, "SPY", days, spy_ret)
    _insert_returns(tmp_db, "SIG_A", days, a_ret)
    _insert_returns(tmp_db, "SIG_B", days, b_ret)

    compute_rolling_xcorr_for_pair(tmp_db, "SIG_A", "SIG_B")

    # Query significant rows -- is_significant uses BONFERRONI_THRESHOLD not 0.05
    sig_rows = tmp_db.execute(
        "SELECT p_value FROM features_cross_correlation "
        "WHERE ticker_a='SIG_A' AND ticker_b='SIG_B' AND is_significant=1"
    ).fetchall()
    for row in sig_rows:
        assert row["p_value"] < BONFERRONI_THRESHOLD, (
            f"p_value {row['p_value']} should be < {BONFERRONI_THRESHOLD}"
        )


def test_xcorr_null_when_insufficient_history(tmp_db):
    """With fewer rows than window size, xcorr must store zero rows (no false values)."""
    rng = np.random.default_rng(17)
    n = 50  # Less than 60-day window
    days = [f"2023-01-{(i + 1):02d}" for i in range(n)]
    spy_ret = rng.normal(0, 0.01, n)
    a_ret = rng.normal(0, 0.01, n)
    b_ret = rng.normal(0, 0.01, n)

    _insert_returns(tmp_db, "SPY", days, spy_ret)
    _insert_returns(tmp_db, "SHORT_A", days, a_ret)
    _insert_returns(tmp_db, "SHORT_B", days, b_ret)

    count = compute_rolling_xcorr_for_pair(tmp_db, "SHORT_A", "SHORT_B")
    assert count == 0, "Expected 0 rows when fewer than window trading days available"
