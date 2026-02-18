"""SPY beta residualization for return series (FEAT-02).

Uses statsmodels.regression.rolling.RollingOLS for efficient rolling beta
estimation. Per-window sm.OLS().fit() is ~100x slower and MUST NOT be used.

Returns rolling residuals: ticker_return - beta * spy_return - alpha.
First (window - 1) rows will be NaN -- stored as NULL per project convention.

Note on statsmodels 0.14: RollingRegressionResults does not expose a .resid
attribute. Residuals are computed manually as: y - (const + spy_coef * spy).
"""
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.rolling import RollingOLS
from utils.logging import get_logger


def residualize_against_spy(
    ticker_returns: pd.Series,
    spy_returns: pd.Series,
    window: int = 60,
) -> pd.Series:
    """Residualize ticker_returns against SPY over a rolling window.

    Args:
        ticker_returns: Daily return series for the ticker. Index must be
            aligned with spy_returns (same trading days).
        spy_returns: Daily return series for SPY. Must share index with
            ticker_returns.
        window: Rolling window size in trading days. Default 60 per FEAT-02.

    Returns:
        pd.Series of rolling OLS residuals, same index as ticker_returns.
        First (window - 1) rows are NaN. NaN stored as NULL downstream.
        If len(ticker_returns) < window, all rows are NaN.

    Raises:
        ValueError: If indices are not aligned.
    """
    if not ticker_returns.index.equals(spy_returns.index):
        raise ValueError(
            "ticker_returns and spy_returns must have identical indices. "
            f"Got {len(ticker_returns)} vs {len(spy_returns)} rows."
        )

    log = get_logger("features.residualize")

    # Guard: if series is shorter than window, return all-NaN series
    if len(ticker_returns) < window:
        log.debug(
            "series_too_short_for_window",
            n_rows=len(ticker_returns),
            window=window,
        )
        return pd.Series(
            [float("nan")] * len(ticker_returns),
            index=ticker_returns.index,
            name=ticker_returns.name,
        )

    # Add constant term (intercept) to regressors
    exog = sm.add_constant(spy_returns, prepend=True)

    # min_nobs=window enforces full-window requirement:
    # windows with < window observations produce NaN params.
    # missing='drop' handles NaN in input series gracefully.
    model = RollingOLS(
        ticker_returns,
        exog,
        window=window,
        min_nobs=window,
        missing="drop",
    )
    results = model.fit(params_only=False)

    # statsmodels 0.14: RollingRegressionResults has no .resid attribute.
    # Residuals are computed manually: y - (alpha + beta * spy).
    # params columns: [const, spy_column_name]
    params = results.params
    const_col = params.columns[0]
    spy_col = params.columns[1]
    predicted = params[const_col] + params[spy_col] * spy_returns
    residuals = ticker_returns - predicted

    # Verify alignment: residuals must have same length as input
    assert len(residuals) == len(ticker_returns), (
        f"Residuals length {len(residuals)} != "
        f"input length {len(ticker_returns)}"
    )

    log.debug(
        "residualization_complete",
        n_rows=len(residuals),
        n_nan=int(residuals.isna().sum()),
    )
    return residuals
