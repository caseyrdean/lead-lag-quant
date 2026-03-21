"""Signal query and execution endpoints."""

from fastapi import APIRouter

from api.deps import Conn, Config
from paper_trading.engine import auto_execute_signals

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(conn: Conn, days: int = 7):
    rows = conn.execute(
        """
        SELECT
            s.rowid AS signal_id,
            s.ticker_a AS leader,
            s.ticker_b AS follower,
            s.signal_date,
            s.direction,
            s.sizing_tier,
            s.stability_score,
            s.correlation_strength,
            s.expected_target,
            s.invalidation_threshold,
            s.data_warning,
            s.generated_at,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM paper_trades pt
                    WHERE pt.source_signal_id = s.rowid AND pt.side = 'buy'
                ) THEN 1 ELSE 0
            END AS executed
        FROM signals s
        INNER JOIN ticker_pairs tp
            ON tp.leader = s.ticker_a
            AND tp.follower = s.ticker_b
            AND tp.is_active = 1
        WHERE s.signal_date >= date('now', ? || ' days')
        ORDER BY s.generated_at DESC
        """,
        (f"-{days}",),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/execute")
def execute_signals(conn: Conn, config: Config):
    try:
        results = auto_execute_signals(conn, config.polygon_api_key)
        return {"executed": len(results), "trades": results}
    except ValueError as exc:
        return {"error": str(exc)}
