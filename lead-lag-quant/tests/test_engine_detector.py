"""Tests for ENGINE-01 optimal lag detection.

Covers: detect_optimal_lag() with empty DB, insufficient data,
correct lag selection, signed correlation strength, NULL filtering,
and anchor-date stability.
"""
import pytest
from leadlag_engine.detector import detect_optimal_lag


def _insert_xcorr(conn, ticker_a, ticker_b, lag, correlation, trading_day, is_significant=1):
    """Helper: insert a single features_cross_correlation row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO features_cross_correlation
            (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (ticker_a, ticker_b, trading_day, lag, correlation, 0.01, is_significant),
    )
    conn.commit()


def _insert_many_xcorr(conn, ticker_a, ticker_b, lag, correlation, start_day_num, count,
                       is_significant=1):
    """Helper: insert `count` rows for a given lag starting from day start_day_num."""
    for i in range(count):
        day = f"2024-{(start_day_num + i) // 100 + 1:02d}-{((start_day_num + i) % 100) + 1:02d}"
        # Use simple date generation: YYYY-01-DD (days 0-89 within jan-mar range)
        day = f"2024-01-{(i + 1):02d}" if count <= 31 else None
        if day is None:
            # For >31 rows, spread across months
            month = (i // 28) + 1
            dom = (i % 28) + 1
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
# Test 1: Empty database returns None (no data at all)
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_empty_db(tmp_db):
    result = detect_optimal_lag(tmp_db, "AAA", "BBB")
    assert result is None


# ---------------------------------------------------------------------------
# Test 2: Returns None when all lags have fewer than 30 significant days
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_insufficient_days(tmp_db):
    # Insert only 10 significant rows at lag=2 (below 30 threshold)
    for i in range(10):
        _insert_xcorr(tmp_db, "AAA", "BBB", lag=2, correlation=0.8,
                      trading_day=f"2024-01-{i+1:02d}")
    result = detect_optimal_lag(tmp_db, "AAA", "BBB")
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: Returns correct optimal_lag when one lag dominates by count
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_correct_lag_selection(tmp_db):
    # Insert 35 rows at lag=2 with correlation=0.75
    # Insert 10 rows at lag=1 with correlation=0.90 (higher corr but below 30 min)
    # Lag=2 wins: 35 >= 30, lag=1 loses: 10 < 30
    for i in range(35):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        conn = tmp_db
        conn.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("AAA", "BBB", day, 2, 0.75, 0.01, 1),
        )
    for i in range(10):
        day = f"2024-04-{i+1:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("AAA", "BBB", day, 1, 0.90, 0.01, 1),
        )
    tmp_db.commit()

    result = detect_optimal_lag(tmp_db, "AAA", "BBB")
    assert result is not None
    assert result["optimal_lag"] == 2
    assert abs(result["correlation_strength"] - 0.75) < 1e-6


# ---------------------------------------------------------------------------
# Test 4: correlation_strength is signed (negative for inverse pairs)
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_negative_correlation_strength(tmp_db):
    # Insert 35 rows with negative correlation at lag=3
    for i in range(35):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("INV", "OPP", day, 3, -0.65, 0.01, 1),
        )
    tmp_db.commit()

    result = detect_optimal_lag(tmp_db, "INV", "OPP")
    assert result is not None
    assert result["optimal_lag"] == 3
    assert result["correlation_strength"] < 0  # must be negative, not abs
    assert abs(result["correlation_strength"] - (-0.65)) < 1e-6


# ---------------------------------------------------------------------------
# Test 5: Ignores NULL correlation rows even when is_significant=1
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_ignores_null_correlation(tmp_db):
    # 25 rows with is_significant=1 but NULL correlation (below 30 threshold after filtering)
    for i in range(25):
        day = f"2024-01-{i+1:02d}" if i < 25 else f"2024-02-{i-24:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("XXX", "YYY", f"2024-01-{i+1:02d}" if i < 25 else f"2024-02-{i-24:02d}",
             2, None, None, 1),
        )
    # Add 5 real rows (still below 30 threshold after NULL filtering)
    for i in range(5):
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("XXX", "YYY", f"2024-03-{i+1:02d}", 2, 0.70, 0.01, 1),
        )
    tmp_db.commit()

    # Should return None: only 5 non-null rows at lag=2, less than 30
    result = detect_optimal_lag(tmp_db, "XXX", "YYY")
    assert result is None


# ---------------------------------------------------------------------------
# Test 6: Result is anchored to MAX(trading_day), stable regardless of run date
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_anchor_to_max_trading_day(tmp_db):
    # Insert 35 rows well in the past -- result should not depend on today's date
    for i in range(35):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2020-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("SPY", "QQQ", day, 1, 0.80, 0.005, 1),
        )
    tmp_db.commit()

    result = detect_optimal_lag(tmp_db, "SPY", "QQQ")
    assert result is not None
    assert result["optimal_lag"] == 1
    assert abs(result["correlation_strength"] - 0.80) < 1e-6


# ---------------------------------------------------------------------------
# Test 7: Selects lag with highest |median correlation| when multiple lags qualify
# ---------------------------------------------------------------------------
def test_detect_optimal_lag_selects_highest_abs_median_corr(tmp_db):
    # Lag=2: 35 rows, median corr=0.60
    # Lag=5: 35 rows, median corr=0.85  <-- should win
    for i in range(35):
        month = (i // 28) + 1
        dom = (i % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("AA", "BB", day, 2, 0.60, 0.01, 1),
        )
    for i in range(35):
        month = ((i + 4) // 28) + 1
        dom = ((i + 4) % 28) + 1
        day = f"2024-{month:02d}-{dom:02d}"
        tmp_db.execute(
            """INSERT OR REPLACE INTO features_cross_correlation
               (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("AA", "BB", day, 5, 0.85, 0.01, 1),
        )
    tmp_db.commit()

    result = detect_optimal_lag(tmp_db, "AA", "BB")
    assert result is not None
    assert result["optimal_lag"] == 5
    assert abs(result["correlation_strength"] - 0.85) < 1e-6
