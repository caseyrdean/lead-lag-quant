"""Unit tests for backtest/engine.py.

Uses the tmp_db fixture which initialises all schema tables (including signals,
features_lagged_returns, features_cross_correlation, regime_states,
distribution_events).

Phase 7 additions:
  - by_action always returns all 4 keys (BUY/HOLD/SELL/UNKNOWN)
  - by_action routes signals correctly by action column value
  - NULL action in signals goes to UNKNOWN bucket
  - outperformance_vs_leader = mean(follower - leader) return
"""

import pytest

from backtest.engine import run_backtest, xcorr_data, regime_state


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------


def test_run_backtest_zero_dict_when_no_signals(tmp_db):
    """run_backtest returns a zero-dict when no signals exist in the date range."""
    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    assert result["total_trades"] == 0
    assert result["winning_trades"] == 0
    assert result["hit_rate"] == 0.0
    assert result["mean_return_per_trade"] == 0.0
    assert result["annualized_sharpe"] == 0.0
    assert result["max_drawdown"] == 0.0
    assert result["leader"] == "AAPL"
    assert result["follower"] == "MSFT"


def test_run_backtest_hit_rate_calculation(tmp_db):
    """run_backtest computes hit_rate = 0.5 when one win and one loss."""
    # Insert two signals using the natural PK (ticker_a, ticker_b, signal_date)
    tmp_db.execute(
        """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date,
            optimal_lag, direction, generated_at
        ) VALUES
            ('AAPL', 'MSFT', '2024-03-01', 2, 'long', '2024-03-01T00:00:00'),
            ('AAPL', 'MSFT', '2024-03-05', 2, 'long', '2024-03-05T00:00:00')
        """
    )

    # Insert matching features_lagged_returns rows:
    # signal 1 → positive return (win), signal 2 → negative return (loss)
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES
            ('MSFT', '2024-03-01', 2,  0.02),
            ('MSFT', '2024-03-05', 2, -0.01)
        """
    )
    tmp_db.commit()

    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    assert result["total_trades"] == 2
    assert result["winning_trades"] == 1
    assert result["hit_rate"] == pytest.approx(0.5)
    assert result["mean_return_per_trade"] == pytest.approx((0.02 + (-0.01)) / 2)


# ---------------------------------------------------------------------------
# xcorr_data
# ---------------------------------------------------------------------------


def test_xcorr_data_returns_empty_list_when_no_data(tmp_db):
    """xcorr_data returns an empty list when features_cross_correlation is empty."""
    result = xcorr_data(tmp_db, "AAPL", "MSFT")

    assert result == []


# ---------------------------------------------------------------------------
# regime_state
# ---------------------------------------------------------------------------


def test_regime_state_returns_sentinel_when_empty(tmp_db):
    """regime_state returns sentinel dict when regime_states table is empty."""
    result = regime_state(tmp_db, "MSFT")

    assert result["regime"] == "Unknown"
    assert result["trading_day"] is None
    assert result["rs_value"] is None
    assert result["price_vs_21ma"] is None
    assert result["price_vs_50ma"] is None
    assert result["atr_ratio"] is None
    assert result["volume_ratio"] is None
    assert result["vwap_rejection_streak"] is None
    assert result["is_flagged"] == 0


# ---------------------------------------------------------------------------
# Phase 7: by_action structure tests
# ---------------------------------------------------------------------------


def test_by_action_always_has_all_four_keys(tmp_db):
    """Phase 7: by_action always contains BUY, HOLD, SELL, UNKNOWN even with no signals."""
    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    assert "by_action" in result
    for key in ("BUY", "HOLD", "SELL", "UNKNOWN"):
        assert key in result["by_action"], f"Missing key: {key!r}"
        assert result["by_action"][key]["total_trades"] == 0


def test_by_action_routes_signals_correctly(tmp_db):
    """Phase 7: by_action correctly counts trades per action bucket.

    2 BUY signals + 1 HOLD signal inserted. Expects BUY.total_trades=2,
    HOLD.total_trades=1, SELL.total_trades=0.
    """
    # Insert 3 signals — 2 BUY, 1 HOLD — with action column populated
    tmp_db.execute(
        """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date, optimal_lag,
            direction, generated_at, action
        ) VALUES
            ('AAPL', 'MSFT', '2024-03-01', 2, 'long', '2024-03-01T00:00:00', 'BUY'),
            ('AAPL', 'MSFT', '2024-03-05', 2, 'long', '2024-03-05T00:00:00', 'BUY'),
            ('AAPL', 'MSFT', '2024-03-10', 2, 'long', '2024-03-10T00:00:00', 'HOLD')
        """
    )
    # Insert matching features_lagged_returns rows for follower (MSFT)
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES
            ('MSFT', '2024-03-01', 2,  0.03),
            ('MSFT', '2024-03-05', 2,  0.02),
            ('MSFT', '2024-03-10', 2, -0.01)
        """
    )
    tmp_db.commit()

    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    by_action = result["by_action"]
    assert by_action["BUY"]["total_trades"] == 2
    assert by_action["HOLD"]["total_trades"] == 1
    assert by_action["SELL"]["total_trades"] == 0
    assert by_action["UNKNOWN"]["total_trades"] == 0


