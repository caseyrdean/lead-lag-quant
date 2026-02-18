"""NYSE trading calendar helpers using exchange_calendars."""

import exchange_calendars as xcals

# Cache the calendar instance at module level (expensive to create)
_nyse_calendar = None


def get_nyse_calendar():
    """Get the NYSE trading calendar (cached).

    Returns:
        The XNYS (NYSE) exchange calendar instance.
    """
    global _nyse_calendar
    if _nyse_calendar is None:
        _nyse_calendar = xcals.get_calendar("XNYS")
    return _nyse_calendar


def get_trading_days(start: str, end: str) -> list[str]:
    """Get NYSE trading days between start and end dates.

    Args:
        start: Start date in YYYY-MM-DD format.
        end: End date in YYYY-MM-DD format.

    Returns:
        List of YYYY-MM-DD strings for NYSE sessions in the range.
    """
    cal = get_nyse_calendar()
    sessions = cal.sessions_in_range(start, end)
    return [s.strftime("%Y-%m-%d") for s in sessions]


def is_trading_day(date: str) -> bool:
    """Check if a date is an NYSE trading day.

    Args:
        date: Date string in YYYY-MM-DD format.

    Returns:
        True if the date is an NYSE trading session.
    """
    cal = get_nyse_calendar()
    return cal.is_session(date)
