"""Market regime classification using hard rules (REGIME-01).

Four states in priority order (first matching rule wins):
  Failure: ATR expanding (> 130% of 20d ATR mean) AND Bear RS condition
  Bear:    RS < -7% for 5+ consecutive sessions
  Bull:    RS > +5% for 10+ consecutive sessions AND price above 21d MA AND 50d MA
  Base:    Default (everything else)

ATR: Wilder's EWM smoothing. span = 2*period - 1 = 39 for period=20.
     DO NOT use simple rolling mean -- Wilder uses EWM.
     DO NOT use TA-Lib or pandas_ta -- excluded from this project's stack.

RS: from features_relative_strength.rs_value (pre-computed by Phase 3).
    RS is stored as fractional decimal (0.05 = 5%), not percentage.

MA: Simple rolling mean of adj_close from normalized_bars.
    21d MA: rolling(21, min_periods=21)
    50d MA: rolling(50, min_periods=50)

If bars are insufficient (< 50 rows), return 'Failure' as conservative default.
If ATR warm-up incomplete (NaN at tail), treat atr_expanding = False.
"""
import sqlite3
import pandas as pd
from utils.logging import get_logger

_ATR_PERIOD = 20
_ATR_EWM_SPAN = 2 * _ATR_PERIOD - 1  # Wilder's formula: span = 2n - 1 = 39
_MA_SHORT = 21
_MA_LONG = 50
_MIN_BARS_FOR_REGIME = 50  # Need at least 50 bars for 50d MA to be non-NaN

_BULL_RS_THRESHOLD = 0.05    # RS > +5%
_BEAR_RS_THRESHOLD = -0.07   # RS < -7%
_BULL_RS_SESSIONS = 10
_BEAR_RS_SESSIONS = 5
_ATR_EXPANSION_RATIO = 1.30  # Current ATR > 130% of 20d mean ATR


def _compute_atr(bars: pd.DataFrame) -> pd.Series:
    """Wilder's ATR using EWM with span=39 (min_periods=20).

    bars must have columns: high, low, adj_close.
    True Range = max(H-L, |H-prev_C|, |L-prev_C|).
    Returns ATR series aligned to bars.index.
    """
    prev_close = bars['adj_close'].shift(1)
    tr = pd.concat([
        bars['high'] - bars['low'],
        (bars['high'] - prev_close).abs(),
        (bars['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=_ATR_EWM_SPAN, min_periods=_ATR_PERIOD).mean()


def _consecutive_streak(condition: pd.Series) -> int:
    """Count consecutive True values at the tail of a boolean Series.

    Uses pandas groupby-cumsum-cumcount pattern (no manual loop).
    Returns 0 if Series is empty or last value is False.
    """
    if condition.empty or not condition.iloc[-1]:
        return 0
    streak = (
        condition
        .groupby((~condition).cumsum())
        .cumcount() + 1
    )
    streak = streak.where(condition, 0)
    return int(streak.iloc[-1])


def classify_regime(
    conn: sqlite3.Connection,
    ticker_a: str,
    ticker_b: str,
) -> str:
    """Classify current regime for a pair using the follower ticker (ticker_b) bars.

    Reads normalized_bars for ticker_b (follower) and features_relative_strength
    for the pair. Returns 'Bull', 'Base', 'Bear', or 'Failure'.

    Failure returned if data is insufficient for any classification.
    """
    log = get_logger("leadlag_engine.regime")

    # Load bars for follower (ticker_b) -- regime is assessed on the followed instrument
    bars_df = pd.read_sql_query(
        """
        SELECT trading_day, high, low, close, adj_close, adj_volume
        FROM normalized_bars
        WHERE ticker = ?
        ORDER BY trading_day ASC
        """,
        conn,
        params=(ticker_b,),
    )

    if len(bars_df) < _MIN_BARS_FOR_REGIME:
        log.info(
            "regime_insufficient_bars",
            ticker_b=ticker_b, n_bars=len(bars_df), min_required=_MIN_BARS_FOR_REGIME,
        )
        return 'Failure'

    bars_df = bars_df.set_index('trading_day')

    # Load RS series for the pair
    rs_df = pd.read_sql_query(
        """
        SELECT trading_day, rs_value
        FROM features_relative_strength
        WHERE ticker_a = ? AND ticker_b = ?
          AND rs_value IS NOT NULL
        ORDER BY trading_day ASC
        """,
        conn,
        params=(ticker_a, ticker_b),
    )

    if rs_df.empty:
        log.info("regime_no_rs_data", ticker_a=ticker_a, ticker_b=ticker_b)
        return 'Failure'

    rs_series = rs_df.set_index('trading_day')['rs_value']

    # Compute ATR (Wilder EWM)
    atr = _compute_atr(bars_df)
    atr_current = atr.iloc[-1]
    atr_20d_mean = atr.rolling(20).mean().iloc[-1]
    atr_expanding = (
        pd.notna(atr_current) and pd.notna(atr_20d_mean)
        and atr_current > _ATR_EXPANSION_RATIO * atr_20d_mean
    )

    # Compute MAs
    ma_21 = bars_df['adj_close'].rolling(_MA_SHORT, min_periods=_MA_SHORT).mean().iloc[-1]
    ma_50 = bars_df['adj_close'].rolling(_MA_LONG, min_periods=_MA_LONG).mean().iloc[-1]
    latest_price = bars_df['adj_close'].iloc[-1]

    # RS streaks
    bear_condition = rs_series < _BEAR_RS_THRESHOLD
    bull_condition = rs_series > _BULL_RS_THRESHOLD
    bear_streak = _consecutive_streak(bear_condition)
    bull_streak = _consecutive_streak(bull_condition)

    # Priority rule evaluation: Failure > Bear > Bull > Base
    if atr_expanding and bear_streak >= _BEAR_RS_SESSIONS:
        regime = 'Failure'
    elif bear_streak >= _BEAR_RS_SESSIONS:
        regime = 'Bear'
    elif (
        bull_streak >= _BULL_RS_SESSIONS
        and pd.notna(ma_21) and pd.notna(ma_50)
        and latest_price > ma_21
        and latest_price > ma_50
    ):
        regime = 'Bull'
    else:
        regime = 'Base'

    log.info(
        "regime_classified",
        ticker_a=ticker_a, ticker_b=ticker_b, regime=regime,
        bear_streak=bear_streak, bull_streak=bull_streak,
        atr_expanding=atr_expanding,
    )

    # Persist to regime_states table
    conn.execute(
        """
        INSERT INTO regime_states
            (ticker, trading_day, regime, rs_value, price_vs_21ma, price_vs_50ma, atr_ratio)
        VALUES (?, (SELECT MAX(trading_day) FROM normalized_bars WHERE ticker=?),
                ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, trading_day) DO UPDATE SET
            regime       = excluded.regime,
            rs_value     = excluded.rs_value,
            price_vs_21ma = excluded.price_vs_21ma,
            price_vs_50ma = excluded.price_vs_50ma,
            atr_ratio    = excluded.atr_ratio
        """,
        (
            ticker_b, ticker_b, regime,
            float(rs_series.iloc[-1]) if not rs_series.empty else None,
            float(latest_price / ma_21 - 1) if pd.notna(ma_21) else None,
            float(latest_price / ma_50 - 1) if pd.notna(ma_50) else None,
            float(atr_current / atr_20d_mean) if (pd.notna(atr_current) and pd.notna(atr_20d_mean)) else None,
        ),
    )
    conn.commit()

    return regime