def test_by_action_null_action_goes_to_unknown(tmp_db):
    """Phase 7: Signal with action=NULL (pre-Phase 7 data) is routed to UNKNOWN bucket."""
    # Insert a signal with no action (NULL) — pre-Phase 7 style
    tmp_db.execute(
        """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date, optimal_lag,
            direction, generated_at
        ) VALUES ('AAPL', 'MSFT', '2024-04-01', 2, 'long', '2024-04-01T00:00:00')
        """
    )
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES ('MSFT', '2024-04-01', 2, 0.015)
        """
    )
    tmp_db.commit()

    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    by_action = result["by_action"]
    assert by_action["UNKNOWN"]["total_trades"] == 1
    assert by_action["BUY"]["total_trades"] == 0
    assert by_action["HOLD"]["total_trades"] == 0
    assert by_action["SELL"]["total_trades"] == 0


# ---------------------------------------------------------------------------
# Phase 7: outperformance_vs_leader arithmetic tests
# ---------------------------------------------------------------------------


def test_outperformance_vs_leader_computed_correctly(tmp_db):
    """Phase 7: outperformance_vs_leader = mean(follower - leader).

    follower_return=0.05, leader_return=0.03 → outperformance_vs_leader ≈ 0.02
    """
    tmp_db.execute(
        """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date, optimal_lag,
            direction, generated_at, action
        ) VALUES ('AAPL', 'MSFT', '2024-05-01', 2, 'long', '2024-05-01T00:00:00', 'BUY')
        """
    )
    # Follower (MSFT) return at lag=2 on signal date
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES ('MSFT', '2024-05-01', 2, 0.05)
        """
    )
    # Leader (AAPL) return at same lag
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES ('AAPL', '2024-05-01', 2, 0.03)
        """
    )
    tmp_db.commit()

    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    outperf = result["by_action"]["BUY"]["outperformance_vs_leader"]
    assert abs(outperf - 0.02) < 1e-6, (
        f"Expected outperformance_vs_leader ≈ 0.02, got {outperf}"
    )


def test_outperformance_vs_leader_negative_when_underperformed(tmp_db):
    """Phase 7: outperformance_vs_leader is negative when follower underperforms leader.

    follower_return=0.02, leader_return=0.04 → outperformance_vs_leader ≈ -0.02
    """
    tmp_db.execute(
        """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date, optimal_lag,
            direction, generated_at, action
        ) VALUES ('AAPL', 'MSFT', '2024-06-01', 2, 'long', '2024-06-01T00:00:00', 'BUY')
        """
    )
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES ('MSFT', '2024-06-01', 2, 0.02)
        """
    )
    tmp_db.execute(
        """
        INSERT INTO features_lagged_returns (ticker, trading_day, lag, return_value)
        VALUES ('AAPL', '2024-06-01', 2, 0.04)
        """
    )
    tmp_db.commit()

    result = run_backtest(tmp_db, "AAPL", "MSFT", "2024-01-01", "2024-12-31")

    outperf = result["by_action"]["BUY"]["outperformance_vs_leader"]
    assert abs(outperf - (-0.02)) < 1e-6, (
        f"Expected outperformance_vs_leader ≈ -0.02, got {outperf}"
    )
