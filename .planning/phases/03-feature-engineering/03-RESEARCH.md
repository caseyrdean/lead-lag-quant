# Phase 3: Feature Engineering - Research

**Researched:** 2026-02-18
**Domain:** Python scientific computing — rolling statistical features, cross-correlation, residualization, SQLite storage
**Confidence:** HIGH (core scipy/pandas APIs), MEDIUM (schema pattern, Bonferroni approach)

---

## Summary

Phase 3 transforms normalized return series into a set of seven statistically rigorous features (FEAT-01 through FEAT-07). The core technical challenge is the rolling cross-correlation with residualization (FEAT-01, FEAT-02): each 60-day window requires SPY-residualized inputs fed into `scipy.signal.correlate` to produce lag-indexed correlation values at offsets -5 through +5. This cannot be done with a simple `pandas.rolling().apply()` because that only accepts single-column 1D input — the implementation must manually iterate over rolling windows with two aligned series slices.

Residualization against SPY (FEAT-02) is best done via `statsmodels.regression.rolling.RollingOLS` for efficiency, producing rolling beta-adjusted residuals without per-window OLS fits in Python loops. The remaining features (RS, volatility, z-score, lagged returns) are straightforward pandas rolling operations. The only state-of-the-art pitfall is the `pandas.pct_change` `fill_method` parameter: it was deprecated in pandas 2.1 and as of pandas 3.x must be `None` — the prior phase already locked this behavior, so Phase 3 should use residuals and return series that already respect `fill_method=None`.

All feature output is stored in SQLite (raw sqlite3) using a long/normalized schema: one row per (ticker_a, ticker_b, lag, trading_day) for cross-correlation features, and one row per (ticker, trading_day) for per-ticker features. This aligns with the existing schema pattern and allows NULL for rows with insufficient history — a locked prior decision.

**Primary recommendation:** Implement rolling cross-correlation by manually iterating aligned window slices over the DataFrame (not `rolling.apply`), use `statsmodels.regression.rolling.RollingOLS` for residualization, use `scipy.stats.pearsonr` for per-window p-values, apply Bonferroni manually (threshold = 0.05/11), and store all features in normalized long-form SQLite tables.

---

## User Constraints (from Phase Context)

No CONTEXT.md exists. The following are locked decisions extracted from the `## Prior decisions` section in the phase specification:

### Locked Decisions
- SQLite for all storage using raw sqlite3 (no ORM)
- Module layout: `/features` directory for Phase 3
- Returns computed strictly per-ticker from adj_close
- `fill_method=None` for `pct_change` (pandas >= 2.1)
- NULL stored for insufficient history rows (not zero)

### Claude's Discretion
- Internal implementation of rolling cross-correlation loop pattern
- Schema design for feature tables (columns, naming, indexing)
- Choice between `statsmodels.OLS` per-window vs `RollingOLS` for residualization
- Whether to batch-insert or row-insert to SQLite
- How to structure the `/features` module internally

### Deferred Ideas (OUT OF SCOPE)
- Feature selection or dimensionality reduction
- Model training or signal generation
- Any feature not in FEAT-01 through FEAT-07

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy | 1.13+ (1.17 current) | `signal.correlate`, `signal.correlation_lags`, `stats.pearsonr` | Official docs show cross-correlation and lag extraction; standard for signal processing in Python |
| pandas | 2.1+ (3.x current) | Rolling windows, return series manipulation, DataFrame operations | Locked decision; `fill_method=None` requires >= 2.1 |
| numpy | 1.26+ (2.x current) | Array slicing, NaN masking, lagged shift operations | Required by scipy/pandas; used directly for `np.corrcoef` lagged slicing |
| statsmodels | 0.14+ | `regression.rolling.RollingOLS` for SPY residualization | Provides efficient rolling beta without per-window Python OLS loops |
| sqlite3 | stdlib | Database writes for all feature tables | Locked decision — raw sqlite3, no ORM |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| statsmodels.stats.multitest | same as statsmodels | `multipletests(method='bonferroni')` for adjusted p-values | Optional — can also compute threshold manually (0.05/11 = 0.0045) |
| scipy.stats.zscore | same as scipy | Batch z-score computation | Useful for off-window z-scores; rolling z-score done with pandas |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual rolling window loop | `pandas.rolling().apply()` | `rolling.apply()` only accepts 1D single-column; cannot pass two aligned series per window — manual loop required for cross-correlation |
| `statsmodels.regression.rolling.RollingOLS` | Per-window `sm.OLS().fit()` in a loop | Per-window loop is ~10-100x slower for 60-day rolling over 250+ trading days; RollingOLS uses incremental matrix updates |
| `scipy.stats.pearsonr` per lag | `numpy.corrcoef` per lag | Both work; `pearsonr` returns p-value directly; `numpy.corrcoef` does not provide p-value and requires separate significance computation |
| `scipy.signal.correlate` (full output, slice lags) | Loop over lags calling `np.corrcoef` at each shift | `scipy.signal.correlate` computes all lags in one FFT pass but requires slicing the output; loop approach is simpler to read for 11 lags |

