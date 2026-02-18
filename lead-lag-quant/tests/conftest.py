"""Shared test fixtures for the lead-lag-quant test suite."""

import pytest

from utils.db import get_connection, init_schema
from utils.config import AppConfig


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite DB with schema initialized.

    Yields:
        sqlite3.Connection to a temporary database with all tables created.
    """
    db_path = tmp_path / "test.db"
    conn = get_connection(str(db_path))
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def app_config(tmp_path):
    """Create an AppConfig with a dummy API key and tmp_path DB.

    Returns:
        AppConfig instance suitable for testing.
    """
    return AppConfig(
        polygon_api_key="test_api_key_12345",
        db_path=str(tmp_path / "test.db"),
    )
