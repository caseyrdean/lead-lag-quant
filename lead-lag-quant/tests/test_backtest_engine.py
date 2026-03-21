"""Unit tests for backtest/engine.py.

Uses the tmp_db fixture which initialises all schema tables (including signals,
features_lagged_returns, features_cross_correlation, regime_states,
distribution_events).
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
