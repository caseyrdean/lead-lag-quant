"""Tests for SIGNAL-01/02 generator, ENGINE-03 gate, and flow map entry.

Test coverage:
  1. passes_gate boundary conditions (strict > not >=)
  2. determine_sizing_tier thresholds
  3. build_flow_map_entry lag sign convention
  4. generate_signal gate enforcement, direction, policy, immutability
  5. classify_action BUY/HOLD/SELL classification edge cases (Phase 7)
  6. compute_rs_slope / compute_leader_baseline_return / compute_response_window None-safety
  7. Transition logging duplicate prevention
"""
import time
import pytest
import sqlite3
import pandas as pd
from signals.generator import (
    passes_gate,
    build_flow_map_entry,
    generate_signal,
    STABILITY_THRESHOLD,
    CORRELATION_THRESHOLD,
    classify_action,
    compute_rs_slope,
    compute_leader_baseline_return,
    compute_response_window,
)
from signals.generator import determine_sizing_tier


# ---------------------------------------------------------------------------
# passes_gate boundary tests (ENGINE-03 hard gate)
# ---------------------------------------------------------------------------

def test_passes_gate_false_at_stability_boundary(tmp_db):
    """ENGINE-03: passes_gate returns False when stability_score = 70.0 (strict > not >=)."""
    assert passes_gate(70.0, 0.66) is False


def test_passes_gate_false_at_correlation_boundary(tmp_db):
    """ENGINE-03: passes_gate returns False when correlation_strength = 0.65 (strict > not >=)."""
    assert passes_gate(70.1, 0.65) is False


def test_passes_gate_true_just_above_both_thresholds(tmp_db):
    """ENGINE-03: passes_gate returns True when stability=70.1 AND correlation=0.66."""
    assert passes_gate(70.1, 0.66) is True


def test_passes_gate_false_when_correlation_too_low(tmp_db):
    """ENGINE-03: passes_gate returns False when stability=85 but correlation=0.60."""
    assert passes_gate(85.0, 0.60) is False


def test_stability_threshold_value():
    """ENGINE-03: STABILITY_THRESHOLD constant is 70.0."""
    assert STABILITY_THRESHOLD == 70.0


def test_correlation_threshold_value():
    """ENGINE-03: CORRELATION_THRESHOLD constant is 0.65."""
    assert CORRELATION_THRESHOLD == 0.65


# ---------------------------------------------------------------------------
# determine_sizing_tier tests (SIGNAL-01)
# ---------------------------------------------------------------------------

def test_sizing_tier_full_above_85():
    """SIGNAL-01: stability_score=90 returns 'full'."""
    assert determine_sizing_tier(90.0) == 'full'


def test_sizing_tier_half_between_70_and_85():
    """SIGNAL-01: stability_score=75 returns 'half'."""
    assert determine_sizing_tier(75.0) == 'half'


def test_sizing_tier_half_just_above_70():
    """SIGNAL-01: stability_score=71 returns 'half'."""
    assert determine_sizing_tier(71.0) == 'half'


def test_sizing_tier_full_at_85_boundary():
    """SIGNAL-01: stability_score=85 returns 'half' (> 85 required for 'full')."""
    assert determine_sizing_tier(85.0) == 'half'


def test_sizing_tier_full_just_above_85():
    """SIGNAL-01: stability_score=85.1 returns 'full'."""
    assert determine_sizing_tier(85.1) == 'full'


# ---------------------------------------------------------------------------
# build_flow_map_entry lag sign convention (SIGNAL-02)
# ---------------------------------------------------------------------------

def test_flow_map_positive_lag_b_leads_a():
    """SIGNAL-02: positive lag -> ticker_b leads ticker_a."""
    result = build_flow_map_entry('NVDA', 'CRWV', 2)
    assert result == 'CRWV leads NVDA by 2 sessions'


def test_flow_map_negative_lag_a_leads_b():
    """SIGNAL-02: negative lag -> ticker_a leads ticker_b."""
    result = build_flow_map_entry('NVDA', 'CRWV', -3)
    assert result == 'NVDA leads CRWV by 3 sessions'


