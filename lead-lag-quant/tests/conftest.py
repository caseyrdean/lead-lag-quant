"""Shared test fixtures for the lead-lag-quant test suite."""

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def api_client(tmp_db, app_config):
    """Create a FastAPI TestClient with in-memory test DB and config wired in.

    deps.py resolves conn/config/client from request.app.state, so setting
    app.state before yielding the TestClient propagates correctly through
    all route handlers.

    Yields:
        fastapi.testclient.TestClient instance ready for API tests.
    """
    from api.main import app

    app.state.conn = tmp_db
    app.state.config = app_config
    app.state.client = None
    app.state.ws_manager = None

    with TestClient(app) as client:
        yield client
