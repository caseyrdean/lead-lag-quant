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
    """)
    conn.commit()
