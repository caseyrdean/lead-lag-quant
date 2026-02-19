"""Tests for ENGINE-02 RSI-v2 sub-scores and composite stability scorer.

Covers: WEIGHTS constant, compute_stability_score(), regime_stability_score(),
and all four DB-backed sub-score functions with empty and populated inputs.
"""
import pytest
from leadlag_engine.stability import (
    WEIGHTS,
    compute_stability_score,
    lag_persistence_score,
    walk_forward_oos_score,
    rolling_confirmation_score,
    regime_stability_score,
    lag_drift_score,
)


# ---------------------------------------------------------------------------
# Helper: insert xcorr rows
# ---------------------------------------------------------------------------
def _insert_xcorr(conn, ticker_a, ticker_b, lag, correlation, trading_day,
                  is_significant=1, p_value=0.01):
    conn.execute(
        """
        INSERT OR REPLACE INTO features_cross_correlation
            (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant),
    )
    conn.commit()


def _insert_many(conn, ticker_a, ticker_b, lag, correlation, count,
                 is_significant=1, start_offset=0):
    """Insert `count` rows spreading across months starting at 2024-01."""
    for i in range(count):
        idx = i + start_offset
        month = (idx // 28) + 1
        dom = (idx % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        conn.execute(
            """
            INSERT OR REPLACE INTO features_cross_correlation
                (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker_a, ticker_b, day, lag, correlation, 0.01, is_significant),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Test 1: WEIGHTS constant verification -- sum must equal 1.0
# ---------------------------------------------------------------------------
def test_weights_sum_to_one():
    total = sum(WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"WEIGHTS sum = {total}, expected 1.0"


def test_weights_keys():
    expected_keys = {'lag_persistence', 'walk_forward_oos', 'rolling_confirmation',
                     'regime_stability', 'lag_drift'}
    assert set(WEIGHTS.keys()) == expected_keys


def test_weights_individual_values():
    assert abs(WEIGHTS['lag_persistence'] - 0.30) < 1e-9
    assert abs(WEIGHTS['walk_forward_oos'] - 0.25) < 1e-9
    assert abs(WEIGHTS['rolling_confirmation'] - 0.20) < 1e-9
    assert abs(WEIGHTS['regime_stability'] - 0.15) < 1e-9
    assert abs(WEIGHTS['lag_drift'] - 0.10) < 1e-9


# ---------------------------------------------------------------------------
# Test 2: compute_stability_score correct weighted average
# ---------------------------------------------------------------------------
def test_compute_stability_score_all_100():
    sub = {
        'lag_persistence': 100.0,
        'walk_forward_oos': 100.0,
        'rolling_confirmation': 100.0,
        'regime_stability': 100.0,
        'lag_drift': 100.0,
    }
    result = compute_stability_score(sub)
    assert abs(result - 100.0) < 1e-9


def test_compute_stability_score_all_zero():
    sub = {
        'lag_persistence': 0.0,
        'walk_forward_oos': 0.0,
        'rolling_confirmation': 0.0,
        'regime_stability': 0.0,
        'lag_drift': 0.0,
    }
    result = compute_stability_score(sub)
    assert abs(result - 0.0) < 1e-9


def test_compute_stability_score_weighted_mixed():
    # Only lag_persistence=100, rest=0 => 0.30 * 100 = 30.0
    sub = {
        'lag_persistence': 100.0,
        'walk_forward_oos': 0.0,
        'rolling_confirmation': 0.0,
        'regime_stability': 0.0,
        'lag_drift': 0.0,
    }
    result = compute_stability_score(sub)
    assert abs(result - 30.0) < 1e-9


def test_compute_stability_score_missing_key_raises():
    with pytest.raises(KeyError):
        compute_stability_score({'lag_persistence': 50.0})


# ---------------------------------------------------------------------------
# Test 3: regime_stability_score values
# ---------------------------------------------------------------------------
def test_regime_stability_score_bull():
    assert regime_stability_score("Bull") == 100.0


def test_regime_stability_score_base():
    assert regime_stability_score("Base") == 100.0


def test_regime_stability_score_bear():
    assert regime_stability_score("Bear") == 50.0


def test_regime_stability_score_failure():
    assert regime_stability_score("Failure") == 0.0


def test_regime_stability_score_unknown():
    assert regime_stability_score("Unknown") == 0.0
    assert regime_stability_score("") == 0.0
    assert regime_stability_score("BULL") == 0.0  # case-sensitive


# ---------------------------------------------------------------------------
# Test 4: lag_persistence_score returns 0.0 on empty database (no crash)
# ---------------------------------------------------------------------------
def test_lag_persistence_score_empty_db(tmp_db):
    result = lag_persistence_score(tmp_db, "AAA", "BBB", optimal_lag=2)
    assert result == 0.0


# ---------------------------------------------------------------------------
# Test 5: walk_forward_oos_score returns 0.0 when fewer than 15 validation rows
# ---------------------------------------------------------------------------
def test_walk_forward_oos_score_empty_db(tmp_db):
    result = walk_forward_oos_score(tmp_db, "AAA", "BBB", optimal_lag=2)
    assert result == 0.0


def test_walk_forward_oos_score_insufficient_rows(tmp_db):
    # Insert 10 rows at lag=2 (below 15 minimum threshold)
    _insert_many(tmp_db, "AAA", "BBB", lag=2, correlation=0.70, count=10)
    result = walk_forward_oos_score(tmp_db, "AAA", "BBB", optimal_lag=2)
    assert result == 0.0


# ---------------------------------------------------------------------------
# Test 6: rolling_confirmation_score returns 0.0 on empty database
# ---------------------------------------------------------------------------
def test_rolling_confirmation_score_empty_db(tmp_db):
    result = rolling_confirmation_score(tmp_db, "AAA", "BBB", optimal_lag=2)
    assert result == 0.0


# ---------------------------------------------------------------------------
# Test 7: lag_drift_score returns 0.0 on empty database
# ---------------------------------------------------------------------------
def test_lag_drift_score_empty_db(tmp_db):
    result = lag_drift_score(tmp_db, "AAA", "BBB")
    assert result == 0.0


def test_lag_drift_score_single_row(tmp_db):
    # With only 1 row, len(daily_best) < 2, should return 0.0
    _insert_xcorr(tmp_db, "AAA", "BBB", lag=2, correlation=0.70, trading_day="2024-01-15")
    result = lag_drift_score(tmp_db, "AAA", "BBB")
    assert result == 0.0


# ---------------------------------------------------------------------------
# Test 8: lag_persistence_score returns ~100 when optimal_lag is always the best lag
# ---------------------------------------------------------------------------
def test_lag_persistence_score_perfect(tmp_db):
    # Insert 40 days where lag=2 always has the highest |correlation|
    # Other lags have lower correlation
    for i in range(40):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        # lag=2 wins with 0.80
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("PP", "QQ", day, 2, 0.80, 0.01, 1),
        )
        # lag=1 has lower correlation
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("PP", "QQ", day, 1, 0.40, 0.05, 1),
        )
    tmp_db.commit()

    result = lag_persistence_score(tmp_db, "PP", "QQ", optimal_lag=2)
    # All 40 days, lag=2 is the best -> 100%
    assert abs(result - 100.0) < 1e-6