**Installation:**
```bash
pip install scipy pandas numpy statsmodels
# sqlite3 is stdlib — no install needed
```

---

## Architecture Patterns

### Recommended Project Structure
```
features/
├── __init__.py              # Exports public compute functions
├── residualize.py           # SPY beta residualization (FEAT-02)
├── cross_correlation.py     # Rolling cross-corr with Bonferroni (FEAT-01, FEAT-03)
├── relative_strength.py     # RS leader/follower (FEAT-04)
├── volatility.py            # Rolling volatility (FEAT-05)
├── zscore.py                # Z-score standardization (FEAT-06)
├── lagged_returns.py        # Lagged return offsets (FEAT-07)
├── db.py                    # SQLite schema creation + insert helpers
└── pipeline.py              # Orchestrates all features for a ticker pair
```

### Pattern 1: Manual Rolling Window Loop for Cross-Correlation

**What:** Because `pandas.rolling().apply()` only accepts a single 1D column, cross-correlation of two series over a rolling window requires explicit window slicing.

**When to use:** Any time the rolling computation requires TWO aligned input series per window (FEAT-01, FEAT-02).

**Example:**
```python
# Source: scipy.signal.correlate docs + cross-correlation pattern
import numpy as np
from scipy import signal, stats

def compute_rolling_xcorr(series_a: np.ndarray,
                           series_b: np.ndarray,
                           window: int = 60,
                           max_lag: int = 5) -> list[dict]:
    """
    Returns one dict per window-end index with correlation + p-value per lag.
    Both series must be pre-residualized (FEAT-02 applied upstream).
    Returns empty list for windows with insufficient data.
    """
    n = len(series_a)
    results = []

    # Precompute all lag offsets we care about
    lags = list(range(-max_lag, max_lag + 1))  # -5 to +5 = 11 lags

    for end in range(window, n + 1):
        a_win = series_a[end - window:end]
        b_win = series_b[end - window:end]

        # Drop windows with any NaN
        mask = ~(np.isnan(a_win) | np.isnan(b_win))
        if mask.sum() < window:
            results.append(None)  # insufficient data -> NULL in DB
            continue

        a_clean = a_win[mask]
        b_clean = b_win[mask]

        # Compute correlation at each lag using pearsonr (gives p-value)
        lag_corrs = {}
        for lag in lags:
            if lag == 0:
                r, p = stats.pearsonr(a_clean, b_clean)
            elif lag > 0:
                # positive lag: b leads a
                r, p = stats.pearsonr(a_clean[lag:], b_clean[:-lag])
            else:
                # negative lag: a leads b
                abs_lag = abs(lag)
                r, p = stats.pearsonr(a_clean[:-abs_lag], b_clean[abs_lag:])
            lag_corrs[lag] = (r, p)

        results.append(lag_corrs)

    return results
```

### Pattern 2: Bonferroni Correction Across 11 Lags (FEAT-03)

**What:** After computing p-values for all 11 lag offsets in a window, apply Bonferroni threshold to determine significance.

**When to use:** Every window in FEAT-01/FEAT-03 processing.

**Example:**
```python
# Manual Bonferroni — simpler and more transparent than multipletests()
BONFERRONI_ALPHA = 0.05
N_LAGS = 11  # lags -5 to +5
BONFERRONI_THRESHOLD = BONFERRONI_ALPHA / N_LAGS  # ≈ 0.004545...

def is_significant(p_value: float) -> bool:
    return p_value < BONFERRONI_THRESHOLD

# Or via statsmodels (equivalent, more formal):
# from statsmodels.stats.multitest import multipletests
# pvals = [lag_corrs[lag][1] for lag in lags]
# reject, _, _, _ = multipletests(pvals, alpha=0.05, method='bonferroni')
```

