"""Phase 4 pipeline orchestrator: runs the full engine for all active pairs.

CRITICAL ORDERING: classify_regime() MUST be called BEFORE compute_stability_score().
The regime_stability sub-score is an INPUT to the RSI-v2 composite, so regime
classification must happen first. Violating this order produces systematically
low stability scores.

Pipeline per pair:
  1. detect_optimal_lag()           -- ENGINE-01
  2. classify_regime()              -- REGIME-01 (before stability score)
  3. detect_distribution_events()   -- REGIME-02 (after regime, informational)
  4. compute_stability_score()      -- ENGINE-02 (uses regime state)
  5. generate_signal()              -- ENGINE-03 gate + SIGNAL-01/02
"""
import sqlite3
from datetime import date
import pandas as pd
from utils.logging import get_logger
from leadlag_engine.detector import detect_optimal_lag
from leadlag_engine.stability import (
    compute_stability_score,
    lag_persistence_score,
    walk_forward_oos_score,
    rolling_confirmation_score,
    regime_stability_score,
    lag_drift_score,
)
from leadlag_engine.regime import classify_regime
from leadlag_engine.distribution import detect_distribution_events
from signals.generator import generate_signal


def run_engine_for_all_pairs(conn: sqlite3.Connection) -> list[dict]:
    """Run the full Phase 4 engine for all active ticker pairs.

    Reads active pairs from ticker_pairs table (is_active=1).
    Returns list of signal dicts for qualifying signals (those that pass the gate).
    Non-qualifying pairs are logged and skipped -- not treated as errors.

    The returned signal dicts contain the full explainability payload:
    optimal_lag, window_length, correlation_strength, stability_score,
    regime_state, adjustment_policy_id, direction, expected_target,
    invalidation_threshold, sizing_tier, flow_map_entry, generated_at.
    """
    log = get_logger("leadlag_engine.pipeline")

    pairs_df = pd.read_sql_query(
        "SELECT leader AS ticker_a, follower AS ticker_b FROM ticker_pairs WHERE is_active=1",
        conn,
    )

    if pairs_df.empty:
        log.info("pipeline_no_active_pairs")
        return []

    signals_generated = []
    signal_date = date.today().isoformat()

    for _, row in pairs_df.iterrows():
        ticker_a, ticker_b = row['ticker_a'], row['ticker_b']

        # Step 1: Detect optimal lag (ENGINE-01)
        lag_result = detect_optimal_lag(conn, ticker_a, ticker_b)
        if lag_result is None:
            log.info(
                "pipeline_skip_no_lag",
                ticker_a=ticker_a, ticker_b=ticker_b,
            )
            continue

        optimal_lag = lag_result['optimal_lag']
        correlation_strength = lag_result['correlation_strength']

        # Step 2: Classify regime FIRST -- required before stability score (REGIME-01)
        regime = classify_regime(conn, ticker_a, ticker_b)

        # Step 3: Detect distribution events (REGIME-02, informational)
        detect_distribution_events(conn, ticker_b)

        # Step 4: Compute RSI-v2 stability score (ENGINE-02)
        sub_scores = {
            'lag_persistence':      lag_persistence_score(conn, ticker_a, ticker_b, optimal_lag),
            'walk_forward_oos':     walk_forward_oos_score(conn, ticker_a, ticker_b, optimal_lag),
            'rolling_confirmation': rolling_confirmation_score(conn, ticker_a, ticker_b, optimal_lag),
            'regime_stability':     regime_stability_score(regime),  # uses regime from step 2
            'lag_drift':            lag_drift_score(conn, ticker_a, ticker_b),
        }
        stability_score = compute_stability_score(sub_scores)

        log.info(
            "pipeline_stability_computed",
            ticker_a=ticker_a, ticker_b=ticker_b,
            stability_score=round(stability_score, 2),
            correlation_strength=round(correlation_strength, 4),
            regime=regime,
            sub_scores={k: round(v, 1) for k, v in sub_scores.items()},
        )

        # Step 5: Generate signal if gate passes (ENGINE-03, SIGNAL-01, SIGNAL-02)
        signal = generate_signal(
            conn=conn,
            ticker_a=ticker_a,
            ticker_b=ticker_b,
            optimal_lag=optimal_lag,
            correlation_strength=correlation_strength,
            stability_score=stability_score,
            regime_state=regime,
            signal_date=signal_date,
        )

        if signal is not None:
            signals_generated.append(signal)

    log.info(
        "pipeline_complete",
        n_pairs=len(pairs_df),
        n_signals=len(signals_generated),
    )
    return signals_generated
