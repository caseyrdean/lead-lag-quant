"""Integration tests for features.pipeline orchestrator."""
import numpy as np
import pytest

from features.pipeline import compute_features_for_pair, compute_features_for_ticker, compute_features_all_pairs


def _insert_pair_and_returns(conn, leader, follower, n=120):
    """Insert a ticker pair and 1d return data for leader, follower, and SPY."""
    rng = np.random.default_rng(99)

    conn.execute(
        "INSERT INTO ticker_pairs (leader, follower) VALUES (?, ?) "
        "ON CONFLICT(leader, follower) DO NOTHING",
        (leader, follower),
    )

    days = [f"2023-{(i // 20 + 1):02d}-{(i % 20 + 1):02d}" for i in range(n)]
    spy_ret = rng.normal(0, 0.01, n)

    for ticker, returns in [
        (leader, 0.7 * spy_ret + rng.normal(0, 0.005, n)),
        (follower, 0.6 * spy_ret + rng.normal(0, 0.005, n)),
        ("SPY", spy_ret),
    ]:
        rows = [
            (ticker, day, ret, None, None, None, None)
            for day, ret in zip(days, returns)
        ]
        conn.executemany(
            """
            INSERT INTO returns_policy_a
                (ticker, trading_day, return_1d, return_5d, return_10d,
                 return_20d, return_60d, adjustment_policy_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'policy_a')
            ON CONFLICT(ticker, trading_day) DO UPDATE SET return_1d=excluded.return_1d
            """,
            rows,
        )

    conn.commit()
    return days


def test_pipeline_populates_all_tables(tmp_db):
    """compute_features_for_pair + compute_features_for_ticker must populate all 5 tables."""
    _insert_pair_and_returns(tmp_db, "AAA", "BBB")

    compute_features_for_pair(tmp_db, "AAA", "BBB")
    for ticker in ["AAA", "BBB", "SPY"]:
        compute_features_for_ticker(tmp_db, ticker)

    # Check all 5 tables have rows
    for table in [
        "features_cross_correlation",
        "features_relative_strength",
        "features_volatility",
        "features_zscore",
        "features_lagged_returns",
    ]:
        count = tmp_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count > 0, f"Table {table} has 0 rows after pipeline run"


def test_compute_features_all_pairs_empty_db(tmp_db):
    """compute_features_all_pairs with no active pairs must return empty dict without error."""
    result = compute_features_all_pairs(tmp_db)
    assert result == {"pairs": {}, "tickers": {}}


def test_compute_features_all_pairs_with_pair(tmp_db):
    """compute_features_all_pairs with one active pair must return results for all 5 features."""
    _insert_pair_and_returns(tmp_db, "CCC", "DDD")
    result = compute_features_all_pairs(tmp_db)

    assert ("CCC", "DDD") in result["pairs"]
    pair_result = result["pairs"][("CCC", "DDD")]
    assert "xcorr" in pair_result
    assert "rs" in pair_result

    # SPY, CCC, DDD should all be in ticker results
    for ticker in ["SPY", "CCC", "DDD"]:
        assert ticker in result["tickers"], f"{ticker} missing from ticker results"
        ticker_result = result["tickers"][ticker]
        assert "volatility" in ticker_result
        assert "zscore" in ticker_result
        assert "lagged_returns" in ticker_result
