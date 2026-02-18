"""Unit tests for the normalization module.

Covers:
- Schema: all 4 new tables exist after init_schema()
- unix_ms_to_trading_day: known timestamp maps to correct trading day
- get_adjustment_factor_for_bar: 1.0 when no splits, correct factor when split exists
- extract_splits_to_table: reads raw splits JSON, writes splits rows, copies fetched_at
- normalize_bars_for_ticker: reads raw agg JSON, produces normalized_bars with policy_a
- store_dividends_for_ticker: reads raw dividend JSON, writes dividends, never touches prices
- normalize_ticker orchestrator: all three sub-steps run, returns correct counts dict
"""
import json

import pytest

from normalization.bar_normalizer import normalize_bars_for_ticker
from normalization.dividend_storer import store_dividends_for_ticker
from normalization.normalizer import normalize_all_pairs, normalize_ticker
from normalization.split_adjuster import (
    extract_splits_to_table,
    get_adjustment_factor_for_bar,
)
from normalization.timestamp_utils import unix_ms_to_trading_day


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_raw(conn, ticker, endpoint, params, body, retrieved_at="2024-01-15T00:00:00"):
    """Insert a row into raw_api_responses."""
    conn.execute(
        "INSERT INTO raw_api_responses (ticker, endpoint, request_params, response_json, retrieved_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ticker, endpoint, params, body, retrieved_at),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_all_four_normalization_tables_exist(self, tmp_db):
        tables = [
            r[0]
            for r in tmp_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "splits" in tables, f"splits missing from tables: {tables}"
        assert "normalized_bars" in tables, f"normalized_bars missing: {tables}"
        assert "returns_policy_a" in tables, f"returns_policy_a missing: {tables}"
        assert "dividends" in tables, f"dividends missing: {tables}"

    def test_existing_tables_still_present(self, tmp_db):
        tables = [
            r[0]
            for r in tmp_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "ticker_pairs" in tables
        assert "raw_api_responses" in tables
        assert "ingestion_log" in tables


# ---------------------------------------------------------------------------
# timestamp_utils tests
# ---------------------------------------------------------------------------

class TestTimestampUtils:
    def test_known_timestamp_maps_to_correct_trading_day(self):
        # 1704153600000 ms = 2024-01-02 00:00 UTC (NYSE trading day 2024-01-02)
        result = unix_ms_to_trading_day(1704153600000)
        assert result == "2024-01-02"

    def test_returns_string_format(self):
        result = unix_ms_to_trading_day(1704153600000)
        assert isinstance(result, str)
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # YYYY
        assert len(parts[1]) == 2  # MM
        assert len(parts[2]) == 2  # DD


# ---------------------------------------------------------------------------
# split_adjuster tests
# ---------------------------------------------------------------------------

class TestGetAdjustmentFactor:
    def test_returns_one_when_no_splits_exist(self, tmp_db):
        factor = get_adjustment_factor_for_bar(tmp_db, "AAPL", "2023-01-10")
        assert factor == 1.0

    def test_returns_one_for_bar_after_split_execution_date(self, tmp_db):
        # Split executed on 2023-06-01; bar_date is 2023-07-01 (after split)
        tmp_db.execute(
            "INSERT INTO splits (ticker, execution_date, split_from, split_to, "
            "historical_adjustment_factor, adjustment_type, fetched_at) "
            "VALUES ('AAPL', '2023-06-01', 1, 4, 0.25, 'forward_split', '2024-01-01')"
        )
        tmp_db.commit()
        factor = get_adjustment_factor_for_bar(tmp_db, "AAPL", "2023-07-01")
        assert factor == 1.0

    def test_returns_correct_factor_for_bar_before_split_execution_date(self, tmp_db):
        # Split executed on 2023-06-01; bar_date is 2023-01-10 (before split)
        tmp_db.execute(
            "INSERT INTO splits (ticker, execution_date, split_from, split_to, "
            "historical_adjustment_factor, adjustment_type, fetched_at) "
            "VALUES ('AAPL', '2023-06-01', 1, 4, 0.25, 'forward_split', '2024-01-01')"
        )
        tmp_db.commit()
        factor = get_adjustment_factor_for_bar(tmp_db, "AAPL", "2023-01-10")
        assert factor == 0.25

    def test_returns_one_when_historical_adjustment_factor_is_null(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO splits (ticker, execution_date, split_from, split_to, "
            "historical_adjustment_factor, adjustment_type, fetched_at) "
            "VALUES ('MSFT', '2023-06-01', 2, 1, NULL, 'reverse_split', '2024-01-01')"
        )
        tmp_db.commit()
        factor = get_adjustment_factor_for_bar(tmp_db, "MSFT", "2023-01-10")
        assert factor == 1.0


class TestExtractSplitsToTable:
    def test_reads_splits_json_and_writes_to_splits_table(self, tmp_db):
        split_json = json.dumps({
            "results": [
                {
                    "execution_date": "2023-06-01",
                    "split_from": 1,
                    "split_to": 4,
                    "historical_adjustment_factor": 0.25,
                    "adjustment_type": "forward_split",
                }
            ]
        })
        _insert_raw(tmp_db, "AAPL", "splits", '{"p":1}', split_json, "2024-01-15T10:00:00")
        count = extract_splits_to_table(tmp_db, "AAPL")
        assert count == 1

        row = tmp_db.execute(
            "SELECT * FROM splits WHERE ticker='AAPL' AND execution_date='2023-06-01'"
        ).fetchone()
        assert row is not None
        assert row["split_from"] == 1.0
        assert row["split_to"] == 4.0
        assert row["historical_adjustment_factor"] == 0.25
        assert row["adjustment_type"] == "forward_split"

    def test_copies_retrieved_at_as_fetched_at(self, tmp_db):
        split_json = json.dumps({
            "results": [
                {
                    "execution_date": "2022-08-25",
                    "split_from": 1,
                    "split_to": 20,
                    "historical_adjustment_factor": 0.05,
                    "adjustment_type": "forward_split",
                }
            ]
        })
        _insert_raw(tmp_db, "TSLA", "splits", '{"p":1}', split_json, "2024-03-01T12:00:00")
        extract_splits_to_table(tmp_db, "TSLA")

        row = tmp_db.execute(
            "SELECT fetched_at FROM splits WHERE ticker='TSLA'"
        ).fetchone()
        assert row["fetched_at"] == "2024-03-01T12:00:00"

    def test_returns_zero_for_empty_results(self, tmp_db):
        _insert_raw(tmp_db, "SPY", "splits", '{"p":1}', '{"results":[]}')
        count = extract_splits_to_table(tmp_db, "SPY")
        assert count == 0

    def test_returns_zero_when_no_raw_row(self, tmp_db):
        count = extract_splits_to_table(tmp_db, "NONEXISTENT")
        assert count == 0


# ---------------------------------------------------------------------------
# bar_normalizer tests
# ---------------------------------------------------------------------------

class TestNormalizeBarsForTicker:
    def test_produces_normalized_bars_with_policy_a(self, tmp_db):
        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 100.0, "h": 105.0, "l": 98.0,
                 "c": 102.0, "v": 1000000, "vw": 101.5, "n": 5000}
            ]
        })
        _insert_raw(tmp_db, "TEST", "aggs", '{"p":1}', agg_json)
        _insert_raw(tmp_db, "TEST", "splits", '{"p":2}', '{"results":[]}')

        count = normalize_bars_for_ticker(tmp_db, "TEST")
        assert count == 1

        row = tmp_db.execute(
            "SELECT * FROM normalized_bars WHERE ticker='TEST'"
        ).fetchone()
        assert row is not None
        assert row["adjustment_policy_id"] == "policy_a"

    def test_no_split_means_adj_close_equals_close(self, tmp_db):
        # With no splits, factor=1.0, so adj_close == close
        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 100.0, "h": 105.0, "l": 98.0,
                 "c": 102.0, "v": 1000000}
            ]
        })
        _insert_raw(tmp_db, "NOSPLIT", "aggs", '{"p":1}', agg_json)
        normalize_bars_for_ticker(tmp_db, "NOSPLIT")

        row = tmp_db.execute(
            "SELECT close, adj_close FROM normalized_bars WHERE ticker='NOSPLIT'"
        ).fetchone()
        assert row["adj_close"] == row["close"]

    def test_split_before_bar_applies_adjustment(self, tmp_db):
        # Bar on 2024-01-02; split executed 2024-06-01 (after bar) => factor=0.25
        tmp_db.execute(
            "INSERT INTO splits (ticker, execution_date, split_from, split_to, "
            "historical_adjustment_factor, adjustment_type, fetched_at) "
            "VALUES ('SPLIT', '2024-06-01', 1, 4, 0.25, 'forward_split', '2024-01-01')"
        )
        tmp_db.commit()

        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 100.0, "h": 105.0, "l": 98.0,
                 "c": 102.0, "v": 1000000}
            ]
        })
        _insert_raw(tmp_db, "SPLIT", "aggs", '{"p":1}', agg_json)
        normalize_bars_for_ticker(tmp_db, "SPLIT")

        row = tmp_db.execute(
            "SELECT close, adj_close FROM normalized_bars WHERE ticker='SPLIT'"
        ).fetchone()
        # adj_close = close * factor = 102.0 * 0.25 = 25.5
        assert abs(row["adj_close"] - 102.0 * 0.25) < 1e-9
        assert row["adj_close"] != row["close"]

    def test_returns_zero_when_no_agg_rows(self, tmp_db):
        count = normalize_bars_for_ticker(tmp_db, "EMPTY")
        assert count == 0

    def test_trading_day_stored_as_yyyy_mm_dd_string(self, tmp_db):
        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 50.0, "h": 51.0, "l": 49.0,
                 "c": 50.5, "v": 500000}
            ]
        })
        _insert_raw(tmp_db, "DATECHK", "aggs", '{"p":1}', agg_json)
        normalize_bars_for_ticker(tmp_db, "DATECHK")

        row = tmp_db.execute(
            "SELECT trading_day FROM normalized_bars WHERE ticker='DATECHK'"
        ).fetchone()
        assert row["trading_day"] == "2024-01-02"


