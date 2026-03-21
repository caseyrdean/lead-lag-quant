"""Backtest engine — pure Python, SQLite-only reads.

BACKTEST-01: Never imports from ingestion_massive/ or calls PolygonClient.
BACKTEST-02: Filters signals by signal_date range (primary look-ahead bias control).
             Splits filtered with fetched_at <= signal_date when needed.
BACKTEST-03: Returns hit_rate, mean_return_per_trade, annualized_sharpe, max_drawdown.
"""

import math
import sqlite3

import numpy as np
import pandas as pd

from utils.logging import get_logger

log = get_logger("backtest.engine")


def _compute_action_metrics(trade_pairs: list) -> dict:
    """Compute backtest metrics for one action group.

    Args:
        trade_pairs: List of (follower_return, leader_return) tuples for one action.

    Returns:
        Dict with total_trades, winning_trades, hit_rate, mean_return,
        annualized_sharpe, max_drawdown, outperformance_vs_leader.
        Returns zero-dict on empty input.
    """
    ZERO = {
        'total_trades': 0,
        'winning_trades': 0,
        'hit_rate': 0.0,
        'mean_return': 0.0,
        'annualized_sharpe': 0.0,
        'max_drawdown': 0.0,
        'outperformance_vs_leader': 0.0,
    }
    if not trade_pairs:
        return ZERO

    follower_returns = [p[0] for p in trade_pairs if p[0] is not None]

    if not follower_returns:
        return ZERO

    total = len(follower_returns)
    wins = sum(1 for r in follower_returns if r > 0)

    series = pd.Series(follower_returns)
    mean = series.mean()
    std = series.std()

    # Sharpe: annualized using sqrt(252) — matches existing run_backtest formula
    annualized_sharpe = float((mean / std) * math.sqrt(252)) if std != 0 else 0.0

    # Max drawdown: cumsum → cummax pattern — matches existing run_backtest formula
    cumulative = series.cumsum()
    running_peak = cumulative.cummax()
    drawdown = (cumulative - running_peak) / running_peak.replace(0, float('nan'))
    max_drawdown_raw = float(drawdown.min()) if not drawdown.isna().all() else 0.0
    max_drawdown = min(max_drawdown_raw, 0.0)

    # outperformance_vs_leader: mean(follower - leader) for pairs where leader return is available
    paired = [(f, l) for f, l in zip(
        follower_returns,
        [p[1] for p in trade_pairs if p[0] is not None],
    ) if l is not None]
    outperformance = float(np.mean([f - l for f, l in paired])) if paired else 0.0

    return {
        'total_trades': total,
        'winning_trades': wins,
        'hit_rate': wins / total if total > 0 else 0.0,
        'mean_return': float(mean),
        'annualized_sharpe': annualized_sharpe,
        'max_drawdown': max_drawdown,
        'outperformance_vs_leader': outperformance,
    }


