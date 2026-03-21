"""Backtest endpoints: run backtest, cross-correlation heatmap, regime state."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.deps import Conn
from backtest.engine import run_backtest, xcorr_data, regime_state

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.get("/run")
def api_run_backtest(
    conn: Conn,
    leader: str,
    follower: str,
    start_date: str,
    end_date: str,
):
    try:
        return run_backtest(conn, leader, follower, start_date, end_date)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/xcorr")
def api_xcorr(
    conn: Conn,
    leader: str,
    follower: str,
    days: int = 60,
):
    try:
        return xcorr_data(conn, leader, follower, days)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/regime")
def api_regime(
    conn: Conn,
    leader: str,
    follower: str,
):
    # Leader param accepted for consistency; regime is follower-keyed per research
    try:
        return regime_state(conn, follower)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
