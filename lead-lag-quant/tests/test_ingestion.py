"""Tests for the ingestion orchestrator."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from ingestion_massive.ingestion import (
    ingest_pair,
    ingest_ticker,
    store_raw_response,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_client(aggs=None, splits=None, dividends=None):
    """Return a mock PolygonClient with configurable return values."""
    client = MagicMock()

    # Default empty responses
    client.get_aggs.return_value = (
        aggs if aggs is not None else [],
        [{"results": aggs or [], "status": "OK"}],
    )
    client.get_splits.return_value = (
        splits if splits is not None else [],
        [{"results": splits or [], "status": "OK"}],
    )
    client.get_dividends.return_value = (
        dividends if dividends is not None else [],
        [{"results": dividends or [], "status": "OK"}],
    )
    return client


# ---------------------------------------------------------------------------
# store_raw_response tests
# ---------------------------------------------------------------------------


class TestStoreRawResponse:
    def test_store_raw_response_insert(self, tmp_db):
        """Stored response can be queried back with matching fields."""
        store_raw_response(
            tmp_db,
            ticker="AAPL",
            endpoint="aggs",
            request_params={"from": "2025-01-01", "to": "2025-12-31"},
            response_json='{"results": [], "status": "OK"}',
        )

        row = tmp_db.execute(
            "SELECT ticker, endpoint, request_params, response_json FROM raw_api_responses"
        ).fetchone()

        assert row["ticker"] == "AAPL"
        assert row["endpoint"] == "aggs"
        assert row["response_json"] == '{"results": [], "status": "OK"}'
        # Params should be deterministic JSON
        stored_params = json.loads(row["request_params"])
        assert stored_params == {"from": "2025-01-01", "to": "2025-12-31"}

    def test_store_raw_response_upsert(self, tmp_db):
        """Storing the same key twice updates the response and timestamp."""
        params = {"ticker": "AAPL", "page": 0}

        store_raw_response(tmp_db, "AAPL", "splits", params, '{"v": 1}')
        store_raw_response(tmp_db, "AAPL", "splits", params, '{"v": 2}')

        rows = tmp_db.execute(
            "SELECT response_json FROM raw_api_responses WHERE ticker='AAPL' AND endpoint='splits'"
        ).fetchall()

        # Only one row should exist (upsert not insert)
        assert len(rows) == 1
        assert rows[0]["response_json"] == '{"v": 2}'

    def test_store_raw_response_deterministic_params(self, tmp_db):
        """Params in different key order produce the same stored row."""
        params_a = {"b": 2, "a": 1}
        params_b = {"a": 1, "b": 2}

        store_raw_response(tmp_db, "MSFT", "dividends", params_a, '{"p": 1}')
        store_raw_response(tmp_db, "MSFT", "dividends", params_b, '{"p": 2}')

        rows = tmp_db.execute(
            "SELECT response_json FROM raw_api_responses WHERE ticker='MSFT'"
        ).fetchall()

        # Deterministic serialization means same key -- only 1 row
        assert len(rows) == 1
        assert rows[0]["response_json"] == '{"p": 2}'


# ---------------------------------------------------------------------------
# ingest_ticker tests
# ---------------------------------------------------------------------------


class TestIngestTicker:
    def test_ingest_ticker_fetches_all_three(self, tmp_db):
        """Ingesting a ticker creates entries for aggs, splits, and dividends."""
        client = _make_client(
            aggs=[{"t": 1, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 5000.0}],
            splits=[{"ticker": "AAPL", "execution_date": "2020-08-31", "split_from": 1, "split_to": 4}],
            dividends=[{"ticker": "AAPL", "cash_amount": 0.23, "ex_dividend_date": "2025-02-07"}],
        )

        result = ingest_ticker(
            client, tmp_db, "AAPL", "2025-01-01", "2025-12-31"
        )

        # All three endpoint types appear in raw_api_responses
        rows = tmp_db.execute(
            "SELECT DISTINCT endpoint FROM raw_api_responses WHERE ticker='AAPL'"
        ).fetchall()
        endpoints = {r["endpoint"] for r in rows}
        assert "aggs" in endpoints
        assert "splits" in endpoints
        assert "dividends" in endpoints

        # ingestion_log should show all completed
        log_rows = tmp_db.execute(
            "SELECT endpoint, status FROM ingestion_log WHERE ticker='AAPL'"
        ).fetchall()
        statuses = {r["endpoint"]: r["status"] for r in log_rows}
        assert statuses["aggs"] == "completed"
        assert statuses["splits"] == "completed"
        assert statuses["dividends"] == "completed"

        # Result counts match
        assert result["aggs"] == 1
        assert result["splits"] == 1
        assert result["dividends"] == 1

    def test_ingest_ticker_handles_error(self, tmp_db):
        """Failed aggs endpoint logs failure; splits and dividends still attempted."""
        client = _make_client()
        client.get_aggs.side_effect = requests.HTTPError("500 Server Error")

        ingest_ticker(client, tmp_db, "FAIL", "2025-01-01", "2025-12-31")

        log_rows = tmp_db.execute(
            "SELECT endpoint, status, error_message FROM ingestion_log WHERE ticker='FAIL'"
        ).fetchall()
        statuses = {r["endpoint"]: r["status"] for r in log_rows}
        errors = {r["endpoint"]: r["error_message"] for r in log_rows}

        assert statuses["aggs"] == "failed"
        assert "500 Server Error" in errors["aggs"]
        # Splits and dividends were still attempted
        assert statuses["splits"] == "completed"
        assert statuses["dividends"] == "completed"


# ---------------------------------------------------------------------------
# ingest_pair tests
# ---------------------------------------------------------------------------


class TestIngestPair:
    def test_ingest_pair_includes_spy(self, tmp_db):
        """ingest_pair always fetches SPY in addition to the specified pair."""
        client = _make_client()

        results = ingest_pair(
            client, tmp_db, "AAPL", "MSFT", "2025-01-01", "2025-12-31"
        )

        fetched_tickers = set(results.keys())
        assert "AAPL" in fetched_tickers
        assert "MSFT" in fetched_tickers
        assert "SPY" in fetched_tickers

    def test_ingest_pair_spy_not_duplicated(self, tmp_db):
        """When one of the pair tickers is SPY, it is fetched only once."""
        client = _make_client()

        results = ingest_pair(
            client, tmp_db, "SPY", "MSFT", "2025-01-01", "2025-12-31"
        )

        fetched_tickers = list(results.keys())
        # SPY should appear exactly once
        assert fetched_tickers.count("SPY") == 1
        assert len(fetched_tickers) == 2  # SPY + MSFT (no duplicate)

        # get_aggs should have been called exactly twice (SPY and MSFT)
        assert client.get_aggs.call_count == 2
        called_tickers = {call.args[0] for call in client.get_aggs.call_args_list}
        assert called_tickers == {"SPY", "MSFT"}
