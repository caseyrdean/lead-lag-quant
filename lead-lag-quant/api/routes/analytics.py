"""Analytics endpoints: trade stats, risk metrics, equity history, ticker breakdown."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.deps import Conn
from paper_trading.analytics import get_risk_metrics, get_trade_stats, get_ticker_breakdown
from paper_trading.market_data import get_portfolio_value_history

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/stats")
def api_stats(conn: Conn):
    try:
        return get_trade_stats(conn)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/risk")
def api_risk(conn: Conn, lookback_days: int = 365):
    try:
        return get_risk_metrics(conn, lookback_days=lookback_days)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/equity")
def api_equity(conn: Conn, lookback_days: int = 365):
    try:
        df = get_portfolio_value_history(conn, lookback_days=lookback_days)
        if df.empty:
            return []
        values = df["value"].astype(float)
        running_peak = values.cummax()
        dd_pct = ((values - running_peak) / running_peak.replace(0, float("nan")) * 100).fillna(0.0)
        df["drawdown_pct"] = dd_pct.round(2)
        return df.to_dict(orient="records")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/ticker-breakdown")
def api_ticker_breakdown(conn: Conn):
    try:
        df = get_ticker_breakdown(conn)
        if df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/pnl-distribution")
def api_pnl_distribution(conn: Conn):
    """Return realized P&L values for all closed trades."""
    try:
        rows = conn.execute(
            "SELECT realized_pnl FROM paper_trades "
            "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = 1"
        ).fetchall()
        return [{"realized_pnl": r[0]} for r in rows]
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/monthly-heatmap")
def api_monthly_heatmap(conn: Conn):
    """Return monthly P&L grouped by year and month."""
    try:
        rows = conn.execute(
            "SELECT strftime('%Y', executed_at) AS year, "
            "       CAST(strftime('%m', executed_at) AS INTEGER) AS month, "
            "       SUM(realized_pnl) AS pnl "
            "FROM paper_trades "
            "WHERE side='sell' AND realized_pnl IS NOT NULL AND portfolio_id = 1 "
            "GROUP BY year, month"
        ).fetchall()
        return [{"year": r[0], "month": r[1], "pnl": round(r[2], 2)} for r in rows]
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
