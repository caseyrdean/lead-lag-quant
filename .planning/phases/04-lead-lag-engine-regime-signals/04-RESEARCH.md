# Phase 4: Lead-Lag Engine, Regime & Signals - Research

**Researched:** 2026-02-18
**Domain:** Python quantitative finance — lead-lag detection, stability scoring, regime classification, signal generation, SQLite signal storage
**Confidence:** HIGH (core algorithms, SQLite patterns), MEDIUM (RSI-v2 component weights — custom metric, no external source)

---

## Summary

Phase 4 is a pure computation phase: it reads from the five SQLite feature tables produced in Phase 3 and outputs qualifying signals to a new `signals` table. There are no new external API calls, no new Python dependencies (all needed libraries are already installed), and no new Gradio panels. The work is entirely algorithm implementation and SQLite schema design.

The central challenge is the RSI-v2 stability score (ENGINE-02), a custom composite metric with no library equivalent. It has five components: lag persistence consistency, regime stability, rolling window confirmation, walk-forward OOS validation (non-overlapping windows), and lag drift penalty. The component weights have not been defined in prior phases — this is called out as a blocker in STATE.md and MUST be resolved in this phase. Recommended weights are specified in this document and justified below.

Regime classification (REGIME-01, REGIME-02) and signal generation (SIGNAL-01, SIGNAL-02) are conceptually straightforward — they apply hard rules to already-computed feature data. The primary pitfalls are: (1) handling NULL feature rows (insufficient history — a locked prior convention), (2) correctly computing ATR without an external library (TA-Lib is explicitly excluded from the stack), (3) VWAP computation from normalized_bars using (high+low+close)/3 * volume pattern, and (4) ensuring signals table immutability via the upsert pattern with the `generated_at` always reflecting the original creation timestamp.

The split into 04-01 (lag detection + RSI-v2 scoring) and 04-02 (regime + signal generation) is clean: 04-01 produces a pair-level stability assessment from cross-correlation features; 04-02 uses that assessment plus regime state to gate and format signals.

**Primary recommendation:** Implement RSI-v2 as five independently computed sub-scores, each normalized to 0–100, then combine with fixed weights into a scalar. Use pandas rolling operations on features already in SQLite. Compute ATR manually from normalized_bars (high, low, adj_close) using a 20-day EWM. Gate signals with a single boolean check: `stability_score > 70 AND correlation_strength > 0.65`.

---

## User Constraints (from Phase Context)

No CONTEXT.md exists for this phase. The following are locked decisions from the phase specification and STATE.md:

### Locked Decisions
- SQLite for all storage (raw sqlite3, no ORM)
- Module layout: `/leadlag_engine` and `/signals` directories
- ON CONFLICT DO UPDATE upserts, executemany for bulk inserts
- NULL-not-zero convention for insufficient history (from prior phases)
- structlog for logging via `utils/logging.py` `get_logger()`
- `adjustment_policy_id = 'policy_a'` on every signal record
- Hard threshold gate: stability_score > 70 AND correlation_strength > 0.65 (ENGINE-03) — no exceptions, no overrides
- Signals stored immutably in SQLite with full explainability payload (ENGINE-04)

### Claude's Discretion
- RSI-v2 component weights (STATE.md calls this out as undefined — must be specified here)
- Internal implementation of each RSI-v2 sub-score
- SQLite schema for signals and regime tables
- Whether to compute VWAP from stored normalized_bars or store it separately
- Module file layout within /leadlag_engine and /signals
- Walk-forward window sizes (estimation, gap, validation period lengths)
- ATR implementation approach (EWM vs simple rolling, period length)
- Sizing tier thresholds (how stability_score maps to full/half/quarter)

### Deferred Ideas (OUT OF SCOPE)
- AWS DynamoDB signal store (v2 architecture)
- Multi-policy support beyond policy_a
- Intraday / 5-minute bars
- All-pairs exhaustive discovery
- ML-based signals

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | stdlib | Signal storage, feature reads, schema creation | Locked decision — raw sqlite3, no ORM |
| pandas | 2.2+ (locked) | Reading feature tables, rolling computation for RSI-v2 sub-scores | Already in project; rolling windows needed for sub-score computation |
| numpy | 2.1+ (locked) | Array operations, argmax for optimal lag detection, NaN masking | Already in project; needed for stable lag extraction |
| scipy.signal | 1.14+ (locked) | `correlate` + `correlation_lags` for optimal lag extraction from Phase 3 cross-correlation data | Already in project; Phase 3 already used these |
| structlog | 25.4+ (locked) | Structured logging via `get_logger()` | Locked pattern from prior phases |

**No new dependencies need to be installed for Phase 4.** All required libraries are already in pyproject.toml from Phases 1-3.

### Supporting (already installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy.stats | same as scipy | `pearsonr` for per-lag p-value computation if needed during lag confirmation | Already available; used in Phase 3 for significance testing |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual ATR (pandas rolling) | TA-Lib `ATR()` | TA-Lib is explicitly excluded from the stack (see STACK.md) — notoriously painful to compile, no manylinux wheel. Manual ATR is 5 lines of pandas. |
| Manual VWAP computation | `pandas_ta` / `ta` | Both are excluded from the stack — Lambda layer bloat. VWAP from OHLCV is a single expression. |
| Custom stability scalar | scipy `stats` scoring | RSI-v2 is fully custom per the requirement spec. No standard library implements this composite. |

**Installation:**
```bash
# No new packages needed — all dependencies are already installed from Phases 1-3
# Verify: uv run pip list | grep -E "pandas|scipy|numpy|structlog"
```

---

## Architecture Patterns

