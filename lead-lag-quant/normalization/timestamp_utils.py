"""NYSE trading day assignment from Polygon Unix millisecond timestamps."""
import exchange_calendars as xcals
import pandas as pd

_nyse_calendar = xcals.get_calendar("XNYS")  # module-level singleton -- expensive, create once


def unix_ms_to_trading_day(unix_ms: int) -> str:
    """Convert Polygon Unix millisecond timestamp to NYSE trading day string.

    Args:
        unix_ms: Unix timestamp in milliseconds (UTC), as returned by Polygon aggs API.

    Returns:
        NYSE trading session date as 'YYYY-MM-DD' string.
        Uses direction='next': if timestamp is a non-trading minute (weekend/holiday),
        maps to next valid session. For Polygon daily bars, 't' is the session open
        timestamp and maps to its own session.
    """
    utc_ts = pd.Timestamp(unix_ms, unit="ms", tz="UTC")
    session = _nyse_calendar.minute_to_session(utc_ts, direction="next")
    return session.strftime("%Y-%m-%d")