### Pattern 3: SPY Residualization with RollingOLS (FEAT-02)

**What:** Regress each ticker's returns against SPY returns over a rolling window, use the residuals as beta-neutral returns.

**When to use:** Before computing cross-correlation (FEAT-01). Apply to BOTH tickers in the pair.

**Example:**
```python
# Source: statsmodels.regression.rolling.RollingOLS docs
import statsmodels.api as sm
from statsmodels.regression.rolling import RollingOLS
import pandas as pd

def residualize_against_spy(ticker_returns: pd.Series,
                             spy_returns: pd.Series,
                             window: int = 60) -> pd.Series:
    """
    Returns rolling residuals of ticker_returns ~ SPY.
    First (window - 1) rows will be NaN — stored as NULL per prior decision.
    """
    exog = sm.add_constant(spy_returns)
    model = RollingOLS(ticker_returns, exog, window=window, min_nobs=window)
    results = model.fit(params_only=False)  # Need resid, not just params
    return results.resid  # pandas Series, NaN for early rows
```

### Pattern 4: Rolling Volatility (FEAT-05)

**What:** Standard deviation of returns over a 20-day rolling window.

**Example:**
```python
# Source: pandas rolling docs
def compute_rolling_volatility(returns: pd.Series, window: int = 20) -> pd.Series:
    # min_periods=window means < window rows → NaN → stored as NULL
    return returns.rolling(window=window, min_periods=window).std(ddof=1)
```

### Pattern 5: Rolling Z-Score (FEAT-06)

**What:** Standardize returns using rolling mean and std per ticker.

**Example:**
```python
# Source: pandas rolling docs + saturncloud.io pattern
def compute_rolling_zscore(returns: pd.Series, window: int = 20) -> pd.Series:
    roll = returns.rolling(window=window, min_periods=window)
    return (returns - roll.mean()) / roll.std(ddof=1)
    # Returns NaN for first (window-1) rows — stored as NULL
```

### Pattern 6: Lagged Returns (FEAT-07)

**What:** Compute return value shifted by ±1 to ±5 bars.

**Example:**
```python
# Source: pandas shift docs
def compute_lagged_returns(returns: pd.Series,
                            offsets: list[int] = None) -> pd.DataFrame:
    if offsets is None:
        offsets = list(range(-5, 6))  # -5 to +5, excluding 0
        offsets.remove(0)
    return pd.DataFrame(
        {f"lag_{lag}": returns.shift(-lag) for lag in offsets}
    )
    # Positive lag = future return (forward shift), negative = past
    # NaN at edges — stored as NULL
```

### Pattern 7: Relative Strength (FEAT-04)

**What:** Cumulative 10-day return difference between leader and follower, rolling.

**Example:**
```python
def compute_relative_strength(leader_returns: pd.Series,
                               follower_returns: pd.Series,
                               window: int = 10) -> pd.Series:
    """
    RS = cumulative_return(leader, 10d) - cumulative_return(follower, 10d)
    Cumulative return over window = product of (1 + r_i) - 1
    """
    def cum_return(s: pd.Series, w: int) -> pd.Series:
        return s.rolling(window=w, min_periods=w).apply(
            lambda x: (1 + x).prod() - 1, raw=True
        )
    return cum_return(leader_returns, window) - cum_return(follower_returns, window)
```

### Recommended SQLite Schema

Two table categories: pair-level features and ticker-level features.