# ---------------------------------------------------------------------------
# dividend_storer tests
# ---------------------------------------------------------------------------

class TestStoreDividendsForTicker:
    def test_writes_dividend_records_to_dividends_table(self, tmp_db):
        div_json = json.dumps({
            "results": [
                {
                    "ex_date": "2023-03-15",
                    "cash_amount": 0.23,
                    "currency": "USD",
                    "dividend_type": "CD",
                    "pay_date": "2023-04-15",
                    "record_date": "2023-03-16",
                }
            ]
        })
        _insert_raw(tmp_db, "AAPL", "dividends", '{"p":1}', div_json)
        count = store_dividends_for_ticker(tmp_db, "AAPL")
        assert count == 1

        row = tmp_db.execute(
            "SELECT * FROM dividends WHERE ticker='AAPL' AND ex_date='2023-03-15'"
        ).fetchone()
        assert row is not None
        assert row["cash_amount"] == 0.23
        assert row["currency"] == "USD"
        assert row["dividend_type"] == "CD"

    def test_dividends_never_modify_normalized_bars(self, tmp_db):
        # Insert a normalized bar with close=100 first
        tmp_db.execute(
            "INSERT INTO normalized_bars "
            "(ticker, trading_day, open, high, low, close, "
            " adj_open, adj_high, adj_low, adj_close, adj_volume, adjustment_policy_id) "
            "VALUES ('DIVTEST', '2023-03-15', 100.0, 101.0, 99.0, 100.0, "
            " 100.0, 101.0, 99.0, 100.0, 50000.0, 'policy_a')"
        )
        tmp_db.commit()

        div_json = json.dumps({
            "results": [
                {
                    "ex_date": "2023-03-15",
                    "cash_amount": 5.00,  # large dividend to detect price contamination
                    "currency": "USD",
                    "dividend_type": "CD",
                    "pay_date": "2023-04-15",
                    "record_date": "2023-03-16",
                }
            ]
        })
        _insert_raw(tmp_db, "DIVTEST", "dividends", '{"p":1}', div_json)
        store_dividends_for_ticker(tmp_db, "DIVTEST")

        # Prices in normalized_bars must be unchanged
        row = tmp_db.execute(
            "SELECT adj_close FROM normalized_bars WHERE ticker='DIVTEST'"
        ).fetchone()
        assert row["adj_close"] == 100.0

    def test_returns_zero_for_empty_results(self, tmp_db):
        _insert_raw(tmp_db, "SPY", "dividends", '{"p":1}', '{"results":[]}')
        count = store_dividends_for_ticker(tmp_db, "SPY")
        assert count == 0

    def test_returns_zero_when_no_raw_row(self, tmp_db):
        count = store_dividends_for_ticker(tmp_db, "NONEXISTENT")
        assert count == 0


