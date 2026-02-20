"""Core paper trading engine: capital setup, position management, auto-execution.

All functions take conn as first argument and use paper_trading.db helpers
for SQL operations. All timestamps are UTC ISO format.
"""

import sqlite3
from datetime import datetime, timezone

from paper_trading.db import (
    check_exit_flags,
    get_open_positions,
    get_portfolio,
    get_trade_history,
)
from paper_trading.price_poller import fetch_snapshot_price
from utils.logging import get_logger

log = get_logger("paper_trading.engine")

# Sizing tier to capital fraction mapping (TRADE-02)
SIZING_FRACTIONS: dict[str, float] = {
    "full": 0.20,     # 20% of starting capital
    "half": 0.10,     # 10% of starting capital
    "quarter": 0.05,  # 5% of starting capital
}


def compute_share_quantity(
    starting_capital: float,
    cash_balance: float,
    sizing_tier: str,
    entry_price: float,
) -> int:
    """Compute integer share count based on sizing tier and available cash.

    Uses floor division -- never allocates more cash than available.
    Returns 0 if insufficient cash or invalid price.
    """
    max_position_value = starting_capital * SIZING_FRACTIONS.get(sizing_tier, 0.10)
    affordable_value = min(max_position_value, cash_balance)
    if affordable_value <= 0 or entry_price <= 0:
        return 0
    return int(affordable_value // entry_price)


def set_capital(
    conn: sqlite3.Connection,
    starting_capital: float,
    portfolio_id: int = 1,
) -> dict:
    """Set (or reset) starting paper capital for a portfolio (TRADE-01).

    Uses INSERT with ON CONFLICT to upsert. Resets cash_balance to
    starting_capital on re-set.

    Returns the portfolio dict.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO paper_portfolio
            (portfolio_id, starting_capital, cash_balance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(portfolio_id) DO UPDATE SET
            starting_capital = excluded.starting_capital,
            cash_balance = excluded.cash_balance,
            updated_at = excluded.updated_at
        """,
        (portfolio_id, starting_capital, starting_capital, now, now),
    )
    conn.commit()
    return dict(get_portfolio(conn, portfolio_id))


def open_or_add_position(
    conn: sqlite3.Connection,
    portfolio_id: int,
    ticker: str,
    shares: int,
    price: float,
    source_signal_id: int | None,
    invalidation_threshold: float | None,
    executed_at: str,
) -> None:
    """Open a new position or add to an existing one (TRADE-02/03).

    Records a buy trade, upserts position with average-cost formula,
    and deducts cash from portfolio. All in one transaction.

    CRITICAL: shares is cast to int before DB write to avoid float precision.
    """
    shares = int(shares)
    trade_value = shares * price

    # 1. Record buy trade
    conn.execute(
        """
        INSERT INTO paper_trades
            (portfolio_id, ticker, side, shares, price, realized_pnl,
             source_signal_id, executed_at, notes)
        VALUES (?, ?, 'buy', ?, ?, NULL, ?, ?, ?)
        """,
        (
            portfolio_id, ticker, shares, price,
            source_signal_id, executed_at,
            "auto_execute" if source_signal_id else "manual",
        ),
    )

    # 2. Upsert position with average-cost update
    conn.execute(
        """
        INSERT INTO paper_positions
            (portfolio_id, ticker, shares, avg_cost, source_signal_id,
             invalidation_threshold, opened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(portfolio_id, ticker) DO UPDATE SET
            avg_cost = (shares * avg_cost + excluded.shares * excluded.avg_cost)
                       / (shares + excluded.shares),
            shares   = shares + excluded.shares
        """,
        (
            portfolio_id, ticker, shares, price,
            source_signal_id, invalidation_threshold, executed_at,
        ),
    )

    # 3. Deduct cash
    conn.execute(
        """
        UPDATE paper_portfolio
        SET cash_balance = cash_balance - ?,
            updated_at = ?
        WHERE portfolio_id = ?
        """,
        (trade_value, executed_at, portfolio_id),
    )

    conn.commit()
    log.info(
        "position_opened",
        ticker=ticker, shares=shares, price=price,
        source_signal_id=source_signal_id,
    )


