"""Background pipeline scheduler: runs the full data pipeline once per trading day.

Logic:
  - Wakes every POLL_INTERVAL seconds (default 900 = 15 min)
  - On each wake, calls _should_run():
      * Skip weekends
      * Skip before 17:00 ET (Polygon EOD data not yet published)
      * Skip if normalized_bars already has today's date
      * Skip if last successful run was already today
  - If all checks pass, runs: ingest → normalize → returns → features → signals
  - Thread-safe status dict readable from the UI at any time

Usage:
    scheduler = PipelineScheduler(conn, client, config)
    scheduler.start()
    label = scheduler.get_status_label()  # call from UI timer
"""

import threading
from datetime import date, datetime, timedelta

import pandas as pd

from utils.logging import get_logger

log = get_logger("pipeline_scheduler")

POLL_INTERVAL = 900        # 15 minutes between checks
PIPELINE_HOUR_ET = 17      # Don't run before 5 PM ET


class PipelineScheduler:
    """Runs the full data-refresh pipeline in a background daemon thread."""

    def __init__(self, conn, client, config):
        self._conn = conn
        self._client = client
        self._config = config
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {
            "status": "idle",          # idle | running | done | error
            "last_run_at": None,       # "YYYY-MM-DD HH:MM ET"
            "last_run_date": None,     # date string of most-recent bar fetched
            "message": "Awaiting first check",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler daemon thread."""
        t = threading.Thread(target=self._loop, daemon=True, name="pipeline-scheduler")
        t.start()
        log.info("pipeline_scheduler_started", poll_interval=POLL_INTERVAL)

    def get_status_label(self) -> str:
        """Return a single-line status string suitable for a gr.Textbox."""
        s = self.status
        parts = []
        if s["last_run_date"]:
            parts.append(f"Data through: {s['last_run_date']}")
        if s["last_run_at"]:
            parts.append(f"Last run: {s['last_run_at']}")
        parts.append(f"Pipeline: {s['status']}")
        if s["message"]:
            parts.append(f"({s['message']})")
        return "  |  ".join(parts)

    @property
    def status(self) -> dict:
        """Thread-safe copy of current status dict."""
        with self._lock:
            return dict(self._status)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, **kwargs) -> None:
        with self._lock:
            self._status.update(kwargs)

    def _latest_trading_day_in_db(self) -> str | None:
        """Return the most recent trading_day in normalized_bars, or None."""
        try:
            row = self._conn.execute(
                "SELECT MAX(trading_day) FROM normalized_bars"
            ).fetchone()
            return row[0] if row and row[0] else None
        except Exception:
            return None

    def _is_trading_day(self, d: date) -> bool:
        """Return True if d is a NYSE trading day."""
        try:
            import pandas_market_calendars as mcal
            nyse = mcal.get_calendar("NYSE")
            schedule = nyse.schedule(start_date=str(d), end_date=str(d))
            return not schedule.empty
        except Exception:
            return d.weekday() < 5  # fallback: Mon–Fri

    def _should_run(self) -> bool:
        """Return True when a pipeline run is warranted."""
        today = date.today()

        if not self._is_trading_day(today):
            return False

        # Don't run before PIPELINE_HOUR_ET (data not published yet)
        now_et = pd.Timestamp.now(tz="America/New_York")
        if now_et.hour < PIPELINE_HOUR_ET:
            return False

        # Already have today's data
        latest = self._latest_trading_day_in_db()
        if latest and latest >= str(today):
            return False

        # Already ran successfully today
        with self._lock:
            last_run_date = self._status.get("last_run_date")
        if last_run_date and last_run_date >= str(today):
            return False

        return True

    def _run_pipeline(self) -> None:
        """Ingest → normalize → returns → features → signals."""
        from ingestion_massive.ingestion import ingest_ticker
        from normalization.normalizer import normalize_all_pairs
        from normalization.returns_calc import compute_returns_all_pairs
        from features.pipeline import compute_features_all_pairs
        from leadlag_engine.pipeline import run_engine_for_all_pairs

        self._set_status(status="running", message="Starting…")
        log.info("pipeline_scheduler_run_started")

        try:
            today = date.today()
            from_date = str(today - timedelta(days=10))
            to_date = str(today)

            pairs = self._conn.execute(
                "SELECT leader, follower FROM ticker_pairs WHERE is_active = 1"
            ).fetchall()

            if not pairs:
                self._set_status(
                    status="done",
                    message="No active pairs",
                    last_run_at=_now_et_str(),
                    last_run_date=str(today),
                )
                return

            tickers: set[str] = {"SPY"}
            for leader, follower in pairs:
                tickers.add(leader.upper())
                tickers.add(follower.upper())

            # --- Ingest ---
            self._set_status(message=f"Ingesting {len(tickers)} tickers…")
            for ticker in sorted(tickers):
                try:
                    ingest_ticker(self._client, self._conn, ticker, from_date, to_date)
                except Exception as exc:
                    log.warning("scheduler_ingest_ticker_failed", ticker=ticker, error=str(exc)[:120])

            # --- Normalize ---
            self._set_status(message="Normalizing…")
            normalize_all_pairs(self._conn)
            compute_returns_all_pairs(self._conn)

            # --- Features + Signals ---
            self._set_status(message="Computing features & signals…")
            compute_features_all_pairs(self._conn)
            run_engine_for_all_pairs(self._conn)

            latest = self._latest_trading_day_in_db()
            self._set_status(
                status="done",
                message=f"Updated through {latest}",
                last_run_at=_now_et_str(),
                last_run_date=str(latest or today),
            )
            log.info("pipeline_scheduler_run_complete", latest_day=latest)

        except Exception as exc:
            log.error("pipeline_scheduler_run_failed", error=str(exc)[:200])
            self._set_status(
                status="error",
                message=str(exc)[:120],
                last_run_at=_now_et_str(),
            )

    def _loop(self) -> None:
        """Main scheduler loop — runs until _stop is set."""
        # Short initial delay so app finishes starting before first check
        self._stop.wait(90)

        while not self._stop.is_set():
            try:
                if self._should_run():
                    self._run_pipeline()
                else:
                    latest = self._latest_trading_day_in_db()
                    if latest and self.status["status"] == "idle":
                        self._set_status(
                            message="Cached",
                            last_run_date=latest,
                        )
            except Exception as exc:
                log.error("pipeline_scheduler_loop_error", error=str(exc)[:200])

            self._stop.wait(POLL_INTERVAL)


def _now_et_str() -> str:
    """Return current Eastern time as 'YYYY-MM-DD HH:MM ET'."""
    return pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d %H:%M ET")
