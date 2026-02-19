"""Tests for SIGNAL-01/02 generator, ENGINE-03 gate, and flow map entry.

Test coverage:
  1. passes_gate boundary conditions (strict > not >=)
  2. determine_sizing_tier thresholds
  3. build_flow_map_entry lag sign convention
  4. generate_signal gate enforcement, direction, policy, immutability
"""
import time
import pytest
import sqlite3
from signals.generator import (
    passes_gate,
    build_flow_map_entry,
    generate_signal,
    STABILITY_THRESHOLD,
    CORRELATION_THRESHOLD,
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
