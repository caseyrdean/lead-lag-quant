"""Regression tests for trading API input validation.

Covers:
- BUGFIX-06: BuyRequest and SellRequest reject shares=0 and price<=0 with HTTP 422
"""


def test_validation_422_buy_zero_shares(api_client):
    """POST /api/trading/buy with shares=0 returns HTTP 422."""
    response = api_client.post(
        "/api/trading/buy",
        json={"ticker": "AAPL", "shares": 0},
    )
    assert response.status_code == 422, (
        f"Expected 422, got {response.status_code}: {response.text}"
    )


def test_validation_422_buy_negative_price(api_client):
    """POST /api/trading/buy with price=-1.0 returns HTTP 422."""
    response = api_client.post(
        "/api/trading/buy",
        json={"ticker": "AAPL", "shares": 1, "price": -1.0},
    )
    assert response.status_code == 422, (
        f"Expected 422, got {response.status_code}: {response.text}"
    )


def test_validation_422_sell_zero_shares(api_client):
    """POST /api/trading/sell with shares=0 returns HTTP 422."""
    response = api_client.post(
        "/api/trading/sell",
        json={"ticker": "AAPL", "shares": 0},
    )
    assert response.status_code == 422, (
        f"Expected 422, got {response.status_code}: {response.text}"
    )
