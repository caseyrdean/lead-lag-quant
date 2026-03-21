"""Paper trading endpoints: buy, sell, positions, portfolio, history, price chart."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.deps import Conn, Config
from paper_trading.engine import (
    close_position,
    get_open_positions_display,
    get_portfolio_summary,
    get_trade_history_display,
    open_or_add_position,
    set_capital,
)
from paper_trading.price_poller import fetch_snapshot_price

router = APIRouter(prefix="/trading", tags=["trading"])


class SetCapitalRequest(BaseModel):
    starting_capital: float


class BuyRequest(BaseModel):
    ticker: str
    shares: int = Field(gt=0)  # BUGFIX-06: reject shares=0 or negative
    price: float | None = Field(default=None, gt=0)  # BUGFIX-06: reject price<=0; None=fetch from Polygon
    source_signal_id: int | None = None
    invalidation_threshold: float | None = None


class SellRequest(BaseModel):
    ticker: str
    shares: int = Field(gt=0)  # BUGFIX-06: reject shares=0 or negative
    price: float | None = Field(default=None, gt=0)  # BUGFIX-06: reject price<=0; None=fetch from Polygon


@router.post("/capital")
def api_set_capital(body: SetCapitalRequest, conn: Conn):
    result = set_capital(conn, body.starting_capital)
    return result


@router.get("/positions")
def api_positions(conn: Conn):
    return get_open_positions_display(conn)


@router.get("/portfolio")
def api_portfolio(conn: Conn):
    return get_portfolio_summary(conn)


@router.get("/history")
def api_history(conn: Conn):
    rows = get_trade_history_display(conn)
    return [dict(r) for r in rows]


@router.post("/buy")
def api_buy(body: BuyRequest, conn: Conn, config: Config):
    price = body.price
    if price is None:
        price = fetch_snapshot_price(body.ticker, config.polygon_api_key)
    if price is None:
        return {"error": f"Could not fetch price for {body.ticker}"}

    now = datetime.now(timezone.utc).isoformat()
    open_or_add_position(
        conn,
        portfolio_id=1,
        ticker=body.ticker.upper(),
        shares=body.shares,
        price=price,
        source_signal_id=body.source_signal_id,
        invalidation_threshold=body.invalidation_threshold,
        executed_at=now,
    )
    return {"status": "ok", "ticker": body.ticker.upper(), "shares": body.shares, "price": price}


@router.post("/sell")
def api_sell(body: SellRequest, conn: Conn, config: Config):
    price = body.price
    if price is None:
        price = fetch_snapshot_price(body.ticker, config.polygon_api_key)
    if price is None:
        return {"error": f"Could not fetch price for {body.ticker}"}

    now = datetime.now(timezone.utc).isoformat()
    try:
        realized_pnl = close_position(
            conn,
            portfolio_id=1,
            ticker=body.ticker.upper(),
            shares_to_close=body.shares,
            close_price=price,
            executed_at=now,
        )
        return {"status": "ok", "ticker": body.ticker.upper(), "shares": body.shares, "price": price, "realized_pnl": realized_pnl}
    except ValueError as exc:
        return {"error": str(exc)}


@router.get("/price-chart/{ticker}")
def api_price_chart(ticker: str, conn: Conn, days: int = 365):
    """Return OHLCV + technical indicators from normalized_bars."""
    from paper_trading.market_data import get_price_history, compute_indicators
    import math

    df = get_price_history(conn, ticker.upper(), days=days)
    if df.empty:
        return []

    df = compute_indicators(df)

    def _safe(v: float) -> float | None:
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return None
        return round(v, 4)

    data = []
    for _, row in df.iterrows():
        data.append({
            "time": row["trading_day"].strftime("%Y-%m-%d") if hasattr(row["trading_day"], "strftime") else str(row["trading_day"])[:10],
            "open": round(row["open"], 4),
            "high": round(row["high"], 4),
            "low": round(row["low"], 4),
            "close": round(row["close"], 4),
            "volume": row["volume"],
            "ma20": _safe(row.get("ma20")),
            "ma50": _safe(row.get("ma50")),
            "rsi": _safe(row.get("rsi")),
            "macd": _safe(row.get("macd")),
            "macd_signal": _safe(row.get("macd_signal")),
            "macd_hist": _safe(row.get("macd_hist")),
        })
    return data