def close_position(
    conn: sqlite3.Connection,
    portfolio_id: int,
    ticker: str,
    shares_to_close: int,
    close_price: float,
    executed_at: str,
    notes: str = "manual",
) -> float:
    """Partially or fully close a position (TRADE-03/06).

    Records a sell trade with realized P&L. Deletes position row if fully
    closed, otherwise reduces shares. Returns realized_pnl.

    Raises ValueError if shares_to_close > shares held.
    """
    shares_to_close = int(shares_to_close)

    row = conn.execute(
        """
        SELECT shares, avg_cost FROM paper_positions
        WHERE portfolio_id = ? AND ticker = ?
        """,
        (portfolio_id, ticker),
    ).fetchone()

    if row is None:
        raise ValueError(f"No open position for {ticker}")

    held_shares = int(row["shares"])
    avg_cost = row["avg_cost"]

    if shares_to_close > held_shares:
        raise ValueError(
            f"Cannot close {shares_to_close} shares of {ticker}; "
            f"only {held_shares} held"
        )

    realized_pnl = shares_to_close * (close_price - avg_cost)
    trade_value = shares_to_close * close_price

    # Record sell trade
    conn.execute(
        """
        INSERT INTO paper_trades
            (portfolio_id, ticker, side, shares, price, realized_pnl,
             source_signal_id, executed_at, notes)
        VALUES (?, ?, 'sell', ?, ?, ?, NULL, ?, ?)
        """,
        (
            portfolio_id, ticker, shares_to_close, close_price,
            realized_pnl, executed_at, notes,
        ),
    )

    remaining = held_shares - shares_to_close
    if remaining == 0:
        # Full close -- remove position row
        conn.execute(
            "DELETE FROM paper_positions WHERE portfolio_id = ? AND ticker = ?",
            (portfolio_id, ticker),
        )
    else:
        # Partial close -- shares reduce, avg_cost stays
        conn.execute(
            "UPDATE paper_positions SET shares = ? WHERE portfolio_id = ? AND ticker = ?",
            (remaining, portfolio_id, ticker),
        )

    # Return cash
    conn.execute(
        """
        UPDATE paper_portfolio
        SET cash_balance = cash_balance + ?,
            updated_at = ?
        WHERE portfolio_id = ?
        """,
        (trade_value, executed_at, portfolio_id),
    )

    conn.commit()
    log.info(
        "position_closed",
        ticker=ticker, shares=shares_to_close,
        close_price=close_price, realized_pnl=round(realized_pnl, 2),
    )
    return realized_pnl


def auto_execute_signals(
    conn: sqlite3.Connection,
    api_key: str,
    portfolio_id: int = 1,
) -> list[dict]:
    """Auto-execute unprocessed signals by opening paper positions (TRADE-02).

    1. Get portfolio (raise ValueError if none).
    2. Query unprocessed signals from db.get_unprocessed_signals.
    3. For each signal: fetch price for ticker_b (follower), compute shares,
       open position if shares > 0.

    Returns list of executed trade dicts.
    """
    from paper_trading.db import get_unprocessed_signals

    portfolio = get_portfolio(conn, portfolio_id)
    if portfolio is None:
        raise ValueError("No portfolio found. Call set_capital() first.")

    signals = get_unprocessed_signals(conn)
    executed = []

    for sig in signals:
        try:
            ticker_b = sig["ticker_b"]
            now = datetime.now(timezone.utc).isoformat()

            # Fetch current price for the follower ticker
            price = fetch_snapshot_price(ticker_b, api_key)
            if price is None:
                log.warning(
                    "auto_execute_skip_no_price",
                    ticker=ticker_b, signal_id=sig["signal_id"],
                )
                continue

            # Refresh portfolio state for current cash
            portfolio = get_portfolio(conn, portfolio_id)
            shares = compute_share_quantity(
                portfolio["starting_capital"],
                portfolio["cash_balance"],
                sig.get("sizing_tier", "half"),
                price,
            )

            if shares == 0:
                log.warning(
                    "auto_execute_skip_insufficient_cash",
                    ticker=ticker_b, signal_id=sig["signal_id"],
                    cash_balance=portfolio["cash_balance"],
                )
                continue

            open_or_add_position(
                conn,
                portfolio_id=portfolio_id,
                ticker=ticker_b,
                shares=shares,
                price=price,
                source_signal_id=sig["signal_id"],
                invalidation_threshold=sig.get("invalidation_threshold"),
                executed_at=now,
            )

            executed.append({
                "signal_id": sig["signal_id"],
                "ticker": ticker_b,
                "shares": shares,
                "price": price,
                "sizing_tier": sig.get("sizing_tier"),
            })
            log.info(
                "auto_execute_success",
                ticker=ticker_b, shares=shares, price=price,
                signal_id=sig["signal_id"],
            )

        except Exception as exc:
            log.error(
                "auto_execute_error",
                signal_id=sig.get("signal_id"),
                ticker=sig.get("ticker_b"),
                error=str(exc)[:200],
            )
            continue

    return executed


