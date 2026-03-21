"""Integration tests for /api/backtest endpoints.

Uses the api_client fixture which injects a temporary SQLite DB and bypasses
the real lifespan startup (no Polygon client, no scheduler).
"""


def test_backtest_run_returns_200_with_required_keys(api_client):
    """GET /api/backtest/run returns 200 with all required metric keys."""
    resp = api_client.get(
        "/api/backtest/run",
        params={
            "leader": "AAPL",
            "follower": "MSFT",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    required_keys = {
        "total_trades",
        "hit_rate",
        "mean_return_per_trade",
        "annualized_sharpe",
        "max_drawdown",
    }
    for key in required_keys:
        assert key in data, f"Missing key: {key}"


def test_backtest_xcorr_returns_200_with_list(api_client):
    """GET /api/backtest/xcorr returns 200 with a list (may be empty)."""
    resp = api_client.get(
        "/api/backtest/xcorr",
        params={"leader": "AAPL", "follower": "MSFT"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_backtest_regime_returns_200_with_regime_key(api_client):
    """GET /api/backtest/regime returns 200 with 'regime' key present."""
    resp = api_client.get(
        "/api/backtest/regime",
        params={"leader": "AAPL", "follower": "MSFT"},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "regime" in data
