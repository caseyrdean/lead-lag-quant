"""RSI-v2 five-component stability score (ENGINE-02).

Components and weights (Claude's discretion per STATE.md blocker):
  lag_persistence_consistency  30%  -- lag is the same across rolling windows
  walk_forward_oos             25%  -- lag works on held-out validation window
  rolling_window_confirmation  20%  -- |correlation| > threshold on recent windows
  regime_stability             15%  -- stable regime context (requires regime classification first)
  lag_drift_penalty            10%  -- low std of best-lag estimate over time

CRITICAL ORDERING: regime must be classified BEFORE compute_stability_score() is called
because regime_stability_score() is an input to the composite. Call classify_regime()
first in the pipeline orchestrator.

All sub-score functions return float 0-100. Empty inputs return 0.0 (not None, not crash).
Window anchoring: always anchor to MAX(trading_day) for the pair, never datetime('now'),
to avoid OOS score instability on weekends.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger

# RSI-v2 component weights (must sum to 1.0)
WEIGHTS: dict[str, float] = {
    'lag_persistence':      0.30,
    'walk_forward_oos':     0.25,
    'rolling_confirmation': 0.20,
    'regime_stability':     0.15,
    'lag_drift':            0.10,
}

_LOOKBACK_DAYS = 120
_OOS_VALIDATION_DAYS = 30
_ROLLING_CONFIRMATION_DAYS = 60
_ROLLING_CONFIRMATION_THRESHOLD = 0.30
_LAG_DRIFT_MAX_STD = 3.0  # std of 3 lags across -5..+5 range -> score 0


def _get_anchor(conn: sqlite3.Connection, ticker_a: str, ticker_b: str) -> str | None:
    """Return MAX(trading_day) for the pair where data exists. None if no data."""
    row = conn.execute(
        "SELECT MAX(trading_day) FROM features_cross_correlation "
        "WHERE ticker_a=? AND ticker_b=? AND correlation IS NOT NULL",
        (ticker_a, ticker_b),
    ).fetchone()
    return row[0] if row else None


def lag_persistence_score(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    optimal_lag: int,
    lookback_days: int = _LOOKBACK_DAYS,
) -> float:
    """Component 1 (30%): Fraction of days where the optimal lag is the single best lag.

    Per day, identify which lag has the highest |correlation| among is_significant=1 rows.
    Score = (days where best lag == optimal_lag) / total days * 100.
    """
    anchor = _get_anchor(conn, ticker_a, ticker_b)
    if anchor is None:
        return 0.0

    sql = """
        SELECT trading_day, lag, correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=?
          AND is_significant=1
          AND correlation IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
        ORDER BY trading_day ASC
    """
    df = pd.read_sql_query(sql, conn, params=(ticker_a, ticker_b, anchor, f'-{lookback_days}'))
    if df.empty:
        return 0.0

    # Per day: find the lag with max |correlation|
    df['abs_corr'] = df['correlation'].abs()
    daily_best = df.loc[df.groupby('trading_day')['abs_corr'].idxmax(), ['trading_day', 'lag']]
    match_pct = (daily_best['lag'] == optimal_lag).mean()
    return float(match_pct * 100.0)


def walk_forward_oos_score(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    optimal_lag: int,
    validation_days: int = _OOS_VALIDATION_DAYS,
) -> float:
    """Component 2 (25%): Out-of-sample validation correlation at optimal lag.

    Window structure (anchored to MAX trading day, not datetime('now')):
      Estimation: days [-155, -35] relative to anchor  (120 days)
      Gap:        days [-35, -30] relative to anchor   (5 days)
      Validation: days [-30, 0]  relative to anchor    (30 days)

    Score = min(mean(|correlation|) in validation window * 100, 100).
    Returns 0.0 if fewer than 15 validation observations exist.
    """
    anchor = _get_anchor(conn, ticker_a, ticker_b)
    if anchor is None:
        return 0.0

    sql = """
        SELECT correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=?
          AND lag=?
          AND correlation IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
          AND trading_day <= ?
    """
    df = pd.read_sql_query(
        sql, conn,
        params=(ticker_a, ticker_b, optimal_lag, anchor, f'-{validation_days}', anchor)
    )
    if len(df) < 15:
        return 0.0
    val_corr = float(df['correlation'].abs().mean())
    return min(val_corr * 100.0, 100.0)


def rolling_confirmation_score(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    optimal_lag: int,
    lookback_days: int = _ROLLING_CONFIRMATION_DAYS,
    threshold: float = _ROLLING_CONFIRMATION_THRESHOLD,
) -> float:
    """Component 3 (20%): Fraction of recent windows where |correlation| > threshold.

    Looks at last 60 days at the optimal lag (ignores Bonferroni significance here --
    we want to see if the relationship is consistently present even if not always significant).
    Score = (rows where |correlation| >= threshold) / total rows * 100.
    """
    anchor = _get_anchor(conn, ticker_a, ticker_b)
    if anchor is None:
        return 0.0

    sql = """
        SELECT correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=?
          AND lag=?
          AND correlation IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
    """
    df = pd.read_sql_query(
        sql, conn,
        params=(ticker_a, ticker_b, optimal_lag, anchor, f'-{lookback_days}')
    )
    if df.empty:
        return 0.0
    above = (df['correlation'].abs() >= threshold).mean()
    return float(above * 100.0)


def regime_stability_score(regime_state: str) -> float:
    """Component 4 (15%): Score based on current regime classification.

    Bull/Base -> 100 (stable, reliable signal context)
    Bear       -> 50  (elevated noise, signals less reliable)
    Failure    -> 0   (do not generate signals in Failure regime)

    MUST be called after classify_regime() in the pipeline.
    """
    return {'Bull': 100.0, 'Base': 100.0, 'Bear': 50.0, 'Failure': 0.0}.get(
        regime_state, 0.0
    )


def lag_drift_score(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    lookback_days: int = _LOOKBACK_DAYS,
) -> float:
    """Component 5 (10%): Penalizes unstable lag estimation over time (inverted std).

    Per day, find the lag with highest |correlation| among is_significant=1 rows.
    Compute std of those daily best-lag values over lookback.
    std=0 -> score 100; std >= _LAG_DRIFT_MAX_STD -> score 0; linear between.
    """
    anchor = _get_anchor(conn, ticker_a, ticker_b)
    if anchor is None:
        return 0.0

    sql = """
        SELECT trading_day, lag, correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=?
          AND is_significant=1
          AND correlation IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
    """
    df = pd.read_sql_query(sql, conn, params=(ticker_a, ticker_b, anchor, f'-{lookback_days}'))
    if df.empty:
        return 0.0

    df['abs_corr'] = df['correlation'].abs()
    daily_best = df.loc[df.groupby('trading_day')['abs_corr'].idxmax(), 'lag']
    if len(daily_best) < 2:
        return 0.0

    drift_std = float(daily_best.std())
    if pd.isna(drift_std):
        return 0.0
    score = max(0.0, 100.0 - (drift_std / _LAG_DRIFT_MAX_STD) * 100.0)
    return score


def compute_stability_score(sub_scores: dict[str, float]) -> float:
    """Combine five RSI-v2 sub-scores into a scalar 0-100 using fixed weights.

    sub_scores must have keys: lag_persistence, walk_forward_oos,
    rolling_confirmation, regime_stability, lag_drift.

    Raises KeyError if any required key is missing.
    """
    return sum(WEIGHTS[k] * sub_scores[k] for k in WEIGHTS)
