"""Regression tests for analytics API error handling.

Covers:
- BUGFIX-07: All analytics endpoints return {"error": "..."} at HTTP 500
  when an underlying function raises an exception — no raw traceback.
"""

import pytest


def _assert_error_response(response, endpoint: str) -> None:
    """Assert response is HTTP 500 with a JSON body containing 'error' key."""
    assert response.status_code == 500, (
        f"{endpoint}: Expected 500, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "error" in body, (
        f"{endpoint}: Expected 'error' key in response body, got: {body}"
    )
    assert body["error"] == "db error", (
        f"{endpoint}: Expected error='db error', got: {body['error']!r}"
    )


def test_error_handling_stats(api_client, monkeypatch):
    """GET /api/analytics/stats returns HTTP 500 + error JSON on exception."""
    import api.routes.analytics as mod
    monkeypatch.setattr(mod, "get_trade_stats", lambda conn: (_ for _ in ()).throw(RuntimeError("db error")))
    response = api_client.get("/api/analytics/stats")
    _assert_error_response(response, "/api/analytics/stats")


def test_error_handling_risk(api_client, monkeypatch):
    """GET /api/analytics/risk returns HTTP 500 + error JSON on exception."""
    import api.routes.analytics as mod
    monkeypatch.setattr(mod, "get_risk_metrics", lambda conn, lookback_days=365: (_ for _ in ()).throw(RuntimeError("db error")))
    response = api_client.get("/api/analytics/risk")
    _assert_error_response(response, "/api/analytics/risk")


def test_error_handling_equity(api_client, monkeypatch):
    """GET /api/analytics/equity returns HTTP 500 + error JSON on exception."""
    import api.routes.analytics as mod
    monkeypatch.setattr(mod, "get_portfolio_value_history", lambda conn, lookback_days=365: (_ for _ in ()).throw(RuntimeError("db error")))
    response = api_client.get("/api/analytics/equity")
    _assert_error_response(response, "/api/analytics/equity")


def test_error_handling_ticker_breakdown(api_client, monkeypatch):
    """GET /api/analytics/ticker-breakdown returns HTTP 500 + error JSON on exception."""
    import api.routes.analytics as mod
    monkeypatch.setattr(mod, "get_ticker_breakdown", lambda conn: (_ for _ in ()).throw(RuntimeError("db error")))
    response = api_client.get("/api/analytics/ticker-breakdown")
    _assert_error_response(response, "/api/analytics/ticker-breakdown")


def test_error_handling_pnl_distribution(api_client, monkeypatch):
    """GET /api/analytics/pnl-distribution returns HTTP 500 + error JSON on exception.

    This endpoint uses conn.execute() directly; force an error by closing the connection.
    """
    import sqlite3

    # Replace the conn dependency with a closed connection to force an OperationalError
    from api.main import app
    from api import deps

    def broken_conn():
        bad = sqlite3.connect(":memory:")
        bad.close()
        return bad

    app.dependency_overrides[deps.get_conn] = broken_conn
    try:
        response = api_client.get("/api/analytics/pnl-distribution")
        assert response.status_code == 500, (
            f"Expected 500, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert "error" in body, f"Expected 'error' key, got: {body}"
    finally:
        # Restore the original override (tmp_db) — api_client fixture will clear on teardown
        from api.main import app as _app
        _app.dependency_overrides[deps.get_conn] = api_client.app.dependency_overrides.get(
            deps.get_conn,
            lambda: None,
        )


def test_error_handling_monthly_heatmap(api_client, monkeypatch):
    """GET /api/analytics/monthly-heatmap returns HTTP 500 + error JSON on exception."""
    import sqlite3

    from api.main import app
    from api import deps

    def broken_conn():
        bad = sqlite3.connect(":memory:")
        bad.close()
        return bad

    original = app.dependency_overrides.get(deps.get_conn)
    app.dependency_overrides[deps.get_conn] = broken_conn
    try:
        response = api_client.get("/api/analytics/monthly-heatmap")
        assert response.status_code == 500, (
            f"Expected 500, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert "error" in body, f"Expected 'error' key, got: {body}"
    finally:
        if original is not None:
            app.dependency_overrides[deps.get_conn] = original
