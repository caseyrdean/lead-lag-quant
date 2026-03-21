"""SQLite schema and DB helper functions for paper trading tables.

Three tables: paper_portfolio, paper_positions, paper_trades.
Call init_paper_trading_schema(conn) from utils.db.init_schema().
"""

import sqlite3
from datetime import datetime, timezone

from utils.logging import get_logger

log = get_logger("paper_trading.db")


def init_paper_trading_schema(conn: sqlite3.Connection) -> None:
    """Create paper trading tables and indexes.

    Called from utils.db.init_schema() after engine schema.
    Uses CREATE TABLE IF NOT EXISTS for idempotent schema creation.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_portfolio (
            portfolio_id     INTEGER PRIMARY KEY DEFAULT 1,
            starting_capital REAL    NOT NULL,
            cash_balance     REAL    NOT NULL,
            created_at       TEXT    NOT NULL,
            updated_at       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_positions (
            position_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id     INTEGER NOT NULL DEFAULT 1,
            ticker           TEXT    NOT NULL,
            shares           REAL    NOT NULL,
            avg_cost         REAL    NOT NULL,
            current_price    REAL,
            last_price_at    TEXT,
            source_signal_id INTEGER,
            invalidation_threshold REAL,
            opened_at        TEXT    NOT NULL,
            UNIQUE(portfolio_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            trade_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id     INTEGER NOT NULL DEFAULT 1,
            ticker           TEXT    NOT NULL,
            side             TEXT    NOT NULL CHECK(side IN ('buy', 'sell')),
            shares           REAL    NOT NULL,
            price            REAL    NOT NULL,
            realized_pnl     REAL,
            source_signal_id INTEGER,
            executed_at      TEXT    NOT NULL,
            notes            TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_signal_buy
            ON paper_trades(source_signal_id)
            WHERE source_signal_id IS NOT NULL AND side = 'buy';

        CREATE INDEX IF NOT EXISTS idx_positions_ticker ON paper_positions(ticker);
        CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON paper_trades(executed_at);
        CREATE INDEX IF NOT EXISTS idx_trades_ticker ON paper_trades(ticker);
    """)
    conn.commit()
    log.info("paper_trading_schema_initialized")


def get_portfolio(conn: sqlite3.Connection, portfolio_id: int = 1) -> dict | None:
    """Fetch portfolio row as dict, or None if not found."""
    row = conn.execute(
        "SELECT * FROM paper_portfolio WHERE portfolio_id = ?",
        (portfolio_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_portfolio(
    conn: sqlite3.Connection,
    starting_capital: float,
    cash_balance: float,
    portfolio_id: int = 1,
) -> None:
    """Insert or replace a portfolio row with UTC timestamps."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_portfolio
            (portfolio_id, starting_capital, cash_balance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (portfolio_id, starting_capital, cash_balance, now, now),
    )
    conn.commit()


def get_open_positions(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> list[dict]:
    """Get all open positions for a portfolio, ordered by opened_at."""
    rows = conn.execute(
        "SELECT * FROM paper_positions WHERE portfolio_id = ? ORDER BY opened_at",
        (portfolio_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_trade_history(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> list[dict]:
    """Get all trades for a portfolio, newest first."""
    rows = conn.execute(
        "SELECT * FROM paper_trades WHERE portfolio_id = ? ORDER BY executed_at DESC",
        (portfolio_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_unprocessed_signals(conn: sqlite3.Connection) -> list[dict]:
    """Return signals from the last 7 days that have no corresponding buy trade.

    Uses NOT EXISTS for idempotent auto-execution detection.
    """
    sql = """
        SELECT s.rowid AS signal_id, s.ticker_a, s.ticker_b, s.signal_date,
               s.direction, s.sizing_tier, s.invalidation_threshold, s.expected_target
        FROM signals s
        INNER JOIN ticker_pairs tp
            ON tp.leader = s.ticker_a
            AND tp.follower = s.ticker_b
            AND tp.is_active = 1
        WHERE s.signal_date >= date('now', '-7 days')
          AND NOT EXISTS (
              SELECT 1 FROM paper_trades
              WHERE paper_trades.source_signal_id = s.rowid
                AND paper_trades.side = 'buy'
          )
          AND (tp.reactivated_at IS NULL OR s.generated_at >= tp.reactivated_at)
        ORDER BY s.generated_at DESC
    """
    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def update_position_prices(
    conn: sqlite3.Connection,
    prices: dict[str, float],
    refreshed_at: str,
) -> None:
    """Batch update current_price and last_price_at on open positions."""
    rows = [
        (price, refreshed_at, ticker)
        for ticker, price in prices.items()
        if price is not None
    ]
    conn.executemany(
        """
        UPDATE paper_positions
        SET current_price = ?, last_price_at = ?
        WHERE ticker = ?
        """,
        rows,
    )
    conn.commit()


def check_exit_flags(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> list[dict]:
    """Check open positions for leader reversal exceeding invalidation_threshold.

    For each position with a source_signal_id and invalidation_threshold,
    looks up the leader ticker (ticker_a from the signal), fetches its most
    recent abs(return_1d) from returns_policy_a, and flags positions where
    the leader's absolute return exceeds the invalidation threshold.

    Returns list of dicts with: ticker, shares, invalidation_threshold,
    leader_return_1d, position_id.
    """
    positions = conn.execute(
        """
        SELECT position_id, ticker, shares, source_signal_id, invalidation_threshold
        FROM paper_positions
        WHERE portfolio_id = ?
          AND source_signal_id IS NOT NULL
          AND invalidation_threshold IS NOT NULL
        """,
        (portfolio_id,),
    ).fetchall()

    flagged = []
    for pos in positions:
        pos_dict = dict(pos)
        signal_id = pos_dict["source_signal_id"]

        # Get the leader ticker from the signal
        signal_row = conn.execute(
            "SELECT ticker_a FROM signals WHERE rowid = ?",
            (signal_id,),
        ).fetchone()
        if signal_row is None:
            continue

        leader_ticker = signal_row["ticker_a"]

        # Get the leader's most recent abs(return_1d)
        ret_row = conn.execute(
            """
            SELECT return_1d FROM returns_policy_a
            WHERE ticker = ?
              AND return_1d IS NOT NULL
            ORDER BY trading_day DESC
            LIMIT 1
            """,
            (leader_ticker,),
        ).fetchone()
        if ret_row is None:
            continue

        leader_return_1d = abs(ret_row["return_1d"])
        if leader_return_1d > pos_dict["invalidation_threshold"]:
            flagged.append({
                "position_id": pos_dict["position_id"],
                "ticker": pos_dict["ticker"],
                "shares": pos_dict["shares"],
                "invalidation_threshold": pos_dict["invalidation_threshold"],
                "leader_return_1d": leader_return_1d,
            })

    return flagged