### Recommended Project Structure
```
leadlag_engine/
├── __init__.py              # Exports detect_optimal_lag(), compute_stability_score()
├── detector.py              # ENGINE-01: optimal lag extraction from features_cross_correlation
├── stability.py             # ENGINE-02: RSI-v2 composite stability score (5 components)
├── regime.py                # REGIME-01: Bull/Base/Bear/Failure classification
├── distribution.py          # REGIME-02: distribution event detection (volume + VWAP rejection)
├── db.py                    # SQLite schema creation + upsert helpers for signals table

signals/
├── __init__.py              # Exports generate_signal(), compute_flow_map_entry()
├── generator.py             # SIGNAL-01: full position spec generation (ENGINE-03 gate + spec)
├── flow_map.py              # SIGNAL-02: directed flow map entry builder (A leads B notation)
├── models.py                # Signal dataclass (optimal_lag, correlation_strength, etc.)
├── thresholds.py            # STABILITY_THRESHOLD = 70, CORRELATION_THRESHOLD = 0.65, sizing tiers
```

### Pattern 1: Optimal Lag Detection (ENGINE-01)

**What:** For a given pair, query `features_cross_correlation` and identify the lag offset with the highest stable (significant) cross-correlation value. "Stable" means Bonferroni-significant (`is_significant = 1`) across the most recent N rolling windows.

**When to use:** Entry point for the Phase 4 pipeline per pair.

**Algorithm:**
1. Query `features_cross_correlation` for the pair, filter `is_significant = 1`
2. For each lag offset (-5 to +5), compute the rolling frequency of significant positive correlation across the last W days
3. The optimal lag is the offset with the highest median `correlation` value across recent significant windows
4. `correlation_strength` is the median correlation at the optimal lag over the estimation window

```python
# Source: scipy.signal.correlation_lags docs + Phase 3 cross-correlation pattern
import sqlite3
import pandas as pd
import numpy as np

def detect_optimal_lag(conn: sqlite3.Connection,
                       ticker_a: str,
                       ticker_b: str,
                       lookback_days: int = 120) -> dict | None:
    """
    Returns {'optimal_lag': int, 'correlation_strength': float} or None if
    insufficient significant observations across lookback window.
    """
    sql = """
        SELECT trading_day, lag, correlation, is_significant
        FROM features_cross_correlation
        WHERE ticker_a = ? AND ticker_b = ?
          AND trading_day >= date('now', ? || ' days')
          AND is_significant = 1
          AND correlation IS NOT NULL
        ORDER BY trading_day ASC
    """
    df = pd.read_sql_query(sql, conn,
                           params=(ticker_a, ticker_b, f'-{lookback_days}'))

    if df.empty:
        return None

    # Group by lag: compute median correlation and frequency (pct of days significant)
    lag_stats = df.groupby('lag')['correlation'].agg(
        median_corr='median',
        count='count'
    )

    # Require at least 30 days of significant observations to consider a lag
    lag_stats = lag_stats[lag_stats['count'] >= 30]
    if lag_stats.empty:
        return None

    # Optimal lag: highest absolute median correlation among eligible lags
    optimal_lag = int(lag_stats['median_corr'].abs().idxmax())
    correlation_strength = float(lag_stats.loc[optimal_lag, 'median_corr'])

    return {
        'optimal_lag': optimal_lag,
        'correlation_strength': correlation_strength,
    }
```

### Pattern 2: RSI-v2 Stability Score (ENGINE-02)

**What:** Five sub-scores combined into a scalar 0–100. Each sub-score is independently computable from Phase 3 feature tables.

