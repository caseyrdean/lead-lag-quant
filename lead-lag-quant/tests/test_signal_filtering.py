"""Regression tests for signal filtering bugs (BUGFIX-03, BUGFIX-04).

test_signals_exclude_inactive: signals for is_active=0 pairs must never be
returned by get_unprocessed_signals (BUGFIX-03).

test_reactivation_guard: signals generated before a pair's reactivated_at
must be excluded; signals generated after must be included (BUGFIX-04).
"""

from datetime import datetime, timedelta, timezone

from paper_trading.db import get_unprocessed_signals


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_pair(conn, leader, follower, is_active=1, reactivated_at=None):
    conn.execute(
        "INSERT INTO ticker_pairs (leader, follower, is_active, reactivated_at) "
        "VALUES (?, ?, ?, ?)",
        (leader, follower, is_active, reactivated_at),
    )
    conn.commit()


def _insert_signal(conn, ticker_a, ticker_b, generated_at=None, signal_date=None):
    if generated_at is None:
        generated_at = _now_utc()
    if signal_date is None:
        signal_date = generated_at[:10]  # YYYY-MM-DD portion
    conn.execute(
        """
        INSERT INTO signals
            (ticker_a, ticker_b, signal_date, optimal_lag, window_length,
             correlation_strength, stability_score, regime_state,
             adjustment_policy_id, direction, expected_target,
             invalidation_threshold, sizing_tier, flow_map_entry, generated_at)
        VALUES
            (?, ?, ?, 2, 60, 0.75, 80.0, 'trending',
             'policy_a', 'long', 0.02, 0.03, 'half',
             'test signal', ?)
        """,
        (ticker_a, ticker_b, signal_date, generated_at),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# BUGFIX-03: Inactive pair signals must be excluded
# ---------------------------------------------------------------------------


def test_signals_exclude_inactive(tmp_db):
    """get_unprocessed_signals must not return signals for is_active=0 pairs."""
    # Active pair
    _insert_pair(tmp_db, "SPY", "QQQ", is_active=1)
    # Inactive (soft-deleted) pair
    _insert_pair(tmp_db, "AAPL", "MSFT", is_active=0)

    now = _now_utc()
    _insert_signal(tmp_db, "SPY", "QQQ", generated_at=now)
    _insert_signal(tmp_db, "AAPL", "MSFT", generated_at=now)

    results = get_unprocessed_signals(tmp_db)

    assert len(results) == 1, f"Expected 1 signal, got {len(results)}: {results}"
    assert results[0]["ticker_a"] == "SPY"
    assert results[0]["ticker_b"] == "QQQ"


# ---------------------------------------------------------------------------
# BUGFIX-04: Stale pre-reactivation signals must be excluded
# ---------------------------------------------------------------------------


def test_reactivation_guard(tmp_db):
    """Signals before reactivated_at are excluded; signals after are included."""
    now = datetime.now(timezone.utc)
    reactivated_at = now.isoformat()

    # Stale: 2 days ago; fresh: tomorrow — ensures distinct signal_dates for UNIQUE constraint
    stale_time = (now - timedelta(days=2)).isoformat()
    fresh_time = (now + timedelta(days=1)).isoformat()
    stale_date = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    fresh_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # Pair reactivated now
    _insert_pair(tmp_db, "SPY", "QQQ", is_active=1, reactivated_at=reactivated_at)

    # Stale signal — generated 2 days BEFORE reactivation
    _insert_signal(tmp_db, "SPY", "QQQ", generated_at=stale_time, signal_date=stale_date)

    results = get_unprocessed_signals(tmp_db)
    assert len(results) == 0, (
        f"Stale signal should be filtered out, got: {results}"
    )

    # Fresh signal — generated 1 day AFTER reactivation
    _insert_signal(tmp_db, "SPY", "QQQ", generated_at=fresh_time, signal_date=fresh_date)

    results = get_unprocessed_signals(tmp_db)
    assert len(results) == 1, (
        f"Fresh signal should be returned, got: {results}"
    )
    assert results[0]["ticker_a"] == "SPY"
    assert results[0]["ticker_b"] == "QQQ"