def test_lag_persistence_score_half(tmp_db):
    # 20 days where lag=2 wins, 20 days where lag=1 wins
    for i in range(20):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("PP", "RR", day, 2, 0.80, 0.01, 1),
        )
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("PP", "RR", day, 1, 0.30, 0.05, 1),
        )
    for i in range(20):
        month = ((i + 20) // 28) + 1
        dom = ((i + 20) % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("PP", "RR", day, 2, 0.30, 0.05, 1),
        )
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("PP", "RR", day, 1, 0.80, 0.01, 1),
        )
    tmp_db.commit()

    result = lag_persistence_score(tmp_db, "PP", "RR", optimal_lag=2)
    assert abs(result - 50.0) < 1.0  # approximately 50%


# ---------------------------------------------------------------------------
# Test 9: rolling_confirmation_score returns ~100 when all correlations above threshold
# ---------------------------------------------------------------------------
def test_rolling_confirmation_score_all_above_threshold(tmp_db):
    # Insert 60 rows with correlation=0.80 (well above default threshold 0.30)
    _insert_many(tmp_db, "CC", "DD", lag=3, correlation=0.80, count=60)
    result = rolling_confirmation_score(tmp_db, "CC", "DD", optimal_lag=3)
    assert abs(result - 100.0) < 1e-6


def test_rolling_confirmation_score_none_above_threshold(tmp_db):
    # Insert 60 rows with correlation=0.10 (below default threshold 0.30)
    _insert_many(tmp_db, "EE", "FF", lag=3, correlation=0.10, count=60)
    result = rolling_confirmation_score(tmp_db, "EE", "FF", optimal_lag=3)
    assert result == 0.0


# ---------------------------------------------------------------------------
# Test 10: walk_forward_oos_score with sufficient validation rows returns > 0
# ---------------------------------------------------------------------------
def test_walk_forward_oos_score_with_data(tmp_db):
    # Insert 20 rows at lag=1 with correlation=0.70 (>= 15 rows needed)
    _insert_many(tmp_db, "GG", "HH", lag=1, correlation=0.70, count=20)
    result = walk_forward_oos_score(tmp_db, "GG", "HH", optimal_lag=1)
    # 0.70 * 100 = 70.0
    assert result > 0.0
    assert result <= 100.0
    assert abs(result - 70.0) < 1e-6


# ---------------------------------------------------------------------------
# Test 11: lag_drift_score returns 100 when lag is perfectly stable (zero std)
# ---------------------------------------------------------------------------
def test_lag_drift_score_perfectly_stable(tmp_db):
    # All 30 days: lag=2 always dominates (zero drift)
    for i in range(30):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("II", "JJ", day, 2, 0.80, 0.01, 1),
        )
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("II", "JJ", day, 1, 0.30, 0.05, 1),
        )
    tmp_db.commit()

    result = lag_drift_score(tmp_db, "II", "JJ")
    # std=0, so score=100
    assert abs(result - 100.0) < 1e-6
