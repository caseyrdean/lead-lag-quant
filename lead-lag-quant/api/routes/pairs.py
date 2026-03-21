"""Ticker pair CRUD endpoints."""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from api.automation import auto_pipeline_for_pair
from api.deps import Conn, Client, Config
from utils.config import PlanTier
from utils.logging import get_logger

log = get_logger("api.routes.pairs")

router = APIRouter(prefix="/pairs", tags=["pairs"])

FREE_TIER_MAX_PAIRS = 5  # BUGFIX-01: enforced server-side to match Gradio UI cap


class AddPairsRequest(BaseModel):
    leader: str
    followers: list[str]


class DeletePairsRequest(BaseModel):
    ids: list[int]


@router.get("")
def list_pairs(conn: Conn):
    rows = conn.execute(
        "SELECT id, leader, follower, created_at "
        "FROM ticker_pairs WHERE is_active = 1 ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("")
def add_pairs(
    body: AddPairsRequest,
    conn: Conn,
    client: Client,
    config: Config,
    request: Request,
    bg: BackgroundTasks,
):
    leader = body.leader.strip().upper()
    followers = [f.strip().upper() for f in body.followers if f.strip()]

    if not leader:
        return {"error": "Leader ticker is required"}
    if not followers:
        return {"error": "At least one follower is required"}

    # BUGFIX-01: enforce FREE-tier pair limit server-side before any INSERT
    if config.plan_tier == PlanTier.FREE:
        active = conn.execute(
            "SELECT COUNT(*) FROM ticker_pairs WHERE is_active = 1"
        ).fetchone()[0]
        if active >= FREE_TIER_MAX_PAIRS:
            raise HTTPException(
                status_code=403,
                detail=f"Free tier is limited to {FREE_TIER_MAX_PAIRS} active pairs.",
            )

    if client.get_ticker_details(leader) is None:
        return {"error": f"Invalid leader: {leader}"}

    results: list[dict] = []
    added = 0
    for follower in followers:
        if follower == leader:
            results.append({"ticker": follower, "status": "skipped", "reason": "same as leader"})
            continue
        if client.get_ticker_details(follower) is None:
            results.append({"ticker": follower, "status": "failed", "reason": "not found on Polygon"})
            continue
        try:
            conn.execute(
                "INSERT INTO ticker_pairs (leader, follower) VALUES (?, ?)",
                (leader, follower),
            )
            conn.commit()
            results.append({"ticker": follower, "status": "added"})
            added += 1
        except sqlite3.IntegrityError:
            now_utc = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "UPDATE ticker_pairs SET is_active = 1, reactivated_at = ? "
                "WHERE leader = ? AND follower = ? AND is_active = 0",
                (now_utc, leader, follower),
            )
            conn.commit()
            if cursor.rowcount > 0:
                results.append({"ticker": follower, "status": "reactivated"})
                added += 1
            else:
                results.append({"ticker": follower, "status": "skipped", "reason": "already active"})

    if added > 0:
        ws_manager = request.app.state.ws_manager
        bg.add_task(
            auto_pipeline_for_pair,
            conn, client, config.polygon_api_key, ws_manager,
        )

    return {"leader": leader, "added": added, "results": results}


@router.get("/correlation")
def pair_correlation(conn: Conn, leader: str, followers: str, days: int = 180):
    """Return indexed price series (base=100) for leader and follower tickers."""
    from paper_trading.market_data import get_price_history
    import pandas as pd

    follower_list = [f.strip().upper() for f in followers.split(",") if f.strip()]
    tickers = [leader.strip().upper()] + follower_list

    raw: dict[str, pd.Series] = {}
    for ticker in tickers:
        df = get_price_history(conn, ticker, days=days)
        if not df.empty:
            raw[ticker] = df.set_index("trading_day")["close"]

    if not raw:
        return []

    combined = pd.DataFrame(raw).dropna(how="all")
    if combined.empty or len(combined) < 2:
        return []

    for col in combined.columns:
        first_idx = combined[col].first_valid_index()
        if first_idx is not None:
            base = combined[col][first_idx]
            if base and base != 0:
                combined[col] = combined[col] / base * 100

    records = []
    for idx, row in combined.iterrows():
        entry: dict = {"date": str(idx)[:10]}
        for col in combined.columns:
            val = row[col]
            entry[col] = round(val, 2) if pd.notna(val) else None
        records.append(entry)
    return records


@router.delete("")
def delete_pairs(body: DeletePairsRequest, conn: Conn):
    removed = 0
    for pair_id in body.ids:
        cursor = conn.execute(
            "UPDATE ticker_pairs SET is_active = 0 WHERE id = ? AND is_active = 1",
            (pair_id,),
        )
        removed += cursor.rowcount
    conn.commit()  # BUGFIX-02: commit is present (verified 2026-03-21)
    return {"removed": removed}
