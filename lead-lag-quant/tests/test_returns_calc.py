"""Tests for normalization/returns_calc.py.

Covers:
- Basic rolling returns computation (1d, 5d, 10d, 20d, 60d)
- Cross-ticker isolation (no pct_change bleed between tickers)
- adjustment_policy_id tag on all rows
- Idempotency (upsert, not duplicate insert)
- Empty ticker (no normalized_bars rows)
"""
import pytest

from normalization.returns_calc import compute_returns_for_ticker, compute_returns_all_pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_normalized_bars(conn, ticker: str, adj_close_values: list[float]):
    """Insert rows into normalized_bars starting at 2024-01-02, one row per value.

    Dates are generated sequentially as '2024-MM-DD' (no weekend skipping needed;
    pct_change is positional so calendar gaps don't affect computation).
    """
    rows = []
    base_year = 2024
    base_month = 1
    day = 2  # start 2024-01-02

    for i, adj_close in enumerate(adj_close_values):
        # Increment date linearly (day-of-year style, handles month overflow simply)
        day_offset = i
        # Use a simple sequential day string by computing from ordinal
        import datetime
        d = datetime.date(base_year, base_month, day) + datetime.timedelta(days=day_offset)
        trading_day = d.strftime("%Y-%m-%d")

        raw_price = adj_close  # identical for test simplicity
        rows.append((
            ticker,
            trading_day,
            raw_price,     # open
            raw_price,     # high
            raw_price,     # low
            raw_price,     # close
            adj_close,     # adj_open
            adj_close,     # adj_high
            adj_close,     # adj_low
            adj_close,     # adj_close
            1_000_000,     # adj_volume
        ))

    conn.executemany(
        "INSERT INTO normalized_bars (ticker, trading_day, open, high, low, close, "
        "adj_open, adj_high, adj_low, adj_close, adj_volume, adjustment_policy_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'policy_a')",
        rows,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Test a: Basic returns computation
# ---------------------------------------------------------------------------

def test_basic_returns_computation(tmp_db):
    """65 rows of AAPL rising by 1/day -- verifies row count, NaN boundary, 60d return."""
    adj_close_values = [100.0 + i for i in range(65)]
    _insert_normalized_bars(tmp_db, "AAPL", adj_close_values)

    count = compute_returns_for_ticker(tmp_db, "AAPL")

    assert count == 65, f"Expected 65 rows upserted, got {count}"

    # First row: return_1d should be NULL (no prior bar)
    first = tmp_db.execute(
        "SELECT return_1d FROM returns_policy_a WHERE ticker='AAPL' "
        "ORDER BY trading_day ASC LIMIT 1"
    ).fetchone()
    assert first is not None
    assert first[0] is None, f"First return_1d should be NULL, got {first[0]}"

    # Row 2 (index 1): return_1d should be approximately 1/100 = 0.01
    second = tmp_db.execute(
        "SELECT return_1d FROM returns_policy_a WHERE ticker='AAPL' "
        "ORDER BY trading_day ASC LIMIT 1 OFFSET 1"
    ).fetchone()
    assert second is not None
    assert second[0] is not None, "Second row return_1d should not be NULL"
    assert abs(second[0] - 0.01) < 1e-6, f"Expected ~0.01, got {second[0]}"

    # Row 61 (offset 60) should have a non-NULL return_60d
    row_61 = tmp_db.execute(
        "SELECT return_60d FROM returns_policy_a WHERE ticker='AAPL' "
        "ORDER BY trading_day ASC LIMIT 1 OFFSET 60"
    ).fetchone()
    assert row_61 is not None
    assert row_61[0] is not None, "Row 61 return_60d should not be NULL"


# ---------------------------------------------------------------------------
# Test b: Cross-ticker isolation
# ---------------------------------------------------------------------------

def test_cross_ticker_isolation(tmp_db):
    """AAA and BBB should each have NULL return_1d on their first row -- no bleed."""
    _insert_normalized_bars(tmp_db, "AAA", [100.0, 200.0, 300.0, 400.0, 500.0])
    _insert_normalized_bars(tmp_db, "BBB", [10.0, 20.0, 30.0, 40.0, 50.0])

    compute_returns_for_ticker(tmp_db, "AAA")
    compute_returns_for_ticker(tmp_db, "BBB")

    aaa_first = tmp_db.execute(
        "SELECT return_1d FROM returns_policy_a WHERE ticker='AAA' "
        "ORDER BY trading_day ASC LIMIT 1"
    ).fetchone()
    assert aaa_first is not None
    assert aaa_first[0] is None, (
        f"AAA first return_1d should be NULL (no bleed), got {aaa_first[0]}"
    )

    bbb_first = tmp_db.execute(
        "SELECT return_1d FROM returns_policy_a WHERE ticker='BBB' "
        "ORDER BY trading_day ASC LIMIT 1"
    ).fetchone()
    assert bbb_first is not None
    assert bbb_first[0] is None, (
        f"BBB first return_1d should be NULL (no bleed), got {bbb_first[0]}"
    )


# ---------------------------------------------------------------------------
# Test c: adjustment_policy_id tag
# ---------------------------------------------------------------------------

def test_adjustment_policy_id_tag(tmp_db):
    """All rows in returns_policy_a must carry adjustment_policy_id = 'policy_a'."""
    _insert_normalized_bars(tmp_db, "MSFT", [200.0 + i for i in range(10)])
    compute_returns_for_ticker(tmp_db, "MSFT")

    rows = tmp_db.execute(
        "SELECT adjustment_policy_id FROM returns_policy_a WHERE ticker='MSFT'"
    ).fetchall()

    assert len(rows) == 10, f"Expected 10 rows, got {len(rows)}"
    for row in rows:
        assert row[0] == "policy_a", (
            f"Expected adjustment_policy_id='policy_a', got '{row[0]}'"
        )


# ---------------------------------------------------------------------------
# Test d: Idempotency (upsert, not duplicate insert)
# ---------------------------------------------------------------------------

def test_idempotency(tmp_db):
    """Calling compute_returns_for_ticker twice should not duplicate rows."""
    _insert_normalized_bars(tmp_db, "GOOG", [150.0 + i * 2 for i in range(5)])

    count_first = compute_returns_for_ticker(tmp_db, "GOOG")
    count_second = compute_returns_for_ticker(tmp_db, "GOOG")

    assert count_first == 5, f"First run should return 5, got {count_first}"
    assert count_second == 5, f"Second run should still return 5, got {count_second}"

    total_rows = tmp_db.execute(
        "SELECT COUNT(*) FROM returns_policy_a WHERE ticker='GOOG'"
    ).fetchone()[0]
    assert total_rows == 5, (
        f"Should have exactly 5 rows (upsert, not duplicate), got {total_rows}"
    )


# ---------------------------------------------------------------------------
# Test e: Empty ticker
# ---------------------------------------------------------------------------

def test_empty_ticker(tmp_db):
    """compute_returns_for_ticker for a ticker with no normalized_bars returns 0."""
    result = compute_returns_for_ticker(tmp_db, "NONEXISTENT")
    assert result == 0, f"Expected 0 for ticker with no data, got {result}"

    rows = tmp_db.execute(
        "SELECT COUNT(*) FROM returns_policy_a WHERE ticker='NONEXISTENT'"
    ).fetchone()[0]
    assert rows == 0, "No rows should be inserted for nonexistent ticker"
