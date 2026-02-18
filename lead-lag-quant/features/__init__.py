"""Feature engineering module for lead-lag-quant.

Public API:
    compute_features_all_pairs(conn) -- orchestrates all FEAT-01 through FEAT-07
    compute_features_for_pair(conn, ticker_a, ticker_b) -- pair-level features
    compute_features_for_ticker(conn, ticker) -- per-ticker features
"""
from features.pipeline import (
    compute_features_all_pairs,
    compute_features_for_pair,
    compute_features_for_ticker,
)

__all__ = [
    "compute_features_all_pairs",
    "compute_features_for_pair",
    "compute_features_for_ticker",
]