```sql
-- FEAT-01, FEAT-03: Cross-correlation per pair, per lag, per date
CREATE TABLE IF NOT EXISTS features_cross_correlation (
    ticker_a        TEXT NOT NULL,
    ticker_b        TEXT NOT NULL,
    trading_day     TEXT NOT NULL,   -- ISO date: YYYY-MM-DD
    lag             INTEGER NOT NULL, -- -5 to +5
    correlation     REAL,            -- NULL if insufficient history
    p_value         REAL,            -- NULL if insufficient history
    is_significant  INTEGER,         -- 0/1 or NULL; Bonferroni-corrected
    PRIMARY KEY (ticker_a, ticker_b, trading_day, lag)
);

-- FEAT-04: Relative Strength per pair per date
CREATE TABLE IF NOT EXISTS features_relative_strength (
    ticker_a        TEXT NOT NULL,   -- leader
    ticker_b        TEXT NOT NULL,   -- follower
    trading_day     TEXT NOT NULL,
    rs_value        REAL,            -- NULL if insufficient history
    PRIMARY KEY (ticker_a, ticker_b, trading_day)
);

-- FEAT-05: Volatility per ticker per date
CREATE TABLE IF NOT EXISTS features_volatility (
    ticker          TEXT NOT NULL,
    trading_day     TEXT NOT NULL,
    volatility_20d  REAL,            -- NULL if insufficient history
    PRIMARY KEY (ticker, trading_day)
);

-- FEAT-06: Z-score standardized returns per ticker per date
CREATE TABLE IF NOT EXISTS features_zscore (
    ticker          TEXT NOT NULL,
    trading_day     TEXT NOT NULL,
    zscore_return   REAL,            -- NULL if insufficient history
    PRIMARY KEY (ticker, trading_day)
);

-- FEAT-07: Lagged returns per ticker per date per lag
CREATE TABLE IF NOT EXISTS features_lagged_returns (
    ticker          TEXT NOT NULL,
    trading_day     TEXT NOT NULL,
    lag             INTEGER NOT NULL, -- -5 to +5, excluding 0
    return_value    REAL,            -- NULL at edges
    PRIMARY KEY (ticker, trading_day, lag)
);
```

**Indexes to add after bulk insert:**
```sql
CREATE INDEX IF NOT EXISTS idx_xcorr_date ON features_cross_correlation(trading_day);
CREATE INDEX IF NOT EXISTS idx_xcorr_pair ON features_cross_correlation(ticker_a, ticker_b);
CREATE INDEX IF NOT EXISTS idx_volatility_ticker ON features_volatility(ticker);
```

### Anti-Patterns to Avoid

- **Using `pandas.rolling().apply()` for cross-correlation:** `rolling.apply()` receives a 1D array for a single column only. There is no supported way to pass two columns per window to a rolling apply without Numba's `method='table'` engine, which is fragile and requires Numba. Use an explicit loop instead.
- **Calling `sm.OLS().fit()` inside a Python loop for each window:** This is 10-100x slower than `RollingOLS`. Each `fit()` call inverts the full matrix; `RollingOLS` uses incremental updates.
- **Storing zero for insufficient history:** The prior decision locks NULL for insufficient rows. Using zero creates false signals in downstream consumers.
- **Computing `scipy.signal.correlate` on full-length series then slicing:** This mixes time periods and produces incorrect rolling correlations. Always slice the window first, then call `correlate`.
- **Using `fill_method` other than `None` in `pct_change`:** Deprecated in pandas 2.1, forbidden in 3.x. Pre-fill with `.ffill()` if needed before calling `pct_change()`, or don't fill at all (locked decision: `fill_method=None`).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rolling OLS / beta estimation | Per-window `sm.OLS().fit()` loop | `statsmodels.regression.rolling.RollingOLS` | Incremental matrix updates, ~100x faster; handles NaN via `missing='drop'` |
| Bonferroni correction | Manual p-value multiplication loop | Either `threshold = 0.05/11` directly OR `statsmodels.stats.multitest.multipletests(method='bonferroni')` | Threshold is trivial here (11 tests); multipletests adds formality if needed |
| Cross-correlation output slicing | Custom lag-index math | `scipy.signal.correlation_lags(len_a, len_b, mode='full')` | Correctly computes lag indices matching `correlate` output positions |
| Significance testing per correlation | Custom t-statistic formula | `scipy.stats.pearsonr(x, y)` | Returns both r and p-value; p-value uses exact beta distribution, not approximation |
| Z-score computation | Manual (x - mean) / std per row | `pandas.rolling().mean()` + `.std()` | Rolling z-score requires rolling mean and std — pandas does this efficiently with min_periods enforcement |

**Key insight:** The only truly custom work in this phase is the outer rolling-window orchestration loop. All statistical primitives (correlation, regression, z-score, significance testing) have well-tested library implementations that handle edge cases (small samples, NaN, numerical precision) that hand-rolled code will get wrong.

---

## Common Pitfalls

### Pitfall 1: pandas rolling.apply Cannot Accept Two Series

**What goes wrong:** Developer tries `df[['a','b']].rolling(60).apply(xcorr_func)` expecting to receive both columns per window. pandas raises a ValueError or silently applies the function to each column separately.

**Why it happens:** The `rolling.apply()` Cython implementation only handles 1D windows. The `method='table'` workaround requires `engine='numba'` which is an optional dependency and has compilation overhead.