# ---------------------------------------------------------------------------
# normalizer orchestrator tests
# ---------------------------------------------------------------------------

class TestNormalizeTicker:
    def test_returns_correct_counts_dict(self, tmp_db):
        # Setup: 1 agg bar, 1 split, 1 dividend
        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 100.0, "h": 105.0, "l": 98.0,
                 "c": 102.0, "v": 1000000}
            ]
        })
        split_json = json.dumps({
            "results": [
                {
                    "execution_date": "2024-06-01",
                    "split_from": 1,
                    "split_to": 4,
                    "historical_adjustment_factor": 0.25,
                    "adjustment_type": "forward_split",
                }
            ]
        })
        div_json = json.dumps({
            "results": [
                {
                    "ex_date": "2024-03-15",
                    "cash_amount": 0.50,
                    "currency": "USD",
                    "dividend_type": "CD",
                    "pay_date": "2024-04-15",
                    "record_date": "2024-03-16",
                }
            ]
        })
        _insert_raw(tmp_db, "FULL", "aggs", '{"p":1}', agg_json)
        _insert_raw(tmp_db, "FULL", "splits", '{"p":2}', split_json)
        _insert_raw(tmp_db, "FULL", "dividends", '{"p":3}', div_json)

        result = normalize_ticker(tmp_db, "FULL")
        assert result["splits"] == 1
        assert result["bars"] == 1
        assert result["dividends"] == 1

    def test_all_normalized_bars_carry_policy_a(self, tmp_db):
        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 50.0, "h": 52.0, "l": 49.0,
                 "c": 51.0, "v": 200000},
            ]
        })
        _insert_raw(tmp_db, "POLCHK", "aggs", '{"p":1}', agg_json)
        _insert_raw(tmp_db, "POLCHK", "splits", '{"p":2}', '{"results":[]}')
        _insert_raw(tmp_db, "POLCHK", "dividends", '{"p":3}', '{"results":[]}')

        normalize_ticker(tmp_db, "POLCHK")

        rows = tmp_db.execute(
            "SELECT adjustment_policy_id FROM normalized_bars WHERE ticker='POLCHK'"
        ).fetchall()
        assert len(rows) > 0
        for row in rows:
            assert row["adjustment_policy_id"] == "policy_a"

    def test_no_splits_produces_adj_close_equal_to_close(self, tmp_db):
        agg_json = json.dumps({
            "results": [
                {"t": 1704153600000, "o": 75.0, "h": 76.0, "l": 74.0,
                 "c": 75.5, "v": 300000},
            ]
        })
        _insert_raw(tmp_db, "NOSPLIT2", "aggs", '{"p":1}', agg_json)
        _insert_raw(tmp_db, "NOSPLIT2", "splits", '{"p":2}', '{"results":[]}')
        _insert_raw(tmp_db, "NOSPLIT2", "dividends", '{"p":3}', '{"results":[]}')

        normalize_ticker(tmp_db, "NOSPLIT2")

        row = tmp_db.execute(
            "SELECT close, adj_close FROM normalized_bars WHERE ticker='NOSPLIT2'"
        ).fetchone()
        assert row["adj_close"] == row["close"]


class TestNormalizeAllPairs:
    def test_returns_empty_dict_when_no_active_pairs(self, tmp_db):
        result = normalize_all_pairs(tmp_db)
        assert result == {}

    def test_processes_all_tickers_including_spy(self, tmp_db):
        # Insert an active pair and raw data for all tickers
        tmp_db.execute(
            "INSERT INTO ticker_pairs (leader, follower, is_active) VALUES ('AAPL', 'MSFT', 1)"
        )
        tmp_db.commit()

        for ticker in ("AAPL", "MSFT", "SPY"):
            agg_json = json.dumps({
                "results": [
                    {"t": 1704153600000, "o": 100.0, "h": 101.0, "l": 99.0,
                     "c": 100.5, "v": 100000}
                ]
            })
            _insert_raw(tmp_db, ticker, "aggs", '{"p":1}', agg_json)
            _insert_raw(tmp_db, ticker, "splits", '{"p":2}', '{"results":[]}')
            _insert_raw(tmp_db, ticker, "dividends", '{"p":3}', '{"results":[]}')

        results = normalize_all_pairs(tmp_db)
        assert set(results.keys()) == {"AAPL", "MSFT", "SPY"}
        for ticker, r in results.items():
            assert r["bars"] == 1