def run_backtest(
    conn: sqlite3.Connection,
    leader: str,
    follower: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Run a stored-data backtest for a pair over a date range.

    BACKTEST-01: reads only from SQLite — never calls Polygon API.
    BACKTEST-02: signal_date BETWEEN start_date AND end_date is the primary
                 look-ahead bias control. For any split re-computation scenario,
                 splits are filtered with fetched_at <= signal_date.
    BACKTEST-03: returns hit_rate, mean_return_per_trade, annualized_sharpe,
                 max_drawdown.

    Args:
        conn: Active SQLite connection.
        leader: Leader ticker symbol (ticker_a in signals table).
        follower: Follower ticker symbol (ticker_b in signals table).
        start_date: ISO-8601 start date string, e.g. "2024-01-01".
        end_date: ISO-8601 end date string, e.g. "2024-12-31".

    Returns:
        Dict with keys: leader, follower, start_date, end_date, total_trades,
        winning_trades, hit_rate, mean_return_per_trade, annualized_sharpe,
        max_drawdown, by_action. All numeric metrics are 0.0 and total_trades=0
        when no signals are found in the date range. by_action always contains
        BUY/HOLD/SELL/UNKNOWN keys; missing action groups return zero sub-dicts.
    """
    _zero_action = {
        'total_trades': 0,
        'winning_trades': 0,
        'hit_rate': 0.0,
        'mean_return': 0.0,
        'annualized_sharpe': 0.0,
        'max_drawdown': 0.0,
        'outperformance_vs_leader': 0.0,
    }
    zero = {
        "leader": leader,
        "follower": follower,
        "start_date": start_date,
        "end_date": end_date,
        "total_trades": 0,
        "winning_trades": 0,
        "hit_rate": 0.0,
        "mean_return_per_trade": 0.0,
        "annualized_sharpe": 0.0,
        "max_drawdown": 0.0,
        "by_action": {k: dict(_zero_action) for k in ['BUY', 'HOLD', 'SELL', 'UNKNOWN']},
    }

    # BACKTEST-02: signal_date range filter is the primary look-ahead bias control
    rows = conn.execute(
        """
        SELECT signal_date, optimal_lag, COALESCE(action, 'UNKNOWN') as action
        FROM signals
        WHERE ticker_a = ?
          AND ticker_b = ?
          AND signal_date BETWEEN ? AND ?
        ORDER BY signal_date ASC
        """,
        (leader, follower, start_date, end_date),
    ).fetchall()

    if not rows:
        log.info(
            "backtest_no_signals",
            leader=leader,
            follower=follower,
            start_date=start_date,
            end_date=end_date,
        )
        return zero

    trade_returns = []
    action_trade_tuples = []  # list of (follower_return, leader_return, action)
    for row in rows:
        signal_date = row[0]
        optimal_lag = row[1]
        action = row[2]

        if optimal_lag is None:
            continue

        # Use features_lagged_returns to avoid calendar vs. trading day arithmetic
        # (BACKTEST-01: read-only from SQLite; never call Polygon)
        ret_row = conn.execute(
            """
            SELECT return_value
            FROM features_lagged_returns
            WHERE ticker = ?
              AND trading_day = ?
              AND lag = ?
            """,
            (follower, signal_date, optimal_lag),
        ).fetchone()

        if ret_row is None or ret_row[0] is None:
            # Missing return data — skip this signal (not a bias; data simply absent)
            continue

        follower_return = ret_row[0]
        trade_returns.append(follower_return)

        # Fetch leader return for outperformance_vs_leader calculation
        leader_row = conn.execute(
            """
            SELECT return_value FROM features_lagged_returns
            WHERE ticker=? AND trading_day=? AND lag=?
            """,
            (leader, signal_date, optimal_lag),
        ).fetchone()
        leader_return = leader_row[0] if leader_row and leader_row[0] is not None else None

        action_trade_tuples.append((follower_return, leader_return, action))

    if not trade_returns:
        return zero

    total_trades = len(trade_returns)
    winning_trades = sum(1 for r in trade_returns if r > 0)

    # BACKTEST-03: metric computation mirrors paper_trading/analytics.py
    hit_rate = winning_trades / total_trades

    series = pd.Series(trade_returns)
    mean = series.mean()
    std = series.std()

    mean_return_per_trade = float(mean)
    annualized_sharpe = float((mean / std) * math.sqrt(252)) if std != 0 else 0.0

    # Max drawdown: cumsum → cummax pattern from analytics.py; returned as negative decimal
    cumulative = series.cumsum()
    running_peak = cumulative.cummax()
    drawdown = (cumulative - running_peak) / running_peak.replace(0, float("nan"))
    max_drawdown_raw = float(drawdown.min()) if not drawdown.isna().all() else 0.0
    # Ensure the value is negative (or 0.0); drawdown formula already produces <= 0
    max_drawdown = min(max_drawdown_raw, 0.0)

    # Assemble per-action breakdown — always contains all 4 keys
    by_action = {}
    for action_key in ['BUY', 'HOLD', 'SELL', 'UNKNOWN']:
        group = [(f, l) for f, l, a in action_trade_tuples if a == action_key]
        by_action[action_key] = _compute_action_metrics(group)

    log.info(
        "backtest_complete",
        leader=leader,
        follower=follower,
        total_trades=total_trades,
        hit_rate=hit_rate,
    )

    return {
        "leader": leader,
        "follower": follower,
        "start_date": start_date,
        "end_date": end_date,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "hit_rate": hit_rate,
        "mean_return_per_trade": mean_return_per_trade,
        "annualized_sharpe": annualized_sharpe,
        "max_drawdown": max_drawdown,
        "by_action": by_action,
    }


def xcorr_data(
    conn: sqlite3.Connection,
    leader: str,
    follower: str,
    days: int = 60,
) -> list[dict]:
    """Return cross-correlation heatmap data for a pair over recent trading days.

    Queries features_cross_correlation for the given pair, limited to the last
    `days` calendar days (approximate trading days). Returns empty list if no
    data exists (handles fresh DB gracefully).

    Args:
        conn: Active SQLite connection.
        leader: Leader ticker (ticker_a).
        follower: Follower ticker (ticker_b).
        days: Number of calendar days to look back (default 60).

    Returns:
        List of dicts with keys: lag (int), trading_day (str),
        correlation (float | None), is_significant (int).
        Ordered by trading_day ASC, lag ASC.
    """
    rows = conn.execute(
        """
        SELECT lag, trading_day, correlation, is_significant
        FROM features_cross_correlation
        WHERE ticker_a = ?
          AND ticker_b = ?
          AND trading_day >= date('now', ? || ' days')
          AND correlation IS NOT NULL
        ORDER BY trading_day ASC, lag ASC
        """,
        (leader, follower, f"-{days}"),
    ).fetchall()

    if not rows:
        return []

    return [
        {
            "lag": row[0],
            "trading_day": row[1],
            "correlation": row[2],
            "is_significant": row[3],
        }
        for row in rows
    ]


def regime_state(conn: sqlite3.Connection, follower: str) -> dict:
    """Return the most recent regime state for a follower ticker.

    Joins regime_states with distribution_events for the most recent trading day.
    Returns a sentinel dict when no regime data exists (e.g. pipeline hasn't run).

    Args:
        conn: Active SQLite connection.
        follower: Follower ticker symbol (ticker_b; regime is follower-keyed).

    Returns:
        Dict with keys: regime, trading_day, rs_value, price_vs_21ma,
        price_vs_50ma, atr_ratio, volume_ratio, vwap_rejection_streak,
        is_flagged. Returns sentinel with regime="Unknown" when table is empty.
    """
    sentinel = {
        "regime": "Unknown",
        "trading_day": None,
        "rs_value": None,
        "price_vs_21ma": None,
        "price_vs_50ma": None,
        "atr_ratio": None,
        "volume_ratio": None,
        "vwap_rejection_streak": None,
        "is_flagged": 0,
    }

    row = conn.execute(
        """
        SELECT rs.regime, rs.rs_value, rs.price_vs_21ma, rs.price_vs_50ma,
               rs.atr_ratio, rs.trading_day,
               de.volume_ratio, de.vwap_rejection_streak, de.is_flagged
        FROM regime_states rs
        LEFT JOIN distribution_events de
            ON de.ticker = rs.ticker
           AND de.trading_day = rs.trading_day
        WHERE rs.ticker = ?
        ORDER BY rs.trading_day DESC
        LIMIT 1
        """,
        (follower,),
    ).fetchone()

    if row is None:
        return sentinel

    return {
        "regime": row[0],
        "trading_day": row[5],
        "rs_value": row[1],
        "price_vs_21ma": row[2],
        "price_vs_50ma": row[3],
        "atr_ratio": row[4],
        "volume_ratio": row[6],
        "vwap_rejection_streak": row[7],
        "is_flagged": row[8] if row[8] is not None else 0,
    }