**How to avoid:** Use an explicit Python loop over window end-indices. Slice both series using integer indexing. This is the correct pattern for FEAT-01.

**Warning signs:** Getting a DataFrame back from `rolling.apply()` with the same shape as the input — means it applied per-column, not per-pair.

### Pitfall 2: scipy.signal.correlate Full-Mode Output Indexing

**What goes wrong:** `signal.correlate(a, b, mode='full')` returns an array of length `2*N - 1`. Naively indexing it for lags -5 to +5 without using `correlation_lags()` produces off-by-one or wrong-sign lags.

**Why it happens:** The center of the full-mode output is at index `N-1`, not index 0. Manual indexing like `corr[-5:]` does NOT give lag -5 to +5.

**How to avoid:** Always pair `correlate` with `correlation_lags`:
```python
corr = signal.correlate(a, b, mode='full')
lags = signal.correlation_lags(len(a), len(b), mode='full')
# Then filter: mask = (lags >= -5) & (lags <= 5)
lag_values = dict(zip(lags[mask], corr[mask]))
```

**Warning signs:** Cross-correlation at lag 0 does not equal `pearsonr(a, b)[0]` for the same window.

### Pitfall 3: RollingOLS Residuals Alignment

**What goes wrong:** `RollingOLS.fit().resid` returns a Series with index aligned to the INPUT index, not shifted. The first `window-1` rows are NaN. If the index is not properly aligned when joining residuals back to the original DataFrame, all subsequent correlations are shifted by one window.

**Why it happens:** Statsmodels aligns the RollingOLS result at the END of each window (index `i` corresponds to window ending at `i`). This is correct but requires verifying alignment before use.

**How to avoid:** After `results = model.fit()`, assert `len(results.resid) == len(ticker_returns)` and that the index matches exactly. Use `.dropna()` only AFTER merging both residualized series, not before.

**Warning signs:** Cross-correlation matrix is non-zero at lag 0 but the lead-lag structure looks reversed or is all NaN for early dates.

### Pitfall 4: pandas pct_change fill_method in Consumed Data

**What goes wrong:** Phase 3 reads returns from `returns_policy_a` table (computed in Phase 2). If Phase 2 used a non-None `fill_method` in an older pandas version, there may be forward-filled returns in the stored data, corrupting residualization.

**Why it happens:** The `fill_method` deprecation path is: deprecated in 2.1, must be None in 3.x, to be removed in 4.x.

**How to avoid:** Trust the locked prior decision (`fill_method=None`). Phase 3 should read raw return values from `returns_policy_a`; if a return_value is NULL in SQLite it should remain NULL (not filled).

**Warning signs:** Return series have no NaN values even for dates around stock halts or gaps.

### Pitfall 5: Bonferroni Threshold Miscalculation

**What goes wrong:** Developer tests significance at each lag independently with `p < 0.05` instead of the corrected threshold, producing false positives across 11 tests per window per day.

**Why it happens:** Forgetting the multiple-comparison correction when iterating over lags.

**How to avoid:** Define `BONFERRONI_THRESHOLD = 0.05 / 11` as a module-level constant. Never use raw `0.05` for lag significance. FEAT-03 explicitly specifies `threshold = 0.05/11 ≈ 0.0045`.

**Warning signs:** Nearly every window shows at least one significant lag — statistically implausible for random market pairs.

### Pitfall 6: Window Alignment for Relative Strength

**What goes wrong:** RS computation uses `(1 + r).prod() - 1` inside a `rolling.apply()` for 10-day cumulative returns, but does not enforce `min_periods=window`, causing partial-window RS values at the start of the series.

**Why it happens:** Default `min_periods` for integer window is equal to `window` — this is actually correct behavior. But if `min_periods` is explicitly set to 1, partial windows silently compute.

**How to avoid:** Always pass `min_periods=window` (or omit it and rely on the correct default) when the feature requires a full window for validity.

---

## Code Examples

Verified patterns from official sources:

### Cross-Correlation with Lag Extraction (scipy.signal)
```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html
import numpy as np
from scipy import signal

def xcorr_at_lags(a: np.ndarray, b: np.ndarray,
                   max_lag: int = 5) -> dict[int, float]:
    """Cross-correlation at integer lags -max_lag to +max_lag."""
    corr = signal.correlate(a, b, mode='full')
    lags = signal.correlation_lags(len(a), len(b), mode='full')

    # Normalize to produce Pearson-like coefficients
    norm = np.sqrt(np.sum(a**2) * np.sum(b**2))
    corr_normalized = corr / norm if norm > 0 else corr

    mask = (lags >= -max_lag) & (lags <= max_lag)
    return dict(zip(lags[mask].tolist(), corr_normalized[mask].tolist()))
```