**Component weight recommendation (Claude's discretion — see Open Questions):**

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Lag persistence consistency | 30% | Most predictive of future reliability — lag that persists across windows signals structural relationship |
| Walk-forward OOS validation | 25% | Strongest evidence of predictive validity — lag works on data the model never saw |
| Rolling window confirmation | 20% | Verifies lag is not a single-window artifact |
| Regime stability | 15% | Signals are more reliable when computed in stable regime context |
| Lag drift penalty | 10% | Penalizes unstable lag estimation even when correlation is high |

**Sub-score definitions:**

```python
# COMPONENT 1: Lag persistence consistency (0-100)
# How consistently is the optimal lag the same across rolling windows?
# Query features_cross_correlation, identify mode lag per window → % of windows where mode == optimal
def lag_persistence_score(conn, ticker_a, ticker_b, optimal_lag, window_days=20, lookback=120):
    sql = """
        SELECT trading_day,
               lag,
               correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=? AND is_significant=1
          AND trading_day >= date('now', ? || ' days')
        ORDER BY trading_day, ABS(correlation) DESC
    """
    df = pd.read_sql_query(sql, conn, params=(ticker_a, ticker_b, f'-{lookback}'))
    if df.empty:
        return 0.0
    # Per day: which lag has highest |correlation|?
    daily_best = df.loc[df.groupby('trading_day')['correlation'].apply(
        lambda s: s.abs().idxmax()
    )]
    match_pct = (daily_best['lag'] == optimal_lag).mean()
    return match_pct * 100.0  # 0-100

# COMPONENT 2: Walk-forward OOS validation (0-100)
# Non-overlapping windows: estimation window (120d) → gap (5d) → validation window (30d)
# Compute optimal lag on estimation window. Check if the lag performs better than
# random in the validation window. Score = validation correlation magnitude * 100 (capped at 100).
def walk_forward_oos_score(conn, ticker_a, ticker_b, optimal_lag):
    # Estimation window: days -155 to -35 (120d)
    # Gap: days -35 to -30 (5d)
    # Validation window: days -30 to 0 (30d)
    sql = """
        SELECT trading_day, lag, correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=?
          AND lag=?
          AND trading_day >= date('now', '-30 days')
          AND correlation IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn, params=(ticker_a, ticker_b, optimal_lag))
    if len(df) < 15:  # Need at least 15 validation days
        return 0.0
    val_corr = df['correlation'].abs().mean()
    return min(val_corr * 100.0, 100.0)  # Raw correlation 0-1 → 0-100, capped

# COMPONENT 3: Rolling window confirmation (0-100)
# What fraction of the last 60 rolling-window observations show |correlation| > 0.3
# at the optimal lag (regardless of Bonferroni significance)?
def rolling_confirmation_score(conn, ticker_a, ticker_b, optimal_lag, threshold=0.30):
    sql = """
        SELECT correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=? AND lag=?
          AND trading_day >= date('now', '-60 days')
          AND correlation IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn, params=(ticker_a, ticker_b, optimal_lag))
    if df.empty:
        return 0.0
    above_threshold = (df['correlation'].abs() >= threshold).mean()
    return above_threshold * 100.0

# COMPONENT 4: Regime stability (0-100)
# Computed AFTER regime classification — see regime.py
# Score: 100 if Bull or Base (stable); 50 if Bear; 0 if Failure
def regime_stability_score(regime_state: str) -> float:
    return {'Bull': 100.0, 'Base': 100.0, 'Bear': 50.0, 'Failure': 0.0}.get(regime_state, 0.0)

# COMPONENT 5: Lag drift penalty (0-100, inverted — high score = low drift)
# Measure std of the "best lag" per window over the last 120 days.
# Std = 0 → score 100. Std = 3 (across -5 to +5 range) → score 0.
# Linear interpolation between 0 and 3.
def lag_drift_score(conn, ticker_a, ticker_b, lookback=120):
    sql = """
        SELECT trading_day, lag, correlation
        FROM features_cross_correlation
        WHERE ticker_a=? AND ticker_b=? AND is_significant=1
          AND trading_day >= date('now', ? || ' days')
    """
    df = pd.read_sql_query(sql, conn, params=(ticker_a, ticker_b, f'-{lookback}'))
    if df.empty:
        return 0.0
    daily_best_lag = df.loc[df.groupby('trading_day')['correlation'].apply(
        lambda s: s.abs().idxmax()
    )]['lag']
    drift_std = daily_best_lag.std()
    if pd.isna(drift_std):
        return 0.0
    score = max(0.0, 100.0 - (drift_std / 3.0) * 100.0)
    return score

# RSI-v2 COMPOSITE (ENGINE-02)
WEIGHTS = {
    'lag_persistence': 0.30,
    'walk_forward_oos': 0.25,
    'rolling_confirmation': 0.20,
    'regime_stability': 0.15,
    'lag_drift': 0.10,
}

def compute_stability_score(sub_scores: dict) -> float:
    """
    sub_scores: {
        'lag_persistence': float 0-100,
        'walk_forward_oos': float 0-100,
        'rolling_confirmation': float 0-100,
        'regime_stability': float 0-100,
        'lag_drift': float 0-100,
    }
    Returns scalar 0-100.
    """
    return sum(WEIGHTS[k] * sub_scores[k] for k in WEIGHTS)
```

### Pattern 3: Regime Classification (REGIME-01)

**What:** Hard-rule classifier using MA structure, RS thresholds, and ATR regime. Applied per pair (using ticker_a as the "followed" instrument or the pair's follower).

**Rules (in priority order — first matching rule wins):**
- **Failure:** ATR in expansion (> 130% of 20d avg) AND Bear RS condition (RS < -7% for 5+ sessions)
- **Bear:** RS < -7% for 5+ consecutive sessions
- **Bull:** RS > +5% for 10+ consecutive sessions AND price > 21d MA AND price > 50d MA
- **Base:** Everything else (default)

**ATR computation (manual, no TA-Lib):**
```python
# Source: ATR formula (Wilder) verified against multiple sources
# True Range = max(H-L, |H-prev_C|, |L-prev_C|)
# ATR = EWM of True Range over 20 periods (Wilder uses span=20 EWM)

def compute_atr(bars: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    bars: DataFrame with columns high, low, adj_close (from normalized_bars)
    Returns ATR series.
    """
    prev_close = bars['adj_close'].shift(1)
    tr = pd.concat([
        bars['high'] - bars['low'],
        (bars['high'] - prev_close).abs(),
        (bars['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder smoothing = EWM with alpha = 1/period → span = 2*period - 1
    atr = tr.ewm(span=(2 * period - 1), min_periods=period).mean()
    return atr
```

**MA computation:**
```python
# Simple moving averages — pandas rolling mean
def compute_mas(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.copy()
    bars['ma_21'] = bars['adj_close'].rolling(window=21, min_periods=21).mean()
    bars['ma_50'] = bars['adj_close'].rolling(window=50, min_periods=50).mean()
    return bars
```

**Regime classifier:**
```python
def classify_regime(
    rs_series: pd.Series,          # features_relative_strength.rs_value
    bars: pd.DataFrame,            # normalized_bars for the follower ticker
    atr_series: pd.Series,         # pre-computed ATR(20)
) -> str:
    """
    Returns 'Bull', 'Base', 'Bear', or 'Failure' for the CURRENT trading day.
    """
    if rs_series.empty or bars.empty:
        return 'Failure'

    latest_price = bars['adj_close'].iloc[-1]
    ma_21 = bars['adj_close'].rolling(21, min_periods=21).mean().iloc[-1]
    ma_50 = bars['adj_close'].rolling(50, min_periods=50).mean().iloc[-1]

    # ATR regime: is current ATR > 130% of 20d mean ATR?
    atr_current = atr_series.iloc[-1]
    atr_20d_mean = atr_series.rolling(20).mean().iloc[-1]
    atr_expanding = (
        pd.notna(atr_current) and pd.notna(atr_20d_mean)
        and atr_current > 1.30 * atr_20d_mean
    )

    # RS streaks
    rs_recent = rs_series.dropna().tail(10)
    bear_streak = 0
    bull_streak = 0
    for val in rs_recent.values[::-1]:
        if val < -0.07:
            bear_streak += 1
        else:
            break
    for val in rs_recent.values[::-1]:
        if val > 0.05:
            bull_streak += 1
        else:
            break

    # Failure: ATR expanding AND sustained Bear RS
    if atr_expanding and bear_streak >= 5:
        return 'Failure'

    # Bear: RS < -7% for 5+ sessions
    if bear_streak >= 5:
        return 'Bear'

    # Bull: RS > +5% for 10+ sessions AND above both MAs
    price_above_mas = (
        pd.notna(ma_21) and pd.notna(ma_50)
        and latest_price > ma_21
        and latest_price > ma_50
    )
    if bull_streak >= 10 and price_above_mas:
        return 'Bull'

    return 'Base'
```

### Pattern 4: Distribution Detection (REGIME-02)

**What:** Flag down-days where volume > 150% of 30-day avg AND VWAP rejection streak >= 3.

**VWAP calculation from normalized_bars:**
```python
# VWAP = sum(typical_price * volume) / sum(volume) over period
# Typical price = (high + low + close) / 3
# For daily bars, VWAP is already close to adj_close — use adj_volume-weighted close
# normalized_bars has: high, low, close, adj_close, adj_volume

def compute_daily_vwap(bars: pd.DataFrame) -> pd.Series:
    """
    Approximate daily VWAP from OHLCV: (high + low + close) / 3 * volume
    For daily aggregates, this is the session VWAP approximation.
    """
    typical_price = (bars['high'] + bars['low'] + bars['close']) / 3
    vwap = (typical_price * bars['adj_volume']).rolling(window=1).sum() / \
           bars['adj_volume'].rolling(window=1).sum()
    return vwap  # For daily bars, VWAP per day = typical_price (no rolling needed)
```

**Distribution detection:**
```python
def detect_distribution_events(bars: pd.DataFrame) -> pd.DataFrame:
    """
    Returns DataFrame with boolean columns:
    - is_high_volume_down_day: adj_volume > 150% of 30d avg AND close < prev_close
    - vwap_rejection: close below VWAP (close < typical_price for the day)
    - distribution_event: high_volume_down_day AND VWAP rejection streak >= 3
    """
    bars = bars.copy()

    # High volume down days
    avg_vol_30d = bars['adj_volume'].rolling(30, min_periods=30).mean()
    bars['is_down_day'] = bars['adj_close'] < bars['adj_close'].shift(1)
    bars['is_high_volume'] = bars['adj_volume'] > 1.50 * avg_vol_30d
    bars['is_high_volume_down_day'] = bars['is_down_day'] & bars['is_high_volume']

    # VWAP rejection: close < typical price (day closed below its own VWAP)
    typical_price = (bars['high'] + bars['low'] + bars['close']) / 3
    bars['vwap_rejection'] = bars['adj_close'] < typical_price

    # Consecutive VWAP rejection streak
    rejection_streak = (
        bars['vwap_rejection']
        .groupby((~bars['vwap_rejection']).cumsum())
        .cumcount() + 1
    )
    rejection_streak = rejection_streak.where(bars['vwap_rejection'], 0)
    bars['vwap_rejection_streak'] = rejection_streak

    bars['distribution_event'] = (
        bars['is_high_volume_down_day']
        & (bars['vwap_rejection_streak'] >= 3)
    )

    return bars
```

### Pattern 5: Signal Generation Gate and Position Spec (SIGNAL-01, ENGINE-03)

**What:** After computing stability_score and regime, apply the hard gate. If signal passes, build position spec.

**Sizing tier mapping:**
| stability_score | Tier |
|-----------------|------|
| > 85 | full |
| 70 < score <= 85 | half |
| <= 70 | quarter (never emitted — gate blocks it) |

Note: The gate is `stability_score > 70`. Scores at the boundary (71-85) emit half-position signals. Scores > 85 emit full-position signals. Quarter tier is reserved for future use or manual override.

```python
# Source: SIGNAL-01 requirement spec
from dataclasses import dataclass
from datetime import date

STABILITY_THRESHOLD = 70.0
CORRELATION_THRESHOLD = 0.65

def passes_gate(stability_score: float, correlation_strength: float) -> bool:
    return stability_score > STABILITY_THRESHOLD and correlation_strength > CORRELATION_THRESHOLD

def determine_sizing_tier(stability_score: float) -> str:
    if stability_score > 85:
        return 'full'
    elif stability_score > 70:
        return 'half'
    else:
        return 'quarter'  # Gate should prevent this from being reached

def compute_expected_target(conn, ticker_b, optimal_lag, lookback_days=120):
    """
    Historical mean return during lag window: mean of lagged_returns.return_value
    at offset = optimal_lag over the lookback period.
    """
    sql = """
        SELECT return_value
        FROM features_lagged_returns
        WHERE ticker = ? AND lag = ?
          AND trading_day >= date('now', ? || ' days')
          AND return_value IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn,
                           params=(ticker_b, optimal_lag, f'-{lookback_days}'))
    if df.empty:
        return None
    return float(df['return_value'].mean())

def compute_invalidation_threshold(conn, ticker_a, lookback_days=60, multiplier=2.0):
    """
    Leader reversal threshold = multiplier * mean(|1d return|) for leader over lookback.
    Signals exit when leader reverses by this amount.
    """
    sql = """
        SELECT return_value
        FROM returns_policy_a
        WHERE ticker = ? AND period = 'return_1d'
          AND trading_day >= date('now', ? || ' days')
          AND return_value IS NOT NULL
    """
    df = pd.read_sql_query(sql, conn,
                           params=(ticker_a, f'-{lookback_days}'))
    if df.empty:
        return None
    mean_abs_return = df['return_value'].abs().mean()
    return float(mean_abs_return * multiplier)
```

### Pattern 6: Signals Table Schema and Immutable Upsert (ENGINE-04)

**What:** Signals stored with ON CONFLICT DO UPDATE that preserves `generated_at` (never overwrites original creation timestamp) but updates the explainability payload.

**Why "immutable" means `generated_at` is never overwritten:** A signal is the fact that on a given date, the system computed a qualifying signal for a pair. Re-running the engine on the same date should not change when the signal was first generated — only the payload can update if the computation re-runs.

```sql
-- signals table schema
CREATE TABLE IF NOT EXISTS signals (
    ticker_a              TEXT NOT NULL,   -- leader
    ticker_b              TEXT NOT NULL,   -- follower
    signal_date           TEXT NOT NULL,   -- ISO date: YYYY-MM-DD (date generated)
    optimal_lag           INTEGER,         -- sessions
    window_length         INTEGER,         -- rolling window used (days)
    correlation_strength  REAL,
    stability_score       REAL,            -- 0-100 scalar
    regime_state          TEXT,            -- Bull/Base/Bear/Failure
    adjustment_policy_id  TEXT NOT NULL DEFAULT 'policy_a',
    direction             TEXT,            -- 'long' or 'short'
    expected_target       REAL,            -- historical mean return during lag window
    invalidation_threshold REAL,           -- leader reversal % threshold
    sizing_tier           TEXT,            -- full/half/quarter
    flow_map_entry        TEXT,            -- "A leads B" notation
    generated_at          TEXT NOT NULL,   -- ISO datetime — never overwritten on upsert
    PRIMARY KEY (ticker_a, ticker_b, signal_date)
);

CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_ticker_a ON signals(ticker_a);
```

**Upsert preserving generated_at:**
```python
# Source: https://sqlite.org/lang_upsert.html
def upsert_signal(conn: sqlite3.Connection, signal: dict) -> None:
    sql = """
        INSERT INTO signals (
            ticker_a, ticker_b, signal_date,
            optimal_lag, window_length,
            correlation_strength, stability_score,
            regime_state, adjustment_policy_id,
            direction, expected_target, invalidation_threshold,
            sizing_tier, flow_map_entry, generated_at
        ) VALUES (
            :ticker_a, :ticker_b, :signal_date,
            :optimal_lag, :window_length,
            :correlation_strength, :stability_score,
            :regime_state, :adjustment_policy_id,
            :direction, :expected_target, :invalidation_threshold,
            :sizing_tier, :flow_map_entry, :generated_at
        )
        ON CONFLICT(ticker_a, ticker_b, signal_date) DO UPDATE SET
            optimal_lag           = excluded.optimal_lag,
            window_length         = excluded.window_length,
            correlation_strength  = excluded.correlation_strength,
            stability_score       = excluded.stability_score,
            regime_state          = excluded.regime_state,
            direction             = excluded.direction,
            expected_target       = excluded.expected_target,
            invalidation_threshold = excluded.invalidation_threshold,
            sizing_tier           = excluded.sizing_tier,
            flow_map_entry        = excluded.flow_map_entry
            -- generated_at is intentionally NOT updated on conflict
    """
    conn.execute(sql, signal)
    conn.commit()
```

### Pattern 7: Directed Flow Map Entry (SIGNAL-02)

**What:** For each active signal, build a string entry in the format "A leads B by N sessions" stored in `signals.flow_map_entry`.

```python
def build_flow_map_entry(ticker_a: str, ticker_b: str, optimal_lag: int) -> str:
    """
    Positive optimal_lag: ticker_a movements predict ticker_b N sessions later.
    Negative optimal_lag: ticker_b movements predict ticker_a N sessions later.
    """
    lag_abs = abs(optimal_lag)
    if optimal_lag > 0:
        return f"{ticker_a} leads {ticker_b} by {lag_abs} session{'s' if lag_abs != 1 else ''}"
    elif optimal_lag < 0:
        return f"{ticker_b} leads {ticker_a} by {lag_abs} session{'s' if lag_abs != 1 else ''}"
    else:
        return f"{ticker_a} coincident with {ticker_b}"
```

### Pattern 8: Pipeline Orchestrator

**What:** Top-level function that runs the full Phase 4 pipeline for all active pairs.

```python
def run_engine_for_all_pairs(conn: sqlite3.Connection) -> list[dict]:
    """
    For each active pair:
    1. Detect optimal lag (ENGINE-01)
    2. Compute RSI-v2 sub-scores (ENGINE-02) — regime computed first for regime_stability_score
    3. Apply gate (ENGINE-03)
    4. If passes: generate position spec, upsert signal (ENGINE-04, SIGNAL-01, SIGNAL-02)
    Returns list of signal dicts (qualifying signals only).
    """
    pairs = pd.read_sql_query("SELECT ticker_a, ticker_b FROM ticker_pairs", conn)
    signals_generated = []

    log = get_logger(__name__)

    for _, row in pairs.iterrows():
        ticker_a, ticker_b = row['ticker_a'], row['ticker_b']

        lag_result = detect_optimal_lag(conn, ticker_a, ticker_b)
        if lag_result is None:
            log.info("lag_detection_insufficient_data",
                     ticker_a=ticker_a, ticker_b=ticker_b)
            continue

        optimal_lag = lag_result['optimal_lag']
        correlation_strength = lag_result['correlation_strength']

        regime = classify_regime_for_pair(conn, ticker_a, ticker_b)

        sub_scores = {
            'lag_persistence': lag_persistence_score(conn, ticker_a, ticker_b, optimal_lag),
            'walk_forward_oos': walk_forward_oos_score(conn, ticker_a, ticker_b, optimal_lag),
            'rolling_confirmation': rolling_confirmation_score(conn, ticker_a, ticker_b, optimal_lag),
            'regime_stability': regime_stability_score(regime),
            'lag_drift': lag_drift_score(conn, ticker_a, ticker_b),
        }
        stability_score = compute_stability_score(sub_scores)

        log.info("stability_score_computed",
                 ticker_a=ticker_a, ticker_b=ticker_b,
                 stability_score=stability_score,
                 correlation_strength=correlation_strength,
                 sub_scores=sub_scores)

        if not passes_gate(stability_score, correlation_strength):
            log.info("signal_gated",
                     ticker_a=ticker_a, ticker_b=ticker_b,
                     stability_score=stability_score,
                     correlation_strength=correlation_strength)
            continue

        # Build full position spec
        signal = {
            'ticker_a': ticker_a,
            'ticker_b': ticker_b,
            'signal_date': date.today().isoformat(),
            'optimal_lag': optimal_lag,
            'window_length': 60,  # matches FEAT-01 rolling window
            'correlation_strength': correlation_strength,
            'stability_score': stability_score,
            'regime_state': regime,
            'adjustment_policy_id': 'policy_a',
            'direction': 'long',  # positive correlation → follow leader direction
            'expected_target': compute_expected_target(conn, ticker_b, optimal_lag),
            'invalidation_threshold': compute_invalidation_threshold(conn, ticker_a),
            'sizing_tier': determine_sizing_tier(stability_score),
            'flow_map_entry': build_flow_map_entry(ticker_a, ticker_b, optimal_lag),
            'generated_at': pd.Timestamp.utcnow().isoformat(),
        }

        upsert_signal(conn, signal)
        signals_generated.append(signal)

    return signals_generated
```

### Anti-Patterns to Avoid

- **Computing regime AFTER stability score and not including regime_stability_score properly:** Regime must be computed first because it is an input to one of the RSI-v2 sub-scores. Call `classify_regime()` before `compute_stability_score()`.
- **Overwriting `generated_at` on upsert:** The signal's original creation timestamp is the audit anchor. The ON CONFLICT clause must explicitly exclude `generated_at` from the SET list.
- **Using NULL-guard in the wrong direction:** Phase 3 stored NULL for insufficient history. Phase 4 must query with `AND correlation IS NOT NULL` and `AND is_significant = 1` filters, not assume all rows are valid.
- **Hard-coding `lag > 0` as the direction:** Negative lags are valid (ticker_b leads ticker_a). The flow map entry must check the sign of `optimal_lag` to produce the correct direction string.
- **Computing ATR using a simple rolling mean instead of EWM:** Wilder's ATR uses exponential smoothing (EWM), not a simple moving average. `pandas.rolling().mean()` gives SMA-ATR which diverges from standard ATR, affecting regime classification accuracy.
- **Using TA-Lib or pandas_ta:** Both are excluded from the stack. ATR and VWAP must be computed manually.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EWM smoothing for ATR | Custom exponential decay loop | `pandas.Series.ewm(span=39).mean()` | pandas EWM handles boundary conditions, NaN propagation, and warm-up period correctly |
| Rolling window for regime streaks | Manual loop counting consecutive values | `groupby((~condition).cumsum()).cumcount()` pattern | pandas groupby-cumsum-cumcount is the canonical streak counter — handles edge cases cleanly |
| Cross-correlation lag extraction | Re-computing correlations from raw returns | Query `features_cross_correlation` SQLite table (Phase 3 already computed it) | Phase 3 did the expensive computation and stored results; Phase 4 reads and aggregates those results, not recomputes them |
| Bonferroni significance re-checking | Re-testing p-values against threshold | Use `is_significant = 1` filter in SQL query (Phase 3 stored this flag) | Phase 3 stored the significance flag; no need to re-derive it |
| Pearson r for stability sub-scores | Custom correlation computation | Phase 3 feature tables already contain `correlation` values; use them directly | All correlations are pre-computed and stored — Phase 4 only aggregates them |

**Key insight:** Phase 4 is a consumer of Phase 3's expensive computations, not a recomputer. The heavy lifting (rolling cross-correlation across 11 lags, Bonferroni corrections, SPY residualization) is done and stored. Phase 4 reads, aggregates, and classifies — it does not re-run the signal processing.

---

## Common Pitfalls

### Pitfall 1: NULL Propagation from Feature Tables

**What goes wrong:** Phase 3 stored NULL for insufficient history rows. If Phase 4 queries without `WHERE correlation IS NOT NULL`, it includes NULL rows in pandas aggregations which silently become NaN in Python. `df['correlation'].median()` on a series with NaN values in pandas returns NaN (because default is `skipna=True` actually this is fine), but `groupby().idxmax()` fails on all-NaN groups.

**Why it happens:** Developer assumes feature tables are fully populated because Phase 3 "completed successfully." In reality, every pair has the first 59 rows as NULL (60-day rolling window).

**How to avoid:** Always add `AND correlation IS NOT NULL` (or the equivalent for each feature) in every SQL query from Phase 4. Never assume feature rows are non-NULL.

**Warning signs:** `optimal_lag` returning NaN or `detect_optimal_lag()` returning None for pairs that clearly have history. Check `SELECT COUNT(*) FROM features_cross_correlation WHERE correlation IS NOT NULL` to verify data exists.

### Pitfall 2: Lag Sign Convention Confusion

**What goes wrong:** Phase 3 stores lags -5 to +5. A positive lag in the cross-correlation convention used by `scipy.signal.correlate` means "B is shifted forward" (B is leading). The Phase 4 flow map entry and direction must correctly interpret which ticker leads based on the sign.

**Why it happens:** Phase 3 STATE.md decision (03-01): "Manual Python loop for rolling cross-correlation — pandas.rolling().apply() is 1D only." The lag convention in the manual loop follows: positive lag → leader (ticker_a) leads follower (ticker_b). This must be verified by examining Phase 3's cross_correlation.py.

**How to avoid:** Explicitly verify Phase 3's lag sign convention from the actual cross_correlation.py implementation before implementing Phase 4's flow map. The test suite should include a hand-computed example: "if correlation at lag=+2 is maximum, ticker_a movements 2 days ago predict ticker_b today."

**Warning signs:** Flow map entries show "A leads B" when traders expect "B leads A" from domain knowledge.

### Pitfall 3: ATR Warm-Up Period

**What goes wrong:** The EWM ATR requires a warm-up period (`min_periods`). If the bars DataFrame has fewer than 20 rows, `atr.iloc[-1]` returns NaN, and the regime classifier silently treats `atr_expanding = False` — not raising an error, just producing a wrong regime.

**Why it happens:** EWM in pandas does not raise an error when it produces NaN; it just propagates NaN silently.

**How to avoid:** Before classifying regime, check `if pd.isna(atr.iloc[-1]): return 'Failure'` (or 'Base' as a conservative default). Log a warning when this occurs. Require at least 50 bars of history before attempting regime classification.

**Warning signs:** All pairs classified as 'Base' regardless of actual market conditions — ATR is NaN and `atr_expanding` condition evaluates to False consistently.

### Pitfall 4: Walk-Forward Window Alignment

**What goes wrong:** The walk-forward OOS validation uses non-overlapping windows (estimation → gap → validation). If these windows are computed with Python `date` arithmetic relative to `datetime.now()`, the windows shift each day the engine runs. This means the OOS score changes even when no new data has arrived.

**Why it happens:** Using `date('now', '-N days')` in SQLite anchors relative to execution time, not to the most recent trading day. On weekends or holidays, the "validation window" may include fewer trading days than expected.

**How to avoid:** Anchor all windows to `MAX(trading_day)` in the feature table for this pair, not to `datetime.now()`. Use: `SELECT MAX(trading_day) FROM features_cross_correlation WHERE ticker_a=? AND ticker_b=?` first, then compute offsets from that anchor.

**Warning signs:** OOS score fluctuates day-to-day even when no new market data has been ingested.

### Pitfall 5: `generated_at` Being Overwritten

**What goes wrong:** Developer writes the ON CONFLICT DO UPDATE to include `generated_at = excluded.generated_at` (or just wildcards all columns), destroying the original creation timestamp.

**Why it happens:** It is natural to want the most recent execution timestamp on every run. The requirement says signals are "stored immutably" — this means the first-time generation timestamp is the authoritative record.

**How to avoid:** The ON CONFLICT SET list must explicitly enumerate every column EXCEPT `generated_at`. Review the schema and double-check the upsert SQL in code review.

**Warning signs:** Running the engine twice on the same day changes `generated_at` timestamps for existing signals.

### Pitfall 6: Regime Stability Score Computed Before Regime Classification

**What goes wrong:** `compute_stability_score()` needs `regime_stability_score(regime_state)` as an input, but if regime is not yet classified, the value defaults to 0 (or causes a KeyError), producing systematically low stability scores for all pairs.

**Why it happens:** The five RSI-v2 sub-scores appear to be independent, but regime_stability depends on regime classification from REGIME-01.

**How to avoid:** Pipeline must always call `classify_regime()` BEFORE `compute_stability_score()`. This is an explicit ordering constraint in the orchestrator function.

**Warning signs:** All stability scores are unusually low (< 70) even for pairs with strong, persistent correlations — the regime_stability sub-score is contributing 0 because regime was not yet computed.

---

## Code Examples

Verified patterns from official sources:

### SQLite Upsert Pattern (ON CONFLICT DO UPDATE)
```python
# Source: https://sqlite.org/lang_upsert.html
# Use excluded.col to reference the value that would have been inserted
conn.execute("""
    INSERT INTO signals (ticker_a, ticker_b, signal_date, stability_score, generated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(ticker_a, ticker_b, signal_date) DO UPDATE SET
        stability_score = excluded.stability_score
        -- generated_at intentionally omitted from SET list
""", (ticker_a, ticker_b, signal_date, stability_score, generated_at))
```

### Pandas EWM for ATR (Wilder's Smoothing)
```python
# Source: pandas.DataFrame.ewm docs
# Wilder smoothing: alpha = 1/period → span = 2*period - 1
atr = tr.ewm(span=(2 * 20 - 1), min_periods=20).mean()
# Note: min_periods ensures first 19 rows return NaN — stored as NULL if needed
```

### Consecutive Streak Counter (pandas)
```python
# Canonical pandas streak pattern — no loop required
# Source: pandas groupby cumsum cumcount pattern (established pandas idiom)
condition = rs_series < -0.07  # Bear condition
streak = (
    condition
    .groupby((~condition).cumsum())
    .cumcount() + 1
)
streak = streak.where(condition, 0)
bear_streak_today = int(streak.iloc[-1])
```

### scipy.signal.correlate for Lag Extraction
```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html
from scipy import signal
import numpy as np

correlation = signal.correlate(series_a, series_b, mode='full')
lags = signal.correlation_lags(len(series_a), len(series_b), mode='full')
peak_lag = lags[np.argmax(np.abs(correlation))]
```

### Reading Feature Table from SQLite into Pandas
```python
# Source: pandas.read_sql_query docs — standard pattern used in all prior phases
import sqlite3
import pandas as pd

conn = sqlite3.connect('database.db')
df = pd.read_sql_query("""
    SELECT trading_day, lag, correlation
    FROM features_cross_correlation
    WHERE ticker_a = ? AND ticker_b = ?
      AND is_significant = 1
      AND correlation IS NOT NULL
    ORDER BY trading_day ASC
""", conn, params=('NVDA', 'CRWV'))
```

### Batch Upsert with executemany
```python
# Source: sqlite3 stdlib docs — locked pattern from prior phases
rows = [(sig['ticker_a'], sig['ticker_b'], sig['signal_date'], ...)
        for sig in signals]
conn.executemany("""
    INSERT INTO signals (...) VALUES (?, ?, ?, ...)
    ON CONFLICT(ticker_a, ticker_b, signal_date) DO UPDATE SET
        stability_score = excluded.stability_score, ...
""", rows)
conn.commit()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TA-Lib for ATR/VWAP/MA | Manual pandas rolling (5-10 lines) | TA-Lib excluded from this project's stack | TA-Lib has no manylinux wheel; pandas manual implementation is equivalent for daily bars |
| Single composite score from black-box | Decomposed sub-scores with logged weights | Best practice 2024-2025 for explainable quant systems | Sub-scores enable debugging which component is failing; aligns with ENGINE-04 explainability requirement |
| p-value significance per correlation | Pre-computed `is_significant` flag in SQLite | Phase 3 locked this decision | Phase 4 never needs to re-derive p-values — query the flag directly |
| Recomputing cross-correlations in engine | Reading pre-computed results from feature tables | Phase 3 completed | Phase 4 is 10-100x faster because it reads aggregations of stored results, not raw returns |

**Deprecated/outdated for this project:**
- TA-Lib: C-dependency, no manylinux wheel, explicitly excluded in STACK.md
- pandas_ta / ta: Lambda layer bloat, excluded in STACK.md — use manual pandas implementation
- Recomputing features in Phase 4: All cross-correlation, RS, volatility, zscore, lagged returns are already in SQLite from Phase 3

---

## Open Questions

1. **RSI-v2 component weights: are these the right proportions?**
   - What we know: Weights must sum to 1.0, producing a scalar 0-100; the requirement does not specify weights (STATE.md flags this as undefined)
   - What's unclear: Whether the recommended weights (lag_persistence: 30%, walk_forward_oos: 25%, rolling_confirmation: 20%, regime_stability: 15%, lag_drift: 10%) produce the intended screening behavior — specifically, whether real pairs will achieve > 70 or the threshold is too strict
   - Recommendation: Implement with the recommended weights, but log all five sub-scores as part of the explainability payload so that weights can be tuned later without changing the data pipeline. The threshold gate (> 70) can be adjusted by changing `STABILITY_THRESHOLD` in `signals/thresholds.py` without rebuilding the engine.

2. **Walk-forward window sizes: estimation=120d, gap=5d, validation=30d — are these correct?**
   - What we know: The requirement says "non-overlapping estimation/gap/validation windows"; no specific lengths are defined in the requirements
   - What's unclear: Whether 30 days of validation data is sufficient for statistical significance; 120 days of estimation is consistent with Phase 3's rolling window minimum (60d) plus safety margin
   - Recommendation: Use 120/5/30 as stated above. Log the window dates in the explainability payload. If validation window has fewer than 15 trading days of data at the optimal lag, return OOS score = 0 (conservative).

3. **Direction field on signal: how is 'long' vs 'short' determined?**
   - What we know: SIGNAL-01 requires "direction" as part of entry condition; the correlation in `features_cross_correlation` can be positive or negative
   - What's unclear: The requirement does not define whether a negative correlation between leader and follower produces a 'short' signal on the follower or a 'long' signal expecting reversal
   - Recommendation: `direction = 'long'` when `correlation_strength > 0` (follower moves in same direction as leader after lag); `direction = 'short'` when `correlation_strength < 0` (follower moves opposite to leader). This is the natural interpretation. Clarify with user if the signal dashboard displays both directions.

4. **VWAP rejection: is "daily close < daily typical price" the right interpretation?**
   - What we know: REGIME-02 says "VWAP rejection streaks >= 3 consecutive sessions"; for daily bars, the session VWAP is approximated by typical price = (H+L+C)/3; a close below typical price indicates the day closed below its VWAP
   - What's unclear: Whether REGIME-02 intends intraday VWAP (impossible from daily OHLCV) or daily session VWAP (approximated from daily bars)
   - Recommendation: Use daily typical price as the VWAP proxy. This is standard practice for daily OHLCV systems. Document the approximation in code comments.

---

## Sources

### Primary (HIGH confidence)
- `https://sqlite.org/lang_upsert.html` — ON CONFLICT DO UPDATE syntax, `excluded.` prefix semantics
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html` — cross-correlation function signature and mode parameter (verified current: scipy v1.17.0)
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html` — lag index extraction usage with correlate (verified current: scipy v1.17.0)
- Phase 3 RESEARCH.md and STATE.md — locked decisions, data schemas, and lag convention from prior implementation

### Secondary (MEDIUM confidence)
- `https://www.tandfonline.com/doi/full/10.1080/1350486X.2025.2544272` — "Robust Detection of Lead-Lag Relationships in Lagged Multi-Factor Models" (2025) — confirms sliding window l=21 as standard for recent lead-lag research, and that lead-lag structure does not exhibit high persistence (important for weighting walk-forward OOS highly)
- `https://en.wikipedia.org/wiki/Walk_forward_optimization` — walk-forward validation with non-overlapping windows, estimation/gap/validation structure
- Multiple ATR sources confirming Wilder EWM smoothing formula (span = 2*period - 1)
- Multiple VWAP sources confirming typical price = (H+L+C)/3 as the daily bar approximation
- pandas.DataFrame.ewm docs — verified `min_periods` behavior for warm-up

### Tertiary (LOW confidence — single source or training knowledge)
- RSI-v2 component weights (30/25/20/15/10) — derived from first principles based on requirement description; no external authoritative source specifies these weights; they are Claude's recommendation
- Streak counter using `groupby((~condition).cumsum()).cumcount()` — established pandas idiom, widely cited in community but not from official pandas docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries verified in prior phases
- Algorithm for optimal lag detection: HIGH — straightforward aggregation of Phase 3's stored cross-correlation results
- RSI-v2 component weights: LOW — these are Claude's recommendation; no external source defines them; must be validated empirically
- ATR calculation: HIGH — Wilder's formula is well-established; pandas EWM is the standard implementation approach
- VWAP approximation from daily OHLCV: MEDIUM — typical price approach is standard for daily bars but is an approximation of intraday VWAP
- SQLite upsert pattern: HIGH — verified against official SQLite docs
- Walk-forward window sizes (120/5/30): LOW — reasonable defaults, not specified in requirements; empirical validation needed
- Regime classification hard rules: HIGH — rules are fully specified in REGIME-01 requirement; implementation is mechanical

**Research date:** 2026-02-18
**Valid until:** 2026-03-20 (pandas, scipy, SQLite are stable; 30-day window appropriate)
