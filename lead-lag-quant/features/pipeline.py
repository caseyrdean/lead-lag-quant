"""Feature engineering pipeline orchestrator (Phase 3).

compute_features_for_pair(conn, ticker_a, ticker_b):
  - FEAT-01/02/03: rolling cross-correlation (residualized, Bonferroni-corrected)
  - FEAT-04: relative strength (leader minus follower cumulative return, 10d rolling)

compute_features_for_ticker(conn, ticker):
  - FEAT-05: rolling volatility (20d std)
  - FEAT-06: z-score standardized returns (20d rolling)
  - FEAT-07: lagged returns (offsets +/-1 through +/-5)

compute_features_all_pairs(conn):
  - Reads all active pairs from ticker_pairs.
  - Calls compute_features_for_pair for each pair.
  - Calls compute_features_for_ticker for each unique ticker + SPY.
  - Returns a summary dict.
"""
import sqlite3
from utils.logging import get_logger
from features.cross_correlation import compute_rolling_xcorr_for_pair
from features.relative_strength import compute_relative_strength_for_pair
from features.volatility import compute_volatility_for_ticker
from features.zscore import compute_zscore_for_ticker
from features.lagged_returns import compute_lagged_returns_for_ticker


def compute_features_for_pair(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
) -> dict:
    """Compute pair-level features (FEAT-01 through FEAT-04) for one pair.

    Args:
        conn: Active SQLite connection.
        ticker_a: First ticker (leader).
        ticker_b: Second ticker (follower).

    Returns:
        Dict with counts: {"xcorr": N, "rs": N}
    """
    log = get_logger("features.pipeline").bind(ticker_a=ticker_a, ticker_b=ticker_b)
    log.info("pair_features_start")

    xcorr_count = compute_rolling_xcorr_for_pair(conn, ticker_a, ticker_b)
    rs_count = compute_relative_strength_for_pair(conn, ticker_a, ticker_b)

    result = {"xcorr": xcorr_count, "rs": rs_count}
    log.info("pair_features_complete", **result)
    return result


def compute_features_for_ticker(
    conn: sqlite3.Connection,
    ticker: str,
) -> dict:
    """Compute per-ticker features (FEAT-05 through FEAT-07) for one ticker.

    Args:
        conn: Active SQLite connection.
        ticker: Ticker symbol.

    Returns:
        Dict with counts: {"volatility": N, "zscore": N, "lagged_returns": N}
    """
    log = get_logger("features.pipeline").bind(ticker=ticker)
    log.info("ticker_features_start")

    vol_count = compute_volatility_for_ticker(conn, ticker)
    zscore_count = compute_zscore_for_ticker(conn, ticker)
    lag_count = compute_lagged_returns_for_ticker(conn, ticker)

    result = {"volatility": vol_count, "zscore": zscore_count, "lagged_returns": lag_count}
    log.info("ticker_features_complete", **result)
    return result


def compute_features_all_pairs(conn: sqlite3.Connection) -> dict:
    """Compute all features for all active pairs including SPY.

    Reads ticker_pairs for all active pairs. Computes pair-level features
    for each (leader, follower). Computes per-ticker features for each unique
    ticker plus SPY.

    Args:
        conn: Active SQLite connection.

    Returns:
        Dict: {"pairs": {(a, b): {...}}, "tickers": {ticker: {...}}}
    """
    log = get_logger("features.pipeline")

    pair_rows = conn.execute(
        "SELECT leader, follower FROM ticker_pairs WHERE is_active = 1"
    ).fetchall()

    if not pair_rows:
        log.info("no_active_pairs")
        return {"pairs": {}, "tickers": {}}

    tickers: set[str] = {"SPY"}
    pair_results: dict = {}

    for row in pair_rows:
        ticker_a = row["leader"]
        ticker_b = row["follower"]
        tickers.add(ticker_a)
        tickers.add(ticker_b)
        pair_results[(ticker_a, ticker_b)] = compute_features_for_pair(
            conn, ticker_a, ticker_b
        )

    ticker_results: dict = {}
    for ticker in sorted(tickers):
        ticker_results[ticker] = compute_features_for_ticker(conn, ticker)

    log.info(
        "features_all_pairs_complete",
        pairs=len(pair_results),
        tickers=len(ticker_results),
    )
    return {"pairs": pair_results, "tickers": ticker_results}
