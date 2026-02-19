"""Signal generation with hard gate enforcement (ENGINE-03, SIGNAL-01, SIGNAL-02).

CRITICAL THRESHOLDS (hard gate, no exceptions, no overrides per ENGINE-03):
  STABILITY_THRESHOLD = 70.0   -- stability_score must be STRICTLY greater than 70
  CORRELATION_THRESHOLD = 0.65 -- correlation_strength must be STRICTLY greater than 0.65

SIZING TIERS (SIGNAL-01):
  stability_score > 85  -> 'full'
  stability_score > 70  -> 'half'   (70 < score <= 85)
  (scores <= 70 never reach sizing -- gate blocks them)

DIRECTION (from correlation sign):
  correlation_strength > 0  -> 'long'  (follower moves same direction as leader)
  correlation_strength < 0  -> 'short' (follower moves opposite to leader)

FLOW MAP ENTRY (SIGNAL-02) -- LAG SIGN CONVENTION from features/cross_correlation.py:
  Positive optimal_lag: ticker_b leads ticker_a  (b_t predicts a_{t+lag})
  Negative optimal_lag: ticker_a leads ticker_b  (a_t predicts b_{t+|lag|})
  Lag 0: contemporaneous

  This is the ACTUAL convention from _pearsonr_at_lag() in cross_correlation.py.
  Positive lag: a_slice = a[lag:], b_slice = b[:-lag]  -> b leads a temporally.
  Build the flow map entry accordingly.

ADJUSTMENT POLICY: adjustment_policy_id = 'policy_a' on every signal record (locked decision).

IMMUTABILITY: generated_at is set on first insert and NEVER overwritten on conflict.
  The upsert in leadlag_engine/db.py enforces this -- generator just sets it on creation.
"""
import sqlite3
from datetime import datetime, timezone
import pandas as pd
from utils.logging import get_logger

STABILITY_THRESHOLD: float = 70.0
CORRELATION_THRESHOLD: float = 0.65

_SIZING_FULL_THRESHOLD: float = 85.0
_EXPECTED_TARGET_LOOKBACK = 120  # days of lagged_returns history for mean return
_INVALIDATION_LOOKBACK = 60      # days of leader returns for mean |1d return|
_INVALIDATION_MULTIPLIER = 2.0   # invalidation = 2x mean absolute 1d return


def passes_gate(stability_score: float, correlation_strength: float) -> bool:
    """ENGINE-03 hard gate. Both conditions must be strictly satisfied.

    No exceptions, no overrides -- this is a locked decision.
    stability_score > 70 AND abs(correlation_strength) > 0.65

    The absolute value is used for correlation so that both long (positive) and
    short (negative) signals pass the strength requirement. A correlation of -0.80
    indicates a strong INVERSE relationship and should pass the gate; direction is
    handled separately by the sign.
    """
    return stability_score > STABILITY_THRESHOLD and abs(correlation_strength) > CORRELATION_THRESHOLD


def determine_sizing_tier(stability_score: float) -> str:
    """Map stability_score to sizing tier.

    > 85  -> 'full'
    > 70  -> 'half'
    Gate ensures scores <= 70 never reach this function in normal operation.
    """
    if stability_score > _SIZING_FULL_THRESHOLD:
        return 'full'
    return 'half'


def build_flow_map_entry(ticker_a: str, ticker_b: str, optimal_lag: int) -> str:
    """Construct directed flow map string (SIGNAL-02).

    LAG SIGN CONVENTION (from features/cross_correlation.py _pearsonr_at_lag):
      Positive lag: ticker_b leads ticker_a
      Negative lag: ticker_a leads ticker_b
      Lag 0: contemporaneous

    Example: optimal_lag=+2 -> "CRWV leads NVDA by 2 sessions"
             optimal_lag=-3 -> "NVDA leads CRWV by 3 sessions"
             optimal_lag=0  -> "NVDA coincident with CRWV"
    """
    lag_abs = abs(optimal_lag)
    session_str = f"session{'s' if lag_abs != 1 else ''}"
    if optimal_lag > 0:
        # positive lag: ticker_b leads ticker_a
        return f"{ticker_b} leads {ticker_a} by {lag_abs} {session_str}"
    elif optimal_lag < 0:
        # negative lag: ticker_a leads ticker_b
        return f"{ticker_a} leads {ticker_b} by {lag_abs} {session_str}"
    else:
        return f"{ticker_a} coincident with {ticker_b}"


