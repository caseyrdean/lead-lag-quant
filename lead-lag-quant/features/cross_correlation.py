"""Rolling cross-correlation with Bonferroni significance testing (FEAT-01, FEAT-03).

KEY CONSTRAINT: pandas.rolling().apply() CANNOT accept two series per window.
This module uses an explicit Python loop slicing both series per window.

BONFERRONI_THRESHOLD = 0.05 / 11 = 0.004545...
Never test significance at raw 0.05 -- 11 lag tests per window means ~42% false
positive rate without correction.

The cross-correlation loop:
  For each window end-index (window <= end <= n):
    Slice 60-day windows from both residualized series.
    For each lag in -5 to +5:
      Use scipy.stats.pearsonr on the lag-shifted slice pair.
      Apply Bonferroni threshold to p_value -> is_significant.
    Yield one row per (date, lag) pair.
"""
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from utils.logging import get_logger
from features.residualize import residualize_against_spy
from features.db import upsert_cross_correlation

# FEAT-03: Bonferroni correction across 11 lag offsets (-5 to +5)
BONFERRONI_ALPHA = 0.05
N_LAGS = 11
BONFERRONI_THRESHOLD = BONFERRONI_ALPHA / N_LAGS  # ~0.004545...

_LAGS = list(range(-5, 6))  # [-5, -4, ..., 0, ..., 4, 5]
_XCORR_WINDOW = 60  # minimum 60-day rolling window per FEAT-01


def _pearsonr_at_lag(a: np.ndarray, b: np.ndarray, lag: int) -> tuple[float, float]:
    """Compute Pearson r and p-value for arrays a and b at integer lag.

    Positive lag: b leads a (b_t predicts a_{t+lag}).
    Negative lag: a leads b (a_t predicts b_{t+|lag|}).
    Lag 0: contemporaneous correlation.

    Returns (nan, nan) if the aligned slice has fewer than 3 observations.
    """
    if lag == 0:
        a_slice, b_slice = a, b
    elif lag > 0:
        a_slice = a[lag:]
        b_slice = b[:-lag]
    else:  # lag < 0
        abs_lag = abs(lag)
        a_slice = a[:-abs_lag]
        b_slice = b[abs_lag:]

    if len(a_slice) < 3:
        return float("nan"), float("nan")

    r, p = stats.pearsonr(a_slice, b_slice)
    return float(r), float(p)


def compute_rolling_xcorr_for_pair(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    window: int = _XCORR_WINDOW,
) -> int:
    """Compute rolling cross-correlation for a ticker pair and upsert to SQLite.

    Reads 1d returns from returns_policy_a for ticker_a, ticker_b, and SPY.
    Residualizes ticker_a and ticker_b returns against SPY (FEAT-02).
    Computes Pearson r + p-value at lags -5 to +5 for each 60-day window (FEAT-01).
    Applies Bonferroni threshold (FEAT-03) to set is_significant flag.
    Upserts results to features_cross_correlation via features.db.upsert_cross_correlation.

    Args:
        conn: Active SQLite connection with returns_policy_a populated.
        ticker_a: First ticker in the pair (conventionally the leader).
        ticker_b: Second ticker in the pair (conventionally the follower).
        window: Rolling window in trading days. Must be >= 60 per FEAT-01.

    Returns:
        Number of rows upserted to features_cross_correlation.
    """
    log = get_logger("features.cross_correlation").bind(
        ticker_a=ticker_a, ticker_b=ticker_b
    )

    # Load 1d returns for all three tickers
    def _load_returns(ticker: str) -> pd.Series:
        df = pd.read_sql_query(
            "SELECT trading_day, return_1d FROM returns_policy_a "
            "WHERE ticker=? ORDER BY trading_day ASC",
            conn,
            params=(ticker,),
        )
        if df.empty:
            return pd.Series(dtype=float, name=ticker)
        return df.set_index("trading_day")["return_1d"].rename(ticker)

    ret_a = _load_returns(ticker_a)
    ret_b = _load_returns(ticker_b)
    ret_spy = _load_returns("SPY")

    if ret_a.empty or ret_b.empty or ret_spy.empty:
        log.warning("missing_returns", ticker_a=ticker_a, ticker_b=ticker_b)
        return 0

    # Align all three series to common trading days (inner join)
    combined = pd.concat([ret_a, ret_b, ret_spy], axis=1, join="inner")
    combined.columns = ["a", "b", "spy"]

    # Residualize both tickers against SPY (FEAT-02)
    # RollingOLS: first (window-1) rows will be NaN
    resid_a = residualize_against_spy(combined["a"], combined["spy"], window=window)
    resid_b = residualize_against_spy(combined["b"], combined["spy"], window=window)

    # Convert to numpy for slicing inside the window loop
    a_arr = resid_a.to_numpy()
    b_arr = resid_b.to_numpy()
    days = combined.index.tolist()
    n = len(a_arr)

    rows: list[tuple] = []

    # Manual rolling loop -- pandas.rolling().apply() cannot accept two series
    for end in range(window, n + 1):
        a_win = a_arr[end - window:end]
        b_win = b_arr[end - window:end]

        # If the window contains any NaN (early RollingOLS NaN leakage), skip
        if np.isnan(a_win).any() or np.isnan(b_win).any():
            continue

        trading_day = days[end - 1]

        for lag in _LAGS:
            r, p = _pearsonr_at_lag(a_win, b_win, lag)
            if np.isnan(r):
                rows.append((ticker_a, ticker_b, trading_day, lag, None, None, None))
            else:
                is_sig = 1 if p < BONFERRONI_THRESHOLD else 0
                rows.append((ticker_a, ticker_b, trading_day, lag, r, p, is_sig))

    if not rows:
        log.warning("no_xcorr_rows_produced", n_rows=n, window=window)
        return 0

    count = upsert_cross_correlation(conn, rows)
    log.info("xcorr_complete", rows=count)
    return count
