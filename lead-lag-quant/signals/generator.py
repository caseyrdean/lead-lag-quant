"""Signal generation with hard gate enforcement (ENGINE-03, SIGNAL-01, SIGNAL-02).

STATISTICAL THRESHOLDS:

  Correlation (|r|):
    ≥ 0.30 → weak but potentially usable
    ≥ 0.65 → strong — gate minimum
    ≥ 0.70 → strong, ideal

  Stability score (0-100):
    ≥ 40 → weak but potentially usable
    ≥ 70 → strong — gate minimum
    ≥ 85 → strong, ideal

SIZING TIERS (SIGNAL-01) -- stability_score only:
  'full':    stability_score > 85  (high confidence)
  'half':    stability_score > 70  (passes gate — moderate to strong)
  'quarter': stability_score <= 70 (at gate boundary — kept for completeness)

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
import numpy as np
import pandas as pd
from utils.logging import get_logger

STABILITY_THRESHOLD: float = 70.0      # ENGINE-03 hard gate minimum (was 50.0)
CORRELATION_THRESHOLD: float = 0.65   # ENGINE-03 hard gate minimum (was 0.50)

# Sizing tier thresholds (stability_score only)
_SIZING_FULL_THRESHOLD: float = 85.0    # stability > 85 -> 'full'
_SIZING_HALF_THRESHOLD: float = 70.0    # stability > 70 -> 'half' (at gate level)
_EXPECTED_TARGET_LOOKBACK = 120  # days of lagged_returns history for mean return
_INVALIDATION_LOOKBACK = 60      # days of leader returns for mean |1d return|
_INVALIDATION_MULTIPLIER = 2.0   # invalidation = 2x mean absolute 1d return


def passes_gate(stability_score: float, correlation_strength: float) -> bool:
    """ENGINE-03 hard gate. Both conditions must be satisfied.

    stability_score > 70 AND abs(correlation_strength) > 0.65

    The absolute value is used for correlation so that both long (positive) and
    short (negative) signals pass the strength requirement. Direction is
    determined separately by the sign.
    """
    return stability_score > STABILITY_THRESHOLD and abs(correlation_strength) > CORRELATION_THRESHOLD


def determine_sizing_tier(stability_score: float) -> str:
    """Map stability score to sizing tier (SIGNAL-01).

    Tier breakpoints (strict >):
      'full':    stability_score > 85   (high confidence)
      'half':    stability_score > 70   (passes gate — moderate to strong)
      'quarter': stability_score <= 70  (at gate boundary — kept for completeness)
    """
    if stability_score > _SIZING_FULL_THRESHOLD:
        return 'full'
    if stability_score > _SIZING_HALF_THRESHOLD:
        return 'half'
    return 'quarter'


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


def compute_rs_slope(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
    lookback_sessions: int = 5,
) -> float | None:
    """Slope of the follower RS series over the last lookback_sessions, normalized by RS std dev.

    Queries features_relative_strength for the pair, fetches 3x lookback rows
    for a stable std dev, then computes np.polyfit slope on the last lookback_sessions
    values in chronological order.

    Returns:
        slope / rs_std when rs_std > 0 and >= 10 full rows are available.
        float(slope) un-normalized when fewer than 10 rows exist or rs_std == 0.
        None when fewer than lookback_sessions rows are available.
    """
    fetch_limit = lookback_sessions * 3
    df = pd.read_sql_query(
        """
        SELECT rs_value
        FROM features_relative_strength
        WHERE ticker_a=? AND ticker_b=?
          AND rs_value IS NOT NULL
        ORDER BY trading_day DESC
        LIMIT ?
        """,
        conn,
        params=(ticker_a, ticker_b, fetch_limit),
    )
    if df.empty or len(df) < lookback_sessions:
        return None

    # Reverse to chronological order; take the last lookback_sessions as the recent window
    df = df.iloc[::-1].reset_index(drop=True)
    recent = df['rs_value'].iloc[-lookback_sessions:].values

    slope = np.polyfit(np.arange(len(recent)), recent, 1)[0]

    # Normalize by std dev computed from the full fetched series (requires >= 10 rows)
    if len(df) >= 10:
        rs_std = float(df['rs_value'].std())
        if rs_std > 0:
            return float(slope / rs_std)
    return float(slope)


def compute_leader_baseline_return(
    conn: sqlite3.Connection,
    ticker_a: str,
    optimal_lag: int,
    lookback_days: int = 120,
) -> float | None:
    """Historical mean lagged return for the leader ticker over the last lookback_days.

    Queries features_lagged_returns for ticker_a at lag=optimal_lag.
    The date window is anchored at the MAX trading_day for that ticker.

    Returns:
        float mean of return_value, or None if no rows found.
    """
    anchor_row = conn.execute(
        "SELECT MAX(trading_day) FROM features_lagged_returns WHERE ticker=? AND lag=?",
        (ticker_a, optimal_lag),
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
          AND trading_day >= date(?, ?)
        """,
        conn,
        params=(ticker_a, optimal_lag, anchor, f'-{lookback_days} days'),
    )
    if df.empty:
        return None
    return float(df['return_value'].mean())


def compute_response_window(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
) -> float | None:
    """Average number of trading sessions the pair spends in BUY state per cycle.

    Scans signal_transitions for the pair in chronological order, identifies
    complete BUY→non-BUY cycles, counts trading sessions (via normalized_bars)
    for each complete cycle, and returns the mean.

    Returns:
        float mean session count if >= 2 complete BUY→exit cycles exist.
        None on bootstrap (no history) or fewer than 2 complete cycles.
    """
    df = pd.read_sql_query(
        """
        SELECT to_action, transitioned_at
        FROM signal_transitions
        WHERE ticker_a=? AND ticker_b=?
        ORDER BY transitioned_at ASC
        """,
        conn,
        params=(ticker_a, ticker_b),
    )
    if df.empty:
        return None

    durations = []
    buy_entry_at = None

    for i, row in df.iterrows():
        action = row['to_action']
        ts = row['transitioned_at']
        # Extract date portion only (strip time component)
        date_part = ts[:10] if ts and len(ts) >= 10 else ts

        if action == 'BUY':
            if buy_entry_at is None:
                buy_entry_at = date_part
        else:
            if buy_entry_at is not None:
                # Complete BUY→exit cycle: count trading sessions for ticker_b
                count_row = conn.execute(
                    """
                    SELECT COUNT(DISTINCT trading_day)
                    FROM normalized_bars
                    WHERE ticker=?
                      AND trading_day > ?
                      AND trading_day <= ?
                    """,
                    (ticker_b, buy_entry_at, date_part),
                ).fetchone()
                session_count = count_row[0] if count_row else 0
                durations.append(session_count)
                buy_entry_at = None

    if len(durations) < 2:
        return None
    return float(sum(durations) / len(durations))


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
        # Outperformance signal enhancement fields (v1.1) — populated by plan 07-02
        'action': None,
        'response_window': None,
        'rs_acceleration': None,
        'leader_rs_deceleration': None,
        'outperformance_margin': None,
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