def test_flow_map_zero_lag_contemporaneous():
    """SIGNAL-02: lag=0 -> contemporaneous."""
    result = build_flow_map_entry('NVDA', 'CRWV', 0)
    assert result == 'NVDA coincident with CRWV'


def test_flow_map_singular_session():
    """SIGNAL-02: lag=1 uses singular 'session' (not 'sessions')."""
    result = build_flow_map_entry('NVDA', 'CRWV', 1)
    assert result == 'CRWV leads NVDA by 1 session'


def test_flow_map_negative_singular_session():
    """SIGNAL-02: lag=-1 uses singular 'session'."""
    result = build_flow_map_entry('NVDA', 'CRWV', -1)
    assert result == 'NVDA leads CRWV by 1 session'


# ---------------------------------------------------------------------------
# generate_signal tests (ENGINE-03 + SIGNAL-01 + SIGNAL-02)
# ---------------------------------------------------------------------------

def _setup_signal_db(conn: sqlite3.Connection) -> None:
    """Insert minimal supporting data for generate_signal tests.

    - ticker_pairs: (NVDA, CRWV) active
    - features_lagged_returns: CRWV with return_value at lag=2
    - returns_policy_a: NVDA with return_1d values
    """
    # Ticker pair
    conn.execute(
        "INSERT OR IGNORE INTO ticker_pairs (leader, follower, is_active) VALUES (?, ?, ?)",
        ("NVDA", "CRWV", 1),
    )
    # features_lagged_returns for CRWV (follower) at lag=2
    for i in range(30):
        day = f"2020-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}"
        try:
            conn.execute(
                "INSERT OR IGNORE INTO features_lagged_returns (ticker, trading_day, lag, return_value) "
                "VALUES (?, ?, ?, ?)",
                ("CRWV", f"2020-05-{i + 1:02d}", 2, 0.015),
            )
        except Exception:
            pass
    # returns_policy_a for NVDA (leader)
    for i in range(30):
        try:
            conn.execute(
                "INSERT OR IGNORE INTO returns_policy_a (ticker, trading_day, return_1d) "
                "VALUES (?, ?, ?)",
                ("NVDA", f"2020-05-{i + 1:02d}", 0.01),
            )
        except Exception:
            pass
    conn.commit()


def test_generate_signal_returns_none_when_gate_fails(tmp_db):
    """ENGINE-03: generate_signal returns None when stability_score=65 (gate fails)."""
    _setup_signal_db(tmp_db)
    result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.80,
        stability_score=65.0,  # below gate threshold
        regime_state="Bull",
        signal_date="2020-06-01",
    )
    assert result is None


def test_generate_signal_no_db_write_on_gate_fail(tmp_db):
    """ENGINE-03: When gate fails, no row is written to signals table."""
    _setup_signal_db(tmp_db)
    generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.80,
        stability_score=65.0,
        regime_state="Bull",
        signal_date="2020-06-01",
    )
    count = tmp_db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert count == 0


def test_generate_signal_returns_dict_with_policy_a(tmp_db):
    """SIGNAL-01: generate_signal with passing scores returns dict with adjustment_policy_id='policy_a'."""
    _setup_signal_db(tmp_db)
    result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.80,
        stability_score=75.0,
        regime_state="Bull",
        signal_date="2020-06-01",
    )
    assert result is not None
    assert result['adjustment_policy_id'] == 'policy_a'


def test_generate_signal_direction_long_for_positive_correlation(tmp_db):
    """SIGNAL-01: direction='long' when correlation_strength is positive."""
    _setup_signal_db(tmp_db)
    result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.80,  # positive
        stability_score=75.0,
        regime_state="Bull",
        signal_date="2020-06-01",
    )
    assert result is not None
    assert result['direction'] == 'long'


