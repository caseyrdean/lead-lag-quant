"""Tests for the paper trading engine core logic."""

import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from paper_trading.engine import (
    auto_execute_signals,
    close_position,
    compute_share_quantity,
    get_portfolio_summary,
    open_or_add_position,
    set_capital,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# TRADE-01: Set capital
# ---------------------------------------------------------------------------


def test_set_capital(tmp_db):
    """set_capital creates a portfolio row with correct starting and cash balance."""
    result = set_capital(tmp_db, 100_000)
    assert result["starting_capital"] == 100_000
    assert result["cash_balance"] == 100_000
    # Verify DB row
    row = tmp_db.execute(
        "SELECT * FROM paper_portfolio WHERE portfolio_id = 1"
    ).fetchone()
    assert row is not None
    assert row["starting_capital"] == 100_000
    assert row["cash_balance"] == 100_000


def test_set_capital_resets(tmp_db):
    """Calling set_capital again resets the portfolio."""
    set_capital(tmp_db, 100_000)
    result = set_capital(tmp_db, 50_000)
    assert result["starting_capital"] == 50_000
    assert result["cash_balance"] == 50_000


# ---------------------------------------------------------------------------
# TRADE-02/03: Open positions
# ---------------------------------------------------------------------------


def test_open_position_manual(tmp_db):
    """Manual buy creates position and trade, deducts cash."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    open_or_add_position(
        tmp_db,
        portfolio_id=1,
        ticker="AAPL",
        shares=10,
        price=150.0,
        source_signal_id=None,
        invalidation_threshold=None,
        executed_at=now,
    )

    # Check position
    pos = tmp_db.execute(
        "SELECT * FROM paper_positions WHERE ticker = 'AAPL'"
    ).fetchone()
    assert pos is not None
    assert int(pos["shares"]) == 10
    assert pos["avg_cost"] == 150.0

    # Check trade
    trade = tmp_db.execute(
        "SELECT * FROM paper_trades WHERE ticker = 'AAPL' AND side = 'buy'"
    ).fetchone()
    assert trade is not None
    assert int(trade["shares"]) == 10
    assert trade["notes"] == "manual"

    # Check cash deducted
    portfolio = tmp_db.execute(
        "SELECT cash_balance FROM paper_portfolio WHERE portfolio_id = 1"
    ).fetchone()
    assert portfolio["cash_balance"] == 100_000 - (10 * 150.0)


def test_open_position_avg_cost(tmp_db):
    """Adding shares to an existing position updates average cost correctly."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    # Buy 10 at $100
    open_or_add_position(
        tmp_db, 1, "TSLA", 10, 100.0, None, None, now,
    )
    # Buy 10 more at $200
    open_or_add_position(
        tmp_db, 1, "TSLA", 10, 200.0, None, None, now,
    )

    pos = tmp_db.execute(
        "SELECT shares, avg_cost FROM paper_positions WHERE ticker = 'TSLA'"
    ).fetchone()
    assert int(pos["shares"]) == 20
    # avg_cost = (10*100 + 10*200) / (10+10) = 3000/20 = 150.0
    assert pos["avg_cost"] == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# TRADE-03/06: Close positions
# ---------------------------------------------------------------------------


def test_close_position_full(tmp_db):
    """Full close computes correct realized P&L and removes position."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    open_or_add_position(tmp_db, 1, "MSFT", 10, 100.0, None, None, now)
    pnl = close_position(tmp_db, 1, "MSFT", 10, 120.0, now)

    # realized_pnl = 10 * (120 - 100) = 200
    assert pnl == pytest.approx(200.0)

    # Position row should be deleted
    pos = tmp_db.execute(
        "SELECT * FROM paper_positions WHERE ticker = 'MSFT'"
    ).fetchone()
    assert pos is None

    # Cash should reflect: 100k - 1000 (buy) + 1200 (sell) = 100200
    portfolio = tmp_db.execute(
        "SELECT cash_balance FROM paper_portfolio WHERE portfolio_id = 1"
    ).fetchone()
    assert portfolio["cash_balance"] == pytest.approx(100_200.0)


def test_close_position_partial(tmp_db):
    """Partial close reduces shares and records correct P&L."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    open_or_add_position(tmp_db, 1, "GOOG", 10, 100.0, None, None, now)
    pnl = close_position(tmp_db, 1, "GOOG", 5, 120.0, now)

    # realized_pnl = 5 * (120 - 100) = 100
    assert pnl == pytest.approx(100.0)

    # 5 shares remain
    pos = tmp_db.execute(
        "SELECT shares FROM paper_positions WHERE ticker = 'GOOG'"
    ).fetchone()
    assert int(pos["shares"]) == 5


def test_close_position_insufficient_shares(tmp_db):
    """Attempting to close more shares than held raises ValueError."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    open_or_add_position(tmp_db, 1, "AMZN", 10, 100.0, None, None, now)

    with pytest.raises(ValueError, match="only 10 held"):
        close_position(tmp_db, 1, "AMZN", 15, 120.0, now)


# ---------------------------------------------------------------------------
# Sizing computation
# ---------------------------------------------------------------------------


def test_compute_share_quantity():
    """compute_share_quantity returns correct integer share count."""
    # full = 20% of 100k = 20k; 20000 // 150 = 133
    assert compute_share_quantity(100_000, 50_000, "full", 150.0) == 133

    # With zero cash
    assert compute_share_quantity(100_000, 0, "full", 150.0) == 0

    # With zero price
    assert compute_share_quantity(100_000, 50_000, "full", 0.0) == 0

    # Half = 10% of 100k = 10k; min(10000, 8000) = 8000; 8000 // 100 = 80
    assert compute_share_quantity(100_000, 8_000, "half", 100.0) == 80


# ---------------------------------------------------------------------------
# Portfolio summary
# ---------------------------------------------------------------------------


def test_get_portfolio_summary(tmp_db):
    """Portfolio summary returns correct cash and zero P&L initially."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    open_or_add_position(tmp_db, 1, "NVDA", 10, 200.0, None, None, now)

    summary = get_portfolio_summary(tmp_db)
    assert summary["starting_capital"] == 100_000
    # 100000 - (10 * 200) = 98000
    assert summary["cash_balance"] == pytest.approx(98_000.0)
    # No current_price set yet, so unrealized = 0
    assert summary["unrealized_pnl"] == 0.0
    assert summary["realized_pnl"] == 0.0
    assert summary["win_rate"] == 0.0


# ---------------------------------------------------------------------------
# Duplicate auto-execution prevention
# ---------------------------------------------------------------------------


def test_duplicate_auto_execution_blocked(tmp_db):
    """Unique index prevents duplicate buy trades for the same signal."""
    set_capital(tmp_db, 100_000)
    now = _now_utc()

    # Insert a test signal into the signals table
    tmp_db.execute(
        """
        INSERT INTO signals
            (ticker_a, ticker_b, signal_date, optimal_lag, window_length,
             correlation_strength, stability_score, regime_state,
             adjustment_policy_id, direction, expected_target,
             invalidation_threshold, sizing_tier, flow_map_entry, generated_at)
        VALUES
            ('SPY', 'QQQ', '2026-02-19', 2, 60, 0.75, 80.0, 'trending',
             'policy_a', 'long', 0.02, 0.03, 'half',
             'SPY leads QQQ by 2 sessions', ?)
        """,
        (now,),
    )
    tmp_db.commit()

    # Get the signal's rowid
    signal_id = tmp_db.execute(
        "SELECT rowid FROM signals WHERE ticker_a = 'SPY' AND ticker_b = 'QQQ'"
    ).fetchone()[0]

    # First buy trade with this signal_id -- should succeed
    open_or_add_position(
        tmp_db, 1, "QQQ", 10, 400.0, signal_id, 0.03, now,
    )

    # Second buy trade with the same signal_id -- should fail
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            """
            INSERT INTO paper_trades
                (portfolio_id, ticker, side, shares, price, realized_pnl,
                 source_signal_id, executed_at, notes)
            VALUES (1, 'QQQ', 'buy', 5, 410.0, NULL, ?, ?, 'auto_execute')
            """,
            (signal_id, now),
        )


# ---------------------------------------------------------------------------
# BUGFIX-05: Concurrent auto-execution must not deadlock or raise
# ---------------------------------------------------------------------------


def test_concurrent_execute(tmp_db):
    """Two threads calling auto_execute_signals concurrently must not deadlock.

    With no unprocessed signals in the DB, each call returns immediately after
    the lock is acquired. This confirms the lock is non-reentrant for distinct
    threads and that both threads complete cleanly.
    """
    set_capital(tmp_db, 100_000)

    errors: list[Exception] = []

    def run():
        try:
            auto_execute_signals(tmp_db, "test_key")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=run)
    t2 = threading.Thread(target=run)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive(), "Thread 1 did not complete — possible deadlock"
    assert not t2.is_alive(), "Thread 2 did not complete — possible deadlock"
    assert errors == [], f"Unexpected exceptions from threads: {errors}"
