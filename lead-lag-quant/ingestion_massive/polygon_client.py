"""Polygon.io REST client with rate limiting, retry, and pagination."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pyrate_limiter import Limiter, Rate, Duration

from utils.logging import get_logger


class PolygonClient:
    """HTTP client for the Polygon.io REST API.

    Features:
    - Token-bucket rate limiting (pre-throttle before each request)
    - Exponential backoff retry on 429 and 5xx errors
    - Cursor-based pagination for all endpoints
    - Always fetches unadjusted aggregate bars (adjusted=false)
    """

    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: str, rate_limit_per_minute: int = 5):
        self.api_key = api_key
        self.log = get_logger("polygon_client")

        # Token-bucket rate limiter
        self.limiter = Limiter(
            Rate(rate_limit_per_minute, Duration.MINUTE),
        )

        # HTTP session with retry adapter
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            backoff_jitter=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = requests.Session()
        self.session.mount("https://", adapter)

    def _get(self, url: str, params: dict | None = None) -> dict:
        """Make a rate-limited, retrying GET request.

        Args:
            url: Full URL to request.
            params: Query parameters (apiKey injected automatically).

        Returns:
            Parsed JSON response as dict.
        """
        self.limiter.try_acquire("polygon_api")

        if params is None:
            params = {}
        params["apiKey"] = self.api_key

        # Log URL without API key for security
        safe_url = url.split("?")[0]
        self.log.debug("polygon_request", url=safe_url)

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _paginate_v3(
        self, url: str, params: dict
    ) -> tuple[list[dict], list[dict]]:
        """Generic pagination for v3 endpoints.

        Follows next_url cursor-based pagination, accumulating both
        parsed results and raw response JSON from each page.

        Args:
            url: Initial endpoint URL.
            params: Initial query parameters.

        Returns:
            Tuple of (all_results, all_raw_responses).
        """
        all_results = []
        all_raw_responses = []

        data = self._get(url, params)
        all_raw_responses.append(data)
        all_results.extend(data.get("results", []))

        while data.get("next_url"):
            # Cursor is embedded in next_url; only apiKey needed
            data = self._get(data["next_url"], {})
            all_raw_responses.append(data)
            all_results.extend(data.get("results", []))

        return all_results, all_raw_responses

    def get_aggs(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        timespan: str = "day",
        multiplier: int = 1,
    ) -> tuple[list[dict], list[dict]]:
        """Fetch aggregate bars for a ticker.

        CRITICAL: Always requests unadjusted data (adjusted=false) per INGEST-02.

        Args:
            ticker: Stock ticker symbol.
            from_date: Start date (YYYY-MM-DD).
            to_date: End date (YYYY-MM-DD).
            timespan: Bar timespan (default: "day").
            multiplier: Bar multiplier (default: 1).

        Returns:
            Tuple of (all_results, all_raw_responses).
        """
        url = (
            f"{self.BASE_URL}/v2/aggs/ticker/{ticker}"
            f"/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        )
        params = {
            "adjusted": "false",
            "sort": "asc",
            "limit": "50000",
        }

        all_results = []
        all_raw_responses = []

        data = self._get(url, params)
        all_raw_responses.append(data)
        all_results.extend(data.get("results", []))

        while data.get("next_url"):
            # Cursor in next_url; only apiKey needed for subsequent pages
            data = self._get(data["next_url"], {})
            all_raw_responses.append(data)
            all_results.extend(data.get("results", []))

        return all_results, all_raw_responses

    def get_splits(self, ticker: str) -> tuple[list[dict], list[dict]]:
        """Fetch stock split history for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Tuple of (all_results, all_raw_responses).
        """
        url = f"{self.BASE_URL}/v3/reference/splits"
        params = {"ticker": ticker, "limit": "1000"}
        return self._paginate_v3(url, params)

    def get_dividends(self, ticker: str) -> tuple[list[dict], list[dict]]:
        """Fetch dividend history for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Tuple of (all_results, all_raw_responses).
        """
        url = f"{self.BASE_URL}/v3/reference/dividends"
        params = {"ticker": ticker, "limit": "1000"}
        return self._paginate_v3(url, params)

    def get_ticker_details(self, ticker: str) -> dict | None:
        """Validate a ticker via the reference endpoint.

        Args:
            ticker: Stock ticker symbol to check.

        Returns:
            Results dict if ticker is active, None if inactive or invalid.
        """
        url = f"{self.BASE_URL}/v3/reference/tickers/{ticker}"
        try:
            data = self._get(url)
            results = data.get("results", {})
            if results.get("active"):
                return results
            return None
        except requests.HTTPError:
            return None
