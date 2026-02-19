"""Polygon snapshot price fetching with NYSE market hours guard.

Uses pandas_market_calendars for accurate holiday/early-close detection.
Price polling only fires during regular NYSE trading hours (9:30-16:00 ET).
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
    """Check if NYSE is currently in regular trading hours (TRADE-05).

    Accounts for holidays and early closes via pandas_market_calendars.
    Returns False on any error (fail closed -- don't poll if check fails).
    """
    try:
        nyse = _get_nyse()
        now_et = pd.Timestamp.now(tz="America/New_York")
        today_str = now_et.strftime("%Y-%m-%d")

        schedule = nyse.schedule(start_date=today_str, end_date=today_str)
        if schedule.empty:
            return False  # Today is a holiday or weekend
        return bool(nyse.open_at_time(schedule, now_et))
    except Exception as exc:
        log.error("market_hours_check_failed", error=str(exc)[:200])
        return False


def fetch_snapshot_price(ticker: str, api_key: str) -> float | None:
    """Fetch the most recent trade price for a ticker from Polygon (TRADE-05).

    Uses fallback chain: lastTrade.p -> min.c -> day.c -> prevDay.c
    Returns float price or None on failure.
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

        # Fallback chain for price extraction
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


def poll_and_update_prices(
    conn: sqlite3.Connection,
    api_key: str,
    portfolio_id: int = 1,
) -> int:
    """Poll Polygon for current prices and update open positions (TRADE-05).

    Only fetches prices during NYSE market hours.
    Returns count of positions with updated prices.
    """
    if not is_market_open():
        log.info("poll_skipped_market_closed")
        return 0

    positions = get_open_positions(conn, portfolio_id)
    if not positions:
        return 0

    tickers = {pos["ticker"] for pos in positions}
    prices: dict[str, float] = {}

    for ticker in tickers:
        price = fetch_snapshot_price(ticker, api_key)
        if price is not None:
            prices[ticker] = price

    if prices:
        now_utc = datetime.now(timezone.utc).isoformat()
        update_position_prices(conn, prices, now_utc)
        log.info("prices_updated", count=len(prices), tickers=list(prices.keys()))

    return len(prices)