def test_generate_signal_direction_short_for_negative_correlation(tmp_db):
    """SIGNAL-01: direction='short' when correlation_strength is negative."""
    _setup_signal_db(tmp_db)
    result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=-0.80,  # negative
        stability_score=75.0,
        regime_state="Bull",
        signal_date="2020-06-02",
    )
    assert result is not None
    assert result['direction'] == 'short'


def test_generate_signal_full_position_spec_fields(tmp_db):
    """SIGNAL-01: generate_signal returns all required position spec fields."""
    _setup_signal_db(tmp_db)
    result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.80,
        stability_score=90.0,  # above 85 -> 'full' tier
        regime_state="Bull",
        signal_date="2020-06-01",
    )
    assert result is not None
    required_fields = [
        'direction', 'expected_target', 'invalidation_threshold',
        'sizing_tier', 'flow_map_entry', 'adjustment_policy_id',
        'generated_at', 'ticker_a', 'ticker_b', 'signal_date',
    ]
    for field in required_fields:
        assert field in result, f"Missing field: {field}"
    assert result['sizing_tier'] == 'full'
    assert result['flow_map_entry'] == 'CRWV leads NVDA by 2 sessions'


def test_generate_signal_immutability_generated_at(tmp_db):
    """SIGNAL-01: Re-run on same (ticker_a, ticker_b, signal_date) does NOT overwrite generated_at."""
    _setup_signal_db(tmp_db)

    # First call
    first_result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.80,
        stability_score=75.0,
        regime_state="Bull",
        signal_date="2020-06-01",
    )
    assert first_result is not None
    first_generated_at = first_result['generated_at']

    # Small pause to ensure time difference if immutability is broken
    time.sleep(0.01)

    # Second call with same signal_date (upsert conflict should NOT update generated_at)
    second_result = generate_signal(
        conn=tmp_db,
        ticker_a="NVDA",
        ticker_b="CRWV",
        optimal_lag=2,
        correlation_strength=0.85,  # different value to confirm upsert runs
        stability_score=80.0,
        regime_state="Base",
        signal_date="2020-06-01",
    )
    assert second_result is not None

    # Read generated_at from DB -- must equal first_generated_at
    db_row = tmp_db.execute(
        "SELECT generated_at FROM signals WHERE ticker_a=? AND ticker_b=? AND signal_date=?",
        ("NVDA", "CRWV", "2020-06-01"),
    ).fetchone()
    assert db_row is not None
    db_generated_at = db_row[0]
    assert db_generated_at == first_generated_at, (
        f"generated_at was overwritten: original={first_generated_at}, "
        f"after re-run={db_generated_at}"
    )


# ---------------------------------------------------------------------------
# Phase 7: classify_action edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rs_values,rs_std,rs_mean,expected", [
    # BUY condition 1: consistent positive RS (last 3+ sessions all > 0)
    ([0.01, 0.02, 0.03, 0.04, 0.05], 0.02, 0.0, 'BUY'),
    # BUY condition 2: reversal — prior session was negative, recent n_sessions all positive
    ([-0.03, -0.02, -0.01, 0.01, 0.02, 0.03], 0.02, 0.0, 'BUY'),
    # BUY condition 1 with only 3 sessions all positive, no prior negative session available
    ([0.01, 0.02, 0.03], 0.02, 0.0, 'BUY'),
    # SELL: 3 consecutive declining RS sessions
    ([0.05, 0.04, 0.03, 0.02], 0.02, 0.0, 'SELL'),
    # HOLD: oscillating within band (no consistent direction)
    ([0.01, -0.01, 0.01, -0.01], 0.02, 0.0, 'HOLD'),
    # HOLD: insufficient data (len < 3)
    ([0.01, 0.02], 0.02, 0.0, 'HOLD'),
])
def test_classify_action_parametrized(rs_values, rs_std, rs_mean, expected):
    """Phase 7: classify_action returns correct action for a variety of RS inputs."""
    rs_series = pd.Series(rs_values)
    result = classify_action(rs_series, rs_std, rs_mean)
    assert result == expected, (
        f"rs={rs_values}, rs_std={rs_std}, rs_mean={rs_mean}: "
        f"expected {expected!r}, got {result!r}"
    )