### Pearsonr with p-value for per-lag significance
```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html
from scipy.stats import pearsonr

def corr_with_pvalue(a: np.ndarray, b: np.ndarray,
                      lag: int = 0) -> tuple[float, float]:
    """Pearson correlation and p-value at a given lag."""
    if lag > 0:
        r, p = pearsonr(a[lag:], b[:-lag])
    elif lag < 0:
        abs_lag = abs(lag)
        r, p = pearsonr(a[:-abs_lag], b[abs_lag:])
    else:
        r, p = pearsonr(a, b)
    return r, p
```

### RollingOLS Residualization
```python
# Source: https://www.statsmodels.org/stable/generated/statsmodels.regression.rolling.RollingOLS.html
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.rolling import RollingOLS

def get_rolling_residuals(returns: pd.Series, spy_returns: pd.Series,
                           window: int = 60) -> pd.Series:
    """Beta-residualized returns. First (window-1) values are NaN."""
    exog = sm.add_constant(spy_returns, prepend=True)
    model = RollingOLS(returns, exog, window=window, min_nobs=window)
    results = model.fit(params_only=False)
    return results.resid  # pandas Series, index aligned to input
```

### Rolling Volatility (FEAT-05)
```python
# Source: https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.rolling.html
def rolling_volatility(returns: pd.Series, window: int = 20) -> pd.Series:
    return returns.rolling(window=window, min_periods=window).std(ddof=1)
    # NaN for first (window-1) rows -> stored as NULL
```

### Rolling Z-Score (FEAT-06)
```python
def rolling_zscore(returns: pd.Series, window: int = 20) -> pd.Series:
    roll = returns.rolling(window=window, min_periods=window)
    mu = roll.mean()
    sigma = roll.std(ddof=1)
    return (returns - mu) / sigma
    # NaN for first (window-1) rows and when sigma == 0
```

### Lagged Returns (FEAT-07)
```python
# Source: pandas.Series.shift docs
def lagged_returns(returns: pd.Series,
                    offsets: list[int] = None) -> pd.DataFrame:
    if offsets is None:
        offsets = [l for l in range(-5, 6) if l != 0]
    return pd.DataFrame(
        {f"lag_{lag:+d}": returns.shift(-lag) for lag in offsets},
        index=returns.index
    )
    # shift(-1) = 1 bar ahead, shift(+1) = 1 bar behind
    # NaN appears at leading/trailing edges
```

### SQLite Batch Insert Pattern
```python
# Source: sqlite3 stdlib docs
import sqlite3
from typing import Iterable

def batch_insert_xcorr(conn: sqlite3.Connection,
                        rows: Iterable[tuple]) -> None:
    """
    rows: (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
    Uses executemany for performance; commits after all rows.
    """
    sql = """
        INSERT OR REPLACE INTO features_cross_correlation
            (ticker_a, ticker_b, trading_day, lag, correlation, p_value, is_significant)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(sql, rows)
    conn.commit()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pct_change(fill_method='pad')` | `pct_change(fill_method=None)` or `.ffill().pct_change()` | pandas 2.1 (2023) | Using old approach raises FutureWarning in 2.x, TypeError in 3.x |
| Per-window `sm.OLS().fit()` in Python loop | `statsmodels.regression.rolling.RollingOLS` | statsmodels 0.12+ | Massively faster residualization; same results |
| `np.corrcoef` for all lags (no p-value) | `scipy.stats.pearsonr` per lag | N/A (both current) | pearsonr gives p-value directly; corrcoef requires separate significance computation |
| `scipy.signal.correlate` full output, manual center | `scipy.signal.correlation_lags` for index | scipy 1.1+ | Eliminates off-by-one lag indexing errors |

**Deprecated/outdated:**
- `pandas.rolling_std()` (module-level): Removed in pandas 0.25; use `df.rolling().std()` instead
- `fill_method != None` in `pct_change`: Must be `None` in pandas 3.x; removed in 4.x per roadmap
- `statsmodels.OLS` per rolling window loop: Superseded by `RollingOLS` for rolling regression use cases

