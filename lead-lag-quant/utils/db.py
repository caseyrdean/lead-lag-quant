"""SQLite database connection factory and schema initialization."""

import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode for better concurrency.

    Args:
        db_path: Path to the SQLite database file. Use ':memory:' for in-memory DB.

    Returns:
        Configured sqlite3.Connection with WAL mode, foreign keys, and Row factory.
    """
    db_path_str = str(db_path)

    # Create parent directory if using a file-based database
    if db_path_str != ":memory:":
        Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path_str, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize all database tables.

    Creates ticker_pairs, raw_api_responses, and ingestion_log tables
    using CREATE TABLE IF NOT EXISTS for idempotent schema creation.

    Args:
        conn: An active SQLite connection.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticker_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leader TEXT NOT NULL,
            follower TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(leader, follower)
        );

        CREATE TABLE IF NOT EXISTS raw_api_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            request_params TEXT NOT NULL,
            response_json TEXT NOT NULL,
            retrieved_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(ticker, endpoint, request_params)
        );

        CREATE TABLE IF NOT EXISTS ingestion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            date_from TEXT,
            date_to TEXT,
            status TEXT NOT NULL,
            records_fetched INTEGER DEFAULT 0,
            error_message TEXT,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            execution_date TEXT NOT NULL,
            split_from REAL NOT NULL,
            split_to REAL NOT NULL,
            historical_adjustment_factor REAL,
            adjustment_type TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(ticker, execution_date)
        );

        CREATE TABLE IF NOT EXISTS normalized_bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            trading_day TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            adj_open REAL NOT NULL,
            adj_high REAL NOT NULL,
            adj_low REAL NOT NULL,
            adj_close REAL NOT NULL,
            adj_volume REAL NOT NULL,
            vwap REAL,
            transactions INTEGER,
            adjustment_policy_id TEXT NOT NULL DEFAULT 'policy_a',
            created_at TEXT NOT NULL DEFAULT (datetime('now','utc')),
            UNIQUE(ticker, trading_day)
        );

        CREATE TABLE IF NOT EXISTS returns_policy_a (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            trading_day TEXT NOT NULL,
            return_1d REAL,
            return_5d REAL,
            return_10d REAL,
            return_20d REAL,
            return_60d REAL,
            adjustment_policy_id TEXT NOT NULL DEFAULT 'policy_a',
            created_at TEXT NOT NULL DEFAULT (datetime('now','utc')),
            UNIQUE(ticker, trading_day)
        );

        CREATE TABLE IF NOT EXISTS dividends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            cash_amount REAL,
            currency TEXT,
            dividend_type TEXT,
            pay_date TEXT,
            record_date TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(ticker, ex_date)
        );

        CREATE INDEX IF NOT EXISTS idx_normalized_bars_ticker_day
            ON normalized_bars(ticker, trading_day);
        CREATE INDEX IF NOT EXISTS idx_returns_ticker_day
            ON returns_policy_a(ticker, trading_day);
        CREATE INDEX IF NOT EXISTS idx_splits_ticker_date
            ON splits(ticker, execution_date);
    """)
    conn.commit()
