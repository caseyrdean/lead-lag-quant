"""Tests for the database utility module."""

import sqlite3

import pytest

from utils.db import get_connection, init_schema


def test_init_schema_creates_tables(tmp_db):
    """init_schema should create all 3 required tables."""
    cursor = tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in cursor.fetchall()]

    assert "ingestion_log" in table_names
    assert "raw_api_responses" in table_names
    assert "ticker_pairs" in table_names


def test_init_schema_idempotent(tmp_db):
    """Calling init_schema twice should not raise an error."""
    # tmp_db already has schema initialized once via fixture
    # Call it again -- should not raise
    init_schema(tmp_db)

    cursor = tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in cursor.fetchall()]
    assert "ticker_pairs" in table_names
    assert "raw_api_responses" in table_names
    assert "ingestion_log" in table_names


def test_ticker_pair_unique_constraint(tmp_db):
    """Inserting the same ticker pair twice should raise IntegrityError."""
    tmp_db.execute(
        "INSERT INTO ticker_pairs (leader, follower) VALUES (?, ?)",
        ("NVDA", "CRWV"),
    )
    tmp_db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            "INSERT INTO ticker_pairs (leader, follower) VALUES (?, ?)",
            ("NVDA", "CRWV"),
        )
        tmp_db.commit()


def test_raw_api_response_upsert(tmp_db):
    """ON CONFLICT DO UPDATE should refresh response_json for same unique key."""
    # Insert initial record
    tmp_db.execute(
        """INSERT INTO raw_api_responses (ticker, endpoint, request_params, response_json)
        VALUES (?, ?, ?, ?)""",
        ("NVDA", "/v2/aggs", '{"from":"2025-01-01"}', '{"results": [1, 2, 3]}'),
    )
    tmp_db.commit()

    # Upsert with same unique key but different response_json
    tmp_db.execute(
        """INSERT INTO raw_api_responses (ticker, endpoint, request_params, response_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (ticker, endpoint, request_params)
        DO UPDATE SET
            response_json = excluded.response_json,
            retrieved_at = datetime('now')""",
        ("NVDA", "/v2/aggs", '{"from":"2025-01-01"}', '{"results": [4, 5, 6]}'),
    )
    tmp_db.commit()

    # Verify only one record exists with the updated response
    cursor = tmp_db.execute(
        "SELECT response_json FROM raw_api_responses WHERE ticker = ? AND endpoint = ?",
        ("NVDA", "/v2/aggs"),
    )
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["response_json"] == '{"results": [4, 5, 6]}'


def test_connection_wal_mode(tmp_path):
    """Connection should use WAL journal mode."""
    db_path = tmp_path / "wal_test.db"
    conn = get_connection(str(db_path))
    try:
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"
    finally:
        conn.close()