---

## Open Questions

1. **RollingOLS residuals vs. per-window OLS residuals — are they identical?**
   - What we know: Both methods produce OLS residuals for the same window; RollingOLS is faster
   - What's unclear: Whether `RollingOLS` with `missing='drop'` produces the same residuals as per-window `OLS` with NaN rows dropped, when the window has sparse NaN interior values
   - Recommendation: Add a unit test comparing both methods on a 60-day window with known data; if they match, prefer `RollingOLS`

2. **Cross-correlation normalization: scipy.signal.correlate vs. pearsonr results**
   - What we know: `scipy.signal.correlate` computes cross-correlation sums (not Pearson r) unless explicitly normalized; `pearsonr` computes Pearson r directly
   - What's unclear: The requirement says "use `scipy.signal.correlate`" (FEAT-01) but Bonferroni p-values require a Pearson r or z-statistic; need to decide if the plan uses `correlate` for all lags at once (then normalize + derive p-values from r) or uses `pearsonr` per lag (simpler, gives p-value directly)
   - Recommendation: Use `pearsonr` per lag for clarity and direct p-value access; the `scipy.signal.correlate` requirement in FEAT-01 can be satisfied by using `pearsonr` with manual lag shifts (which implements the same cross-correlation math) OR by using `correlate` for the r values and `pearsonr` for p-values at the peak lag only

3. **Schema: separate table per feature vs. single wide feature table**
   - What we know: Separate normalized tables (one per feature type) align with the existing pattern (`normalized_bars`, `returns_policy_a`) and allow NULL per-cell; a wide table would have many NULL columns
   - What's unclear: Whether downstream consumers (Phase 4+) will prefer a single JOIN-friendly table or separate lookups
   - Recommendation: Use separate normalized tables as designed above; they are easier to populate incrementally and the pattern is consistent with the existing schema

---

## Sources

### Primary (HIGH confidence)
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html` — function signature, mode parameter, return values
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlation_lags.html` — lag index extraction pattern
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html` — p-value computation, two-sided test
- `https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.pct_change.html` — fill_method=None status (pandas 3.0.1)
- `https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.rolling.html` — min_periods behavior, NaN output
- `https://pandas.pydata.org/docs/user_guide/window.html` — rolling.apply raw=True, NaN handling, min_periods semantics
- `https://www.statsmodels.org/stable/generated/statsmodels.regression.rolling.RollingOLS.html` — window parameter, min_nobs, fit() usage
- `https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html` — OLS.fit().resid attribute
- `https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html` — Bonferroni method, return values
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html` — confirmed Bonferroni NOT in this function; statsmodels is correct tool
- `https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.zscore.html` — ddof parameter, nan_policy

### Secondary (MEDIUM confidence)
- `https://github.com/pandas-dev/pandas/issues/53491` — pct_change deprecation timeline: deprecated 2.1, must be None in 3.x, removed in 4.x
- `https://numpy.org/doc/stable/reference/generated/numpy.corrcoef.html` — lagged correlation pattern using manual slicing; NaN handling requires pre-filtering
- `https://jinhyuncheong.com/jekyll/update/2019/05/16/Four_ways_to_qunatify_synchrony.html` — rolling window cross-correlation loop pattern (explicit window slicing approach)
- `https://github.com/pandas-dev/pandas/issues/53235` — confirmed rolling.apply does NOT support multi-column input without Numba; manual loop required

### Tertiary (LOW confidence)
- Various Medium/GeeksForGeeks articles on cross-correlation — cited for confirming standard patterns; not used as authoritative source for any specific claim

---

## Metadata

**Confidence breakdown:**
- Standard stack (scipy, pandas, statsmodels, numpy): HIGH — verified against official docs for all key APIs
- Architecture (rolling loop pattern, RollingOLS, schema design): HIGH — derived from documented API constraints (rolling.apply limitation is confirmed via GitHub issue)
- Bonferroni application: HIGH — threshold formula is mathematically defined in requirement; implementation via multipletests confirmed in docs
- SQLite schema design: MEDIUM — pattern consistent with prior phases and documented best practices; specific column naming is discretionary
- Pitfalls: HIGH for items verified via GitHub issues and official docs; MEDIUM for alignment/edge-case pitfalls (single-source)

**Research date:** 2026-02-18
**Valid until:** 2026-03-20 (scipy, pandas, statsmodels are stable; 30-day window is appropriate)
