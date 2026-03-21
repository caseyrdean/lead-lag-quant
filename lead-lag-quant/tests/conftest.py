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
    """Create a FastAPI TestClient with in-memory test DB and config injected.

    Uses app.dependency_overrides to replace the get_conn and get_config
    dependency functions from api.deps so that route handlers receive the
    test fixtures instead of the real lifespan-managed resources.
    TestClient(app, raise_server_exceptions=False) is used with
    lifespan="off" to avoid triggering the real DB/scheduler startup.

    Yields:
        fastapi.testclient.TestClient instance ready for API tests.
    """
    from api.main import app
    from api import deps

    # Override dependency callables so route handlers use test fixtures
    app.dependency_overrides[deps.get_conn] = lambda: tmp_db
    app.dependency_overrides[deps.get_config] = lambda: app_config
    app.dependency_overrides[deps.get_client] = lambda: None

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    # Clean up overrides after the test
    app.dependency_overrides.clear()
