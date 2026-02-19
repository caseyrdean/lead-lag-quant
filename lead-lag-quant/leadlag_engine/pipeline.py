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


def run_engine_for_all_pairs(conn: sqlite3.Connection) -> dict:
    """Run the full Phase 4 engine for all active ticker pairs.

    Reads active pairs from ticker_pairs table (is_active=1).

    Returns a dict:
      signals       -- list of signal dicts for qualifying pairs (pass gate)
      pair_summaries -- list of per-pair outcome dicts for UI display
        Each summary has: ticker_a, ticker_b, outcome, stability_score,
        correlation_strength, data_warning, reason.
    """
    log = get_logger("leadlag_engine.pipeline")

    pairs_df = pd.read_sql_query(
        "SELECT leader AS ticker_a, follower AS ticker_b FROM ticker_pairs WHERE is_active=1",
        conn,
    )

    if pairs_df.empty:
        log.info("pipeline_no_active_pairs")
        return {'signals': [], 'pair_summaries': []}

    signals_generated = []
    pair_summaries = []
    signal_date = date.today().isoformat()

    for _, row in pairs_df.iterrows():
        ticker_a, ticker_b = row['ticker_a'], row['ticker_b']

        # Step 1: Detect optimal lag (ENGINE-01)
        lag_result = detect_optimal_lag(conn, ticker_a, ticker_b)
        if lag_result is None:
            log.info("pipeline_skip_no_lag", ticker_a=ticker_a, ticker_b=ticker_b)
            pair_summaries.append({
                'ticker_a': ticker_a,
                'ticker_b': ticker_b,
                'outcome': 'skipped',
                'reason': 'Insufficient significant correlation days (< 5)',
                'stability_score': None,
                'correlation_strength': None,
                'data_warning': None,
            })
            continue

        optimal_lag = lag_result['optimal_lag']
        correlation_strength = lag_result['correlation_strength']
        limited_data = lag_result.get('limited_data', False)
        significant_days = lag_result.get('significant_days', 30)
        data_warning = (
            f"Limited data: {significant_days} significant days (ideal: 30)"
            if limited_data else None
        )

        # Step 2: Classify regime FIRST -- required before stability score (REGIME-01)
        regime = classify_regime(conn, ticker_a, ticker_b)

        # Step 3: Detect distribution events (REGIME-02, informational)
        detect_distribution_events(conn, ticker_b)

        # Step 4: Compute RSI-v2 stability score (ENGINE-02)
        sub_scores = {
            'lag_persistence':      lag_persistence_score(conn, ticker_a, ticker_b, optimal_lag),
            'walk_forward_oos':     walk_forward_oos_score(conn, ticker_a, ticker_b, optimal_lag),
            'rolling_confirmation': rolling_confirmation_score(conn, ticker_a, ticker_b, optimal_lag),
            'regime_stability':     regime_stability_score(regime),
            'lag_drift':            lag_drift_score(conn, ticker_a, ticker_b),
        }
        stability_score = compute_stability_score(sub_scores)

        log.info(
            "pipeline_stability_computed",
            ticker_a=ticker_a, ticker_b=ticker_b,
            stability_score=round(stability_score, 2),
            correlation_strength=round(correlation_strength, 4),
            regime=regime,
            limited_data=limited_data,
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
            data_warning=data_warning,
        )

        if signal is not None:
            signals_generated.append(signal)
            pair_summaries.append({
                'ticker_a': ticker_a,
                'ticker_b': ticker_b,
                'outcome': 'signal',
                'reason': f"stability={stability_score:.1f}, corr={correlation_strength:.3f}",
                'stability_score': stability_score,
                'correlation_strength': correlation_strength,
                'data_warning': data_warning,
            })
        else:
            from signals.generator import STABILITY_THRESHOLD, CORRELATION_THRESHOLD
            if stability_score <= STABILITY_THRESHOLD:
                reason = f"Stability too low ({stability_score:.1f}, need >{STABILITY_THRESHOLD})"
            else:
                reason = f"Correlation too weak ({abs(correlation_strength):.3f}, need >{CORRELATION_THRESHOLD})"
            pair_summaries.append({
                'ticker_a': ticker_a,
                'ticker_b': ticker_b,
                'outcome': 'gated',
                'reason': reason,
                'stability_score': stability_score,
                'correlation_strength': correlation_strength,
                'data_warning': data_warning,
            })

    log.info(
        "pipeline_complete",
        n_pairs=len(pairs_df),
        n_signals=len(signals_generated),
    )
    return {'signals': signals_generated, 'pair_summaries': pair_summaries}