def test_classify_action_reversal_requires_prior_negative():
    """Phase 7: rs=[−0.03, −0.02, −0.01, −0.005] (still all negative) must NOT be BUY.

    The last 3 values are all negative so condition 1 fails. The pre-reversal check
    requires last n sessions to be all positive — which they're not. Result is SELL
    because 3 consecutive diffs are negative.
    """
    # Diffs of [-0.03, -0.02, -0.01, -0.005] are [+0.01, +0.01, +0.005] — all positive,
    # so this is NOT a SELL. The last 3 values are [-0.02, -0.01, -0.005] — all negative
    # so condition 1 (all positive) fails. Condition 2 (prior negative AND recent all
    # positive) also fails since recent values are negative. Falls through to HOLD.
    rs_series = pd.Series([-0.03, -0.02, -0.01, -0.005])
    result = classify_action(rs_series, rs_std=0.02, rs_mean=0.0)
    assert result != 'BUY', (
        f"Expected NOT BUY for always-negative declining RS, got {result!r}"
    )


def test_classify_action_always_positive_rs_does_not_trigger_reversal_path():
    """Phase 7: rs always positive should take BUY condition 1, not reversal path.

    Verifies that an always-positive RS series (no prior negative) correctly
    returns BUY via condition 1, not via the reversal path.
    """
    # Six sessions, all positive — no prior negative anywhere
    rs_series = pd.Series([0.01, 0.02, 0.01, 0.03, 0.02, 0.04])
    # pre_reversal = rs_series.iloc[-(3+1)] = rs_series.iloc[2] = 0.01 (positive)
    # So reversal condition is false (pre_reversal >= 0), but condition 1 passes
    result = classify_action(rs_series, rs_std=0.02, rs_mean=0.0)
    assert result == 'BUY', (
        f"Expected BUY via condition 1 for always-positive RS, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Phase 7: compute_rs_slope None-safety
# ---------------------------------------------------------------------------

def test_compute_rs_slope_returns_none_on_empty_table():
    """Phase 7: compute_rs_slope returns None when features_relative_strength is empty."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        """
        CREATE TABLE features_relative_strength (
            ticker_a TEXT, ticker_b TEXT, trading_day TEXT, rs_value REAL
        )
        """
    )
    conn.commit()
    result = compute_rs_slope(conn, 'NVDA', 'CRWV')
    assert result is None
    conn.close()


def test_compute_rs_slope_returns_none_on_sparse_data():
    """Phase 7: compute_rs_slope returns None when fewer than lookback_sessions rows exist."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        """
        CREATE TABLE features_relative_strength (
            ticker_a TEXT, ticker_b TEXT, trading_day TEXT, rs_value REAL
        )
        """
    )
    # Insert only 2 rows; lookback_sessions defaults to 5
    conn.execute(
        "INSERT INTO features_relative_strength VALUES (?, ?, ?, ?)",
        ('NVDA', 'CRWV', '2024-01-01', 0.01),
    )
    conn.execute(
        "INSERT INTO features_relative_strength VALUES (?, ?, ?, ?)",
        ('NVDA', 'CRWV', '2024-01-02', 0.02),
    )
    conn.commit()
    result = compute_rs_slope(conn, 'NVDA', 'CRWV', lookback_sessions=5)
    assert result is None
    conn.close()


# ---------------------------------------------------------------------------
# Phase 7: compute_leader_baseline_return None-safety
# ---------------------------------------------------------------------------

def test_compute_leader_baseline_return_returns_none_on_empty_table():
    """Phase 7: compute_leader_baseline_return returns None when features_lagged_returns is empty."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        """
        CREATE TABLE features_lagged_returns (
            ticker TEXT, trading_day TEXT, lag INTEGER, return_value REAL
        )
        """
    )
    conn.commit()
    result = compute_leader_baseline_return(conn, 'NVDA', 2)
    assert result is None
    conn.close()


# ---------------------------------------------------------------------------
# Phase 7: compute_response_window None-safety
# ---------------------------------------------------------------------------

def _make_response_window_conn() -> sqlite3.Connection:
    """Create minimal in-memory SQLite with signal_transitions and normalized_bars."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        """
        CREATE TABLE signal_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker_a TEXT, ticker_b TEXT, signal_date TEXT,
            from_action TEXT, to_action TEXT NOT NULL, transitioned_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE normalized_bars (
            ticker TEXT, trading_day TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL, vwap REAL,
            PRIMARY KEY (ticker, trading_day)
        )
        """
    )
    conn.commit()
    return conn


def test_compute_response_window_returns_none_on_empty_transitions():
    """Phase 7: compute_response_window returns None when signal_transitions is empty."""
    conn = _make_response_window_conn()
    result = compute_response_window(conn, 'NVDA', 'CRWV')
    assert result is None
    conn.close()


def test_compute_response_window_returns_none_on_single_cycle():
    """Phase 7: compute_response_window returns None when only 1 complete BUY cycle exists (need >= 2)."""
    conn = _make_response_window_conn()
    # Insert one complete BUY->SELL cycle
    conn.execute(
        "INSERT INTO signal_transitions (ticker_a, ticker_b, signal_date, from_action, to_action, transitioned_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ('NVDA', 'CRWV', '2024-01-01', None, 'BUY', '2024-01-01T00:00:00'),
    )
    conn.execute(
        "INSERT INTO signal_transitions (ticker_a, ticker_b, signal_date, from_action, to_action, transitioned_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ('NVDA', 'CRWV', '2024-01-05', 'BUY', 'SELL', '2024-01-05T00:00:00'),
    )
    conn.commit()
    result = compute_response_window(conn, 'NVDA', 'CRWV')
    assert result is None
    conn.close()


# ---------------------------------------------------------------------------
# Phase 7: Transition logging duplicate prevention
# ---------------------------------------------------------------------------

def _setup_transition_db(conn: sqlite3.Connection) -> None:
    """Set up minimal schema for transition logging tests on an existing tmp_db connection."""
    # Insert a ticker pair
    conn.execute(
        "INSERT OR IGNORE INTO ticker_pairs (leader, follower, is_active) VALUES (?, ?, ?)",
        ("AAPL", "MSFT", 1),
    )
    # Insert enough features_lagged_returns for the follower (MSFT) to get a return
    for i in range(5):
        conn.execute(
            "INSERT OR IGNORE INTO features_lagged_returns (ticker, trading_day, lag, return_value) "
            "VALUES (?, ?, ?, ?)",
            ("MSFT", f"2024-01-{i+1:02d}", 2, 0.01),
        )
    # Insert enough returns_policy_a for the leader (AAPL) for invalidation threshold
    for i in range(5):
        conn.execute(
            "INSERT OR IGNORE INTO returns_policy_a (ticker, trading_day, return_1d) "
            "VALUES (?, ?, ?)",
            ("AAPL", f"2024-01-{i+1:02d}", 0.005),
        )
    # Insert a few features_relative_strength rows for RS classify_action
    # Use all-positive to get BUY, or all-oscillating to get HOLD
    conn.commit()


def _insert_rs_for_hold(conn: sqlite3.Connection, ticker_a: str, ticker_b: str) -> None:
    """Insert oscillating RS values that classify_action will map to HOLD."""
    # Oscillating: [0.01, -0.01, 0.01] — mixed, no consistent direction, within std band
    rs_values = [0.01, -0.01, 0.01, -0.01, 0.01]
    for i, v in enumerate(rs_values):
        conn.execute(
            "INSERT OR IGNORE INTO features_relative_strength "
            "(ticker_a, ticker_b, trading_day, rs_value) VALUES (?, ?, ?, ?)",
            (ticker_a, ticker_b, f"2024-01-{i+1:02d}", v),
        )
    conn.commit()


def _insert_rs_for_buy(conn: sqlite3.Connection, ticker_a: str, ticker_b: str) -> None:
    """Insert consistently positive RS values that classify_action will map to BUY."""
    rs_values = [0.01, 0.02, 0.03, 0.04, 0.05]
    for i, v in enumerate(rs_values):
        conn.execute(
            "INSERT OR REPLACE INTO features_relative_strength "
            "(ticker_a, ticker_b, trading_day, rs_value) VALUES (?, ?, ?, ?)",
            (ticker_a, ticker_b, f"2024-01-{i+1:02d}", v),
        )
    conn.commit()


def test_transition_not_logged_on_same_action(tmp_db):
    """Phase 7: Same action repeated does NOT add a second row to signal_transitions.

    Call generate_signal twice with the same action outcome (HOLD) and the same
    signal_date — the second call should be a no-op for signal_transitions.
    """
    _setup_transition_db(tmp_db)
    _insert_rs_for_hold(tmp_db, "AAPL", "MSFT")

    common_args = dict(
        conn=tmp_db, ticker_a="AAPL", ticker_b="MSFT",
        optimal_lag=2, correlation_strength=0.80,
        stability_score=75.0, regime_state="Bull",
        signal_date="2024-01-10",
    )

    # First call: new signal, action goes from None -> HOLD (logged once)
    result1 = generate_signal(**common_args)
    assert result1 is not None
    assert result1['action'] == 'HOLD'

    count_after_first = tmp_db.execute(
        "SELECT COUNT(*) FROM signal_transitions WHERE ticker_a=? AND ticker_b=?",
        ("AAPL", "MSFT"),
    ).fetchone()[0]
    assert count_after_first == 1, (
        f"Expected 1 transition row after first call, got {count_after_first}"
    )

    # Second call: same signal_date, same action (HOLD->HOLD) — must NOT add a row
    result2 = generate_signal(**common_args)
    assert result2 is not None
    assert result2['action'] == 'HOLD'

    count_after_second = tmp_db.execute(
        "SELECT COUNT(*) FROM signal_transitions WHERE ticker_a=? AND ticker_b=?",
        ("AAPL", "MSFT"),
    ).fetchone()[0]
    assert count_after_second == 1, (
        f"Expected still 1 transition row after second HOLD call, got {count_after_second}"
    )


def test_transition_logged_on_action_change(tmp_db):
    """Phase 7: Action change (HOLD -> BUY) adds a second row to signal_transitions."""
    _setup_transition_db(tmp_db)

    # First call: RS = HOLD pattern
    _insert_rs_for_hold(tmp_db, "AAPL", "MSFT")
    result1 = generate_signal(
        conn=tmp_db, ticker_a="AAPL", ticker_b="MSFT",
        optimal_lag=2, correlation_strength=0.80,
        stability_score=75.0, regime_state="Bull",
        signal_date="2024-01-10",
    )
    assert result1 is not None
    assert result1['action'] == 'HOLD'

    count_after_first = tmp_db.execute(
        "SELECT COUNT(*) FROM signal_transitions WHERE ticker_a=? AND ticker_b=?",
        ("AAPL", "MSFT"),
    ).fetchone()[0]
    assert count_after_first == 1

    # Now switch to BUY RS pattern and re-run with a different signal_date
    _insert_rs_for_buy(tmp_db, "AAPL", "MSFT")
    result2 = generate_signal(
        conn=tmp_db, ticker_a="AAPL", ticker_b="MSFT",
        optimal_lag=2, correlation_strength=0.80,
        stability_score=75.0, regime_state="Bull",
        signal_date="2024-01-11",  # new signal_date → new signal row, prev action = None
    )
    assert result2 is not None
    assert result2['action'] == 'BUY'

    count_after_second = tmp_db.execute(
        "SELECT COUNT(*) FROM signal_transitions WHERE ticker_a=? AND ticker_b=?",
        ("AAPL", "MSFT"),
    ).fetchone()[0]
    assert count_after_second == 2, (
        f"Expected 2 transition rows after HOLD then BUY, got {count_after_second}"
    )