def compute_expected_target(
    conn: sqlite3.Connection,
    ticker_b: str,
    optimal_lag: int,
    lookback_days: int = _EXPECTED_TARGET_LOOKBACK,
) -> float | None:
    """Historical mean return for the follower during the lag window (SIGNAL-01).

    Queries features_lagged_returns for ticker_b at offset=optimal_lag.
    Returns mean return_value or None if insufficient data.
    """
    anchor_row = conn.execute(
        "SELECT MAX(trading_day) FROM features_lagged_returns WHERE ticker=?",
        (ticker_b,),
    ).fetchone()
    anchor = anchor_row[0] if anchor_row else None
    if anchor is None:
        return None

    df = pd.read_sql_query(
        """
        SELECT return_value
        FROM features_lagged_returns
        WHERE ticker=? AND lag=?
          AND return_value IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
        """,
        conn,
        params=(ticker_b, optimal_lag, anchor, f'-{lookback_days}'),
    )
    if df.empty:
        return None
    return float(df['return_value'].mean())


def compute_invalidation_threshold(
    conn: sqlite3.Connection,
    ticker_a: str,
    lookback_days: int = _INVALIDATION_LOOKBACK,
    multiplier: float = _INVALIDATION_MULTIPLIER,
) -> float | None:
    """Leader reversal threshold for signal invalidation (SIGNAL-01).

    Threshold = multiplier * mean(|1d return|) for the leader over lookback.
    If leader reverses by this amount, the signal is invalidated.
    """
    anchor_row = conn.execute(
        "SELECT MAX(trading_day) FROM returns_policy_a WHERE ticker=?",
        (ticker_a,),
    ).fetchone()
    anchor = anchor_row[0] if anchor_row else None
    if anchor is None:
        return None

    df = pd.read_sql_query(
        """
        SELECT return_1d
        FROM returns_policy_a
        WHERE ticker=?
          AND return_1d IS NOT NULL
          AND trading_day >= date(?, ? || ' days')
        """,
        conn,
        params=(ticker_a, anchor, f'-{lookback_days}'),
    )
    if df.empty:
        return None
    mean_abs_return = float(df['return_1d'].abs().mean())
    return mean_abs_return * multiplier


def generate_signal(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    optimal_lag: int,
    correlation_strength: float,
    stability_score: float,
    regime_state: str,
    signal_date: str,
    data_warning: str | None = None,
) -> dict | None:
    """Generate a full position spec if the signal passes the hard gate (ENGINE-03).

    Returns the signal dict if gate passes and upserts to SQLite.
    Returns None if gate fails (stability_score <= 70 OR correlation_strength <= 0.65).

    adjustment_policy_id is always 'policy_a' -- locked decision.
    generated_at is set once at creation; the upsert in leadlag_engine/db.py
    ensures it is NEVER overwritten if the signal already exists.
    """
    log = get_logger("signals.generator")

    if not passes_gate(stability_score, correlation_strength):
        log.info(
            "signal_gated",
            ticker_a=ticker_a, ticker_b=ticker_b,
            stability_score=round(stability_score, 2),
            correlation_strength=round(correlation_strength, 4),
        )
        return None

    direction = 'long' if correlation_strength > 0 else 'short'
    sizing_tier = determine_sizing_tier(stability_score)
    flow_map_entry = build_flow_map_entry(ticker_a, ticker_b, optimal_lag)
    expected_target = compute_expected_target(conn, ticker_b, optimal_lag)
    invalidation_threshold = compute_invalidation_threshold(conn, ticker_a)

    signal = {
        'ticker_a': ticker_a,
        'ticker_b': ticker_b,
        'signal_date': signal_date,
        'optimal_lag': optimal_lag,
        'window_length': 60,  # matches FEAT-01 rolling window
        'correlation_strength': correlation_strength,
        'stability_score': stability_score,
        'regime_state': regime_state,
        'adjustment_policy_id': 'policy_a',
        'direction': direction,
        'expected_target': expected_target,
        'invalidation_threshold': invalidation_threshold,
        'sizing_tier': sizing_tier,
        'flow_map_entry': flow_map_entry,
        'data_warning': data_warning,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }

    from leadlag_engine.db import upsert_signal, upsert_flow_map
    upsert_signal(conn, signal)
    upsert_flow_map(conn, {
        'ticker_a': ticker_a,
        'ticker_b': ticker_b,
        'direction': direction,
        'optimal_lag': optimal_lag,
        'last_updated': signal['generated_at'],
    })

    log.info(
        "signal_generated",
        ticker_a=ticker_a, ticker_b=ticker_b,
        stability_score=round(stability_score, 2),
        sizing_tier=sizing_tier,
        direction=direction,
        flow_map_entry=flow_map_entry,
    )
    return signal
