"""Polygon snapshot price fetching with NYSE market hours guard.

Uses pandas_market_calendars for accurate holiday/early-close detection.

Price update strategy:
  - Market OPEN:  attempt Polygon snapshot for live prices; fall back to
                  normalized_bars adj_close if snapshot is unavailable
                  (e.g. free-tier 403).
  - Market CLOSED: apply latest normalized_bars adj_close so positions
                  always show the most recent closing price rather than NULL.

The UI timer calls poll_and_update_prices every 5 minutes; during market
hours this catches intraday moves; outside hours it holds the closing price.
"""

import sqlite3
from datetime import datetime, timezone

import pandas as pd
import requests

from paper_trading.db import get_open_positions, update_position_prices
from utils.logging import get_logger

log = get_logger("paper_trading.price_poller")

# Lazy-init singleton to avoid import-time expense
_NYSE = None


def _get_nyse():
    """Lazy-initialize and return the NYSE calendar singleton."""
    global _NYSE
    if _NYSE is None:
        import pandas_market_calendars as mcal
        _NYSE = mcal.get_calendar("NYSE")
    return _NYSE


def is_market_open() -> bool:
    """Check if NYSE is currently in regular trading hours.

    Accounts for holidays and early closes via pandas_market_calendars.
    Uses direct schedule comparison (avoids open_at_time's out-of-range error).
    Returns False on any error (fail-closed — don't assume open).
    """
    try:
        nyse = _get_nyse()
        now_et = pd.Timestamp.now(tz="America/New_York")
        today_str = now_et.strftime("%Y-%m-%d")

        schedule = nyse.schedule(start_date=today_str, end_date=today_str)
        if schedule.empty:
            return False  # Today is a holiday or weekend

        market_open = schedule.iloc[0]["market_open"]
        market_close = schedule.iloc[0]["market_close"]
        return bool(market_open <= now_et <= market_close)
    except Exception as exc:
        log.error("market_hours_check_failed", error=str(exc)[:200])
        return False


def fetch_snapshot_price(ticker: str, api_key: str) -> float | None:
    """Fetch the most recent trade price for a ticker from Polygon.

    Uses fallback chain: lastTrade.p -> min.c -> day.c -> prevDay.c
    Returns float price or None on any failure (including free-tier 403).
    """
    url = (
        f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks"
        f"/tickers/{ticker}"
    )
    try:
        resp = requests.get(url, params={"apiKey": api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        tick = data.get("ticker", {})

        price = (
            (tick.get("lastTrade") or {}).get("p")
            or (tick.get("min") or {}).get("c")
            or (tick.get("day") or {}).get("c")
            or (tick.get("prevDay") or {}).get("c")
        )
        if price is not None:
            return float(price)
        return None
    except Exception as exc:
        log.error("fetch_snapshot_price_failed", ticker=ticker, error=str(exc)[:200])
        return None


def apply_db_closing_prices(
    conn: sqlite3.Connection, portfolio_id: int = 1
) -> int:
    """Update open positions with the latest adj_close from normalized_bars.

    Used when market is closed, or as a fallback when Polygon snapshot is
    unavailable.  Ensures positions always carry a price rather than NULL.

    Returns count of positions updated.
    """
    positions = get_open_positions(conn, portfolio_id)
    if not positions:
        return 0

    prices: dict[str, float] = {}
    for pos in positions:
        ticker = pos["ticker"]
        row = conn.execute(
            "SELECT adj_close FROM normalized_bars"
            " WHERE ticker = ? ORDER BY trading_day DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if row:
            prices[ticker] = float(row[0])

    if prices:
        now_utc = datetime.now(timezone.utc).isoformat()
        update_position_prices(conn, prices, now_utc)
        log.info(
            "db_closing_prices_applied",
            count=len(prices),
            tickers=list(prices.keys()),
        )

    return len(prices)


def get_market_status_label(conn: sqlite3.Connection) -> str:
    """Return a human-readable market status string for the UI.

    Examples:
        "Market OPEN  —  live prices polled at 10:32 ET"
        "Market CLOSED  —  showing closing prices as of 2026-02-19"
    """
    try:
        if is_market_open():
            now_et = pd.Timestamp.now(tz="America/New_York")
            return f"Market OPEN  —  live prices  (polled at {now_et.strftime('%H:%M ET')})"

        row = conn.execute(
            "SELECT MAX(trading_day) FROM normalized_bars"
        ).fetchone()
        last_day = row[0] if (row and row[0]) else "no data yet"
        return f"Market CLOSED  —  showing closing prices as of {last_day}"
    except Exception as exc:
        log.error("get_market_status_label_failed", error=str(exc)[:200])
        return "Market status unknown"


def poll_and_update_prices(
    conn: sqlite3.Connection,
    api_key: str,
    portfolio_id: int = 1,
) -> int:
    """Update open-position prices, always providing a value.

    Strategy:
      1. Apply last normalized_bars adj_close as a baseline so positions
         are never price-less (covers the closed-market case immediately).
      2. If market is open, attempt Polygon snapshot prices and override
         the baseline with live values where available.

    Returns count of positions updated.
    """
    # Step 1 — apply DB closing prices as a reliable baseline
    db_count = apply_db_closing_prices(conn, portfolio_id)

    if not is_market_open():
        log.info("poll_market_closed_db_prices_applied", count=db_count)
        return db_count

    # Step 2 — market is open: attempt live Polygon snapshot prices
    positions = get_open_positions(conn, portfolio_id)
    if not positions:
        return db_count

    tickers = {pos["ticker"] for pos in positions}
    live_prices: dict[str, float] = {}

    for ticker in tickers:
        price = fetch_snapshot_price(ticker, api_key)
        if price is not None:
            live_prices[ticker] = price

    if live_prices:
        now_utc = datetime.now(timezone.utc).isoformat()
        update_position_prices(conn, live_prices, now_utc)
        log.info(
            "live_prices_updated",
            count=len(live_prices),
            tickers=list(live_prices.keys()),
        )
        return len(live_prices)

    # Polygon snapshot unavailable (e.g. free-tier 403) — DB prices already set
    log.info("polygon_snapshot_unavailable_using_db_prices")
    return db_count
