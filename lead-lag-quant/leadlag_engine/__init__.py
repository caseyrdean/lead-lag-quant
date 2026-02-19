"""Lead-lag engine package.

Public API:
  run_engine_for_all_pairs(conn) -- full pipeline orchestrator
  detect_optimal_lag(conn, ticker_a, ticker_b) -- ENGINE-01
  compute_stability_score(sub_scores) -- ENGINE-02
  classify_regime(conn, ticker_a, ticker_b) -- REGIME-01
"""
from leadlag_engine.pipeline import run_engine_for_all_pairs
from leadlag_engine.detector import detect_optimal_lag
from leadlag_engine.stability import compute_stability_score
from leadlag_engine.regime import classify_regime

__all__ = [
    "run_engine_for_all_pairs",
    "detect_optimal_lag",
    "compute_stability_score",
    "classify_regime",
]
