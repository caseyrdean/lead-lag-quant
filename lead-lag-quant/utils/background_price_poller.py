"""Background daemon that keeps paper_positions.current_price continuously fresh.

Runs in a daemon thread — no UI interaction required.  The UI timers
(paper trading, analytics, signal dashboard) become pure DB readers and
can fire at short intervals without triggering Polygon API calls.

Poll intervals:
  Market OPEN:   every LIVE_INTERVAL  seconds (default 60 s)
  Market CLOSED: every CLOSED_INTERVAL seconds (default 300 s)
"""

import threading

from paper_trading.price_poller import is_market_open, poll_and_update_prices
from utils.logging import get_logger

log = get_logger("background_price_poller")

LIVE_INTERVAL   = 60    # seconds — during NYSE trading hours
CLOSED_INTERVAL = 300   # seconds — when market is closed / weekend


class BackgroundPricePoller:
    """Continuously polls Polygon (or DB fallback) and writes current_price
    into paper_positions, independent of which UI tab the user is viewing.
    """

    def __init__(self, conn, api_key: str) -> None:
        self._conn    = conn
        self._api_key = api_key
        self._stop    = threading.Event()

    def start(self) -> None:
        """Start the daemon thread (non-blocking)."""
        t = threading.Thread(
            target=self._loop, daemon=True, name="price-poller"
        )
        t.start()
        log.info("background_price_poller_started",
                 live_interval=LIVE_INTERVAL,
                 closed_interval=CLOSED_INTERVAL)

    def _loop(self) -> None:
        """Poll prices, then sleep for the appropriate interval and repeat."""
        # Brief startup delay so app fully initialises before first poll
        self._stop.wait(15)

        while not self._stop.is_set():
            try:
                poll_and_update_prices(self._conn, self._api_key)
            except Exception as exc:
                log.error("background_price_poll_failed", error=str(exc)[:200])

            interval = LIVE_INTERVAL if is_market_open() else CLOSED_INTERVAL
            self._stop.wait(interval)
