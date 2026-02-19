"""Optimal lag detection for a ticker pair (ENGINE-01).

Reads features_cross_correlation (pre-computed by Phase 3).
Phase 4 NEVER recomputes raw cross-correlations -- it aggregates stored results.

LAG SIGN CONVENTION (from features/cross_correlation.py _pearsonr_at_lag):
  Positive lag: ticker_b leads ticker_a  (b_t predicts a_{t+lag})
  Negative lag: ticker_a leads ticker_b  (a_t predicts b_{t+|lag|})
  Lag 0: contemporaneous

This convention must be respected in flow_map_entry construction (see signals/generator.py).
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger

_MIN_SIGNIFICANT_DAYS = 30       # Ideal minimum days with is_significant=1
_MIN_SIGNIFICANT_DAYS_FLOOR = 5  # Floor for limited-data fallback
_DEFAULT_LOOKBACK = 120          # Days of history to consider


def detect_optimal_lag(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> dict | None:
    """Identify the optimal lag for a pair from stored cross-correlation features.

    Returns {'optimal_lag': int, 'correlation_strength': float} where:
      - optimal_lag: the lag offset with highest |median correlation| among eligible lags
      - correlation_strength: signed median correlation at optimal_lag (positive or negative)

    Returns None if no lag has >= _MIN_SIGNIFICANT_DAYS of is_significant=1 observations.

    CRITICAL: Always filter AND is_significant=1 AND correlation IS NOT NULL.
    Phase 3 stores NULL for insufficient history -- do not include NULL rows in aggregation.
    """
    log = get_logger("leadlag_engine.detector")

    # Anchor lookback to the pair's actual max trading day, not datetime('now').
    # This prevents OOS score instability on weekends/holidays.
    anchor_sql = """
        SELECT MAX(trading_day) FROM features_cross_correlation
        WHERE ticker_a = ? AND ticker_b = ?
          AND is_significant = 1
          AND correlation IS NOT NULL
    """
    anchor = conn.execute(anchor_sql, (ticker_a, ticker_b)).fetchone()[0]
    if anchor is None:
        log.info("detect_optimal_lag_no_data", ticker_a=ticker_a, ticker_b=ticker_b)
        return None

    sql = """
        SELECT lag, correlation
        FROM features_cross_correlation
        WHERE ticker_a = ? AND ticker_b = ?
          AND is_significant = 1
          AND correlation IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
        ORDER BY trading_day ASC
    """
    df = pd.read_sql_query(
        sql, conn,
        params=(ticker_a, ticker_b, anchor, f'-{lookback_days}')
    )

    if df.empty:
        log.info("detect_optimal_lag_empty", ticker_a=ticker_a, ticker_b=ticker_b)
        return None

    # Compute per-lag stats: median correlation + count of significant days
    lag_stats = df.groupby('lag')['correlation'].agg(
        median_corr='median',
        count='count',
    )

    # Require at least _MIN_SIGNIFICANT_DAYS of significant observations per lag.
    # If unavailable, fall back to floor threshold and flag as limited_data.
    eligible = lag_stats[lag_stats['count'] >= _MIN_SIGNIFICANT_DAYS]
    limited_data = False

    if eligible.empty:
        eligible = lag_stats[lag_stats['count'] >= _MIN_SIGNIFICANT_DAYS_FLOOR]
        if eligible.empty:
            log.info(
                "detect_optimal_lag_insufficient_days",
                ticker_a=ticker_a, ticker_b=ticker_b,
                max_count=int(lag_stats['count'].max()),
                min_required=_MIN_SIGNIFICANT_DAYS_FLOOR,
            )
            return None
        limited_data = True

    # Optimal lag: highest absolute median correlation among eligible lags
    optimal_lag = int(eligible['median_corr'].abs().idxmax())
    correlation_strength = float(eligible.loc[optimal_lag, 'median_corr'])
    significant_days = int(eligible.loc[optimal_lag, 'count'])

    log.info(
        "detect_optimal_lag_found",
        ticker_a=ticker_a, ticker_b=ticker_b,
        optimal_lag=optimal_lag,
        correlation_strength=round(correlation_strength, 4),
        significant_days=significant_days,
        limited_data=limited_data,
    )
    return {
        'optimal_lag': optimal_lag,
        'correlation_strength': correlation_strength,
        'limited_data': limited_data,
        'significant_days': significant_days,
    }