def get_portfolio_summary(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> dict:
    """Compute full portfolio summary (TRADE-04/06).

    Returns dict with: cash_balance, starting_capital, unrealized_pnl,
    realized_pnl, total_pnl, win_rate.
    """
    cash_row = conn.execute(
        "SELECT cash_balance, starting_capital FROM paper_portfolio WHERE portfolio_id = ?",
        (portfolio_id,),
    ).fetchone()

    if cash_row is None:
        return {
            "cash_balance": 0.0,
            "starting_capital": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
        }

    unrealized_row = conn.execute(
        """
        SELECT COALESCE(SUM((current_price - avg_cost) * shares), 0)
        FROM paper_positions
        WHERE portfolio_id = ? AND current_price IS NOT NULL
        """,
        (portfolio_id,),
    ).fetchone()
    unrealized = unrealized_row[0]

    realized_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(realized_pnl), 0) AS total_realized,
            COUNT(CASE WHEN realized_pnl > 0 THEN 1 END) AS wins,
            COUNT(CASE WHEN realized_pnl IS NOT NULL THEN 1 END) AS total_closed
        FROM paper_trades
        WHERE portfolio_id = ? AND side = 'sell'
        """,
        (portfolio_id,),
    ).fetchone()

    total_realized = realized_row["total_realized"]
    wins = realized_row["wins"]
    total_closed = realized_row["total_closed"]

    win_rate = (
        round(wins / total_closed * 100, 1)
        if total_closed > 0
        else 0.0
    )

    return {
        "cash_balance": cash_row["cash_balance"],
        "starting_capital": cash_row["starting_capital"],
        "unrealized_pnl": unrealized,
        "realized_pnl": total_realized,
        "total_pnl": unrealized + total_realized,
        "win_rate": win_rate,
    }


def get_open_positions_display(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> list[dict]:
    """Get open positions with unrealized P&L and exit flags (TRADE-04/07).

    Returns list of dicts suitable for DataFrame conversion, including:
    ticker, shares, avg_cost, current_price, unrealized_pnl, exit_flag.
    """
    positions = get_open_positions(conn, portfolio_id)

    # Get exit-flagged position IDs
    flagged = check_exit_flags(conn, portfolio_id)
    flagged_ids = {f["position_id"] for f in flagged}

    result = []
    for pos in positions:
        current_price = pos.get("current_price")
        if current_price is not None:
            unrealized_pnl = round(
                (current_price - pos["avg_cost"]) * pos["shares"], 2
            )
        else:
            unrealized_pnl = None

        result.append({
            "ticker": pos["ticker"],
            "shares": int(pos["shares"]),
            "avg_cost": round(pos["avg_cost"], 2),
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "exit_flag": pos["position_id"] in flagged_ids,
            "opened_at": pos["opened_at"],
        })

    return result


def get_trade_history_display(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> list[dict]:
    """Get trade history for display (TRADE-08).

    Thin wrapper around db.get_trade_history.
    """
    return get_trade_history(conn, portfolio_id)
