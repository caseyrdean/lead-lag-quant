"""Tests for the Polygon.io REST client."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from ingestion_massive.polygon_client import PolygonClient


def _mock_response(json_data: dict, status_code: int = 200):
    """Create a mock Response object with .json() and .raise_for_status()."""
    resp = MagicMock(spec=requests.Response)
    resp.json.return_value = json_data
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def client():
    """Create a PolygonClient with dummy key and high rate limit for tests."""
    return PolygonClient(api_key="test_key_123", rate_limit_per_minute=100)


class TestGetAggs:
    def test_get_aggs_pagination(self, client):
        """Two pages of aggs results should be combined."""
        page1 = {
            "results": [{"t": 1, "o": 100.0}],
            "next_url": "https://api.polygon.io/v2/aggs/next?cursor=abc",
        }
        page2 = {
            "results": [{"t": 2, "o": 101.0}],
        }

        with patch.object(client.session, "get") as mock_get:
            mock_get.side_effect = [
                _mock_response(page1),
                _mock_response(page2),
            ]

            results, raw = client.get_aggs("AAPL", "2025-01-01", "2025-06-01")

        assert len(results) == 2
        assert results[0]["t"] == 1
        assert results[1]["t"] == 2
        assert len(raw) == 2

        # Verify apiKey was included in both calls
        assert mock_get.call_count == 2
        for call in mock_get.call_args_list:
            params = call[1].get("params", call[0][1] if len(call[0]) > 1 else {})
            assert params.get("apiKey") == "test_key_123"

    def test_get_aggs_always_unadjusted(self, client):
        """Aggregate bar requests must always include adjusted=false."""
        page1 = {"results": [{"t": 1, "o": 100.0}]}

        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(page1)
            client.get_aggs("AAPL", "2025-01-01", "2025-06-01")

        call_params = mock_get.call_args[1]["params"]
        assert call_params["adjusted"] == "false"


class TestGetSplits:
    def test_get_splits_pagination(self, client):
        """V3 pagination for splits should combine results from all pages."""
        page1 = {
            "results": [{"ticker": "AAPL", "execution_date": "2020-08-31"}],
            "next_url": "https://api.polygon.io/v3/reference/splits?cursor=xyz",
        }
        page2 = {
            "results": [{"ticker": "AAPL", "execution_date": "2014-06-09"}],
        }

        with patch.object(client.session, "get") as mock_get:
            mock_get.side_effect = [
                _mock_response(page1),
                _mock_response(page2),
            ]

            results, raw = client.get_splits("AAPL")

        assert len(results) == 2
        assert results[0]["execution_date"] == "2020-08-31"
        assert results[1]["execution_date"] == "2014-06-09"


class TestGetTickerDetails:
    def test_get_ticker_details_valid(self, client):
        """Valid active ticker returns the results dict."""
        data = {
            "results": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "active": True,
            }
        }

        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(data)
            result = client.get_ticker_details("AAPL")

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["active"] is True

    def test_get_ticker_details_invalid(self, client):
        """Invalid ticker (404) returns None."""
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response({}, status_code=404)
            result = client.get_ticker_details("ZZZZZ")

        assert result is None

    def test_get_ticker_details_inactive(self, client):
        """Inactive ticker returns None."""
        data = {
            "results": {
                "ticker": "OLDTICKER",
                "name": "Old Corp",
                "active": False,
            }
        }

        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = _mock_response(data)
            result = client.get_ticker_details("OLDTICKER")

        assert result is None


class TestRateLimiter:
    def test_rate_limiter_called(self, client):
        """Limiter.try_acquire must be called before each request."""
        page1 = {"results": [{"t": 1, "o": 100.0}]}

        with patch.object(client.limiter, "try_acquire") as mock_limiter:
            with patch.object(client.session, "get") as mock_get:
                mock_get.return_value = _mock_response(page1)
                client.get_aggs("AAPL", "2025-01-01", "2025-06-01")

        mock_limiter.assert_called_with("polygon_api")
