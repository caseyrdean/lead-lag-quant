"""Distribution event detection (REGIME-02).

A distribution event requires BOTH:
  1. High-volume down day: adj_volume > 150% of 30-day avg volume AND close < prev_close
  2. VWAP rejection streak >= 3 consecutive sessions

VWAP approximation for daily OHLCV: typical_price = (high + low + close) / 3
A VWAP rejection is when the session closes BELOW its typical price (adj_close < typical_price).

Uses canonical pandas streak counter: groupby((~condition).cumsum()).cumcount()
DO NOT use TA-Lib or pandas_ta for VWAP or ATR.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger

_VOLUME_RATIO_THRESHOLD = 1.50    # > 150% of 30d avg
_VWAP_REJECTION_STREAK = 3        # >= 3 consecutive rejection sessions
_VOLUME_LOOKBACK = 30             # days for average volume baseline


def detect_distribution_events(
    conn: sqlite3.Connection,
    ticker: str,
) -> pd.DataFrame:
    """Detect distribution events for a ticker from normalized_bars.

    Returns a DataFrame indexed by trading_day with columns:
      volume_ratio           -- adj_volume / 30d_avg_volume (NaN for first 30 rows)
      vwap_rejection_streak  -- consecutive days closing below typical price (int)
      is_distribution        -- bool: high_volume_down_day AND streak >= 3

    Also upserts results to distribution_events table.
    """
    log = get_logger("leadlag_engine.distribution")

    bars = pd.read_sql_query(
        """
        SELECT trading_day, high, low, close, adj_close, adj_volume
        FROM normalized_bars
        WHERE ticker = ?
        ORDER BY trading_day ASC
        """,
        conn,
        params=(ticker,),
    )

    if bars.empty:
        log.info("distribution_no_bars", ticker=ticker)
        return pd.DataFrame()

    bars = bars.set_index('trading_day')

    # High-volume down days
    avg_vol_30d = bars['adj_volume'].rolling(_VOLUME_LOOKBACK, min_periods=_VOLUME_LOOKBACK).mean()
    bars['volume_ratio'] = bars['adj_volume'] / avg_vol_30d
    is_down_day = bars['adj_close'] < bars['adj_close'].shift(1)
    is_high_volume = bars['adj_volume'] > _VOLUME_RATIO_THRESHOLD * avg_vol_30d
    high_vol_down = is_down_day & is_high_volume

    # VWAP rejection: session closed below its own typical price
    typical_price = (bars['high'] + bars['low'] + bars['close']) / 3
    vwap_rejection = bars['adj_close'] < typical_price

    # Consecutive VWAP rejection streak (pandas idiom, no loop)
    streak = (
        vwap_rejection
        .groupby((~vwap_rejection).cumsum())
        .cumcount() + 1
    )
    streak = streak.where(vwap_rejection, 0).astype(int)
    bars['vwap_rejection_streak'] = streak

    # Distribution event: high-volume down day AND VWAP streak >= threshold
    bars['is_distribution'] = high_vol_down & (streak >= _VWAP_REJECTION_STREAK)

    # Upsert to distribution_events table
    rows = [
        (
            ticker, day,
            None if pd.isna(row['volume_ratio']) else float(row['volume_ratio']),
            int(row['vwap_rejection_streak']),
            1 if row['is_distribution'] else 0,
        )
        for day, row in bars[['volume_ratio', 'vwap_rejection_streak', 'is_distribution']].iterrows()
    ]
    conn.executemany(
        """
        INSERT INTO distribution_events
            (ticker, trading_day, volume_ratio, vwap_rejection_streak, is_flagged)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            volume_ratio          = excluded.volume_ratio,
            vwap_rejection_streak = excluded.vwap_rejection_streak,
            is_flagged            = excluded.is_flagged
        """,
        rows,
    )
    conn.commit()

    log.info(
        "distribution_events_computed",
        ticker=ticker,
        n_events=int(bars['is_distribution'].sum()),
        n_rows=len(bars),
    )

    return bars[['volume_ratio', 'vwap_rejection_streak', 'is_distribution']]
