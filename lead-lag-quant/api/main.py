"""FastAPI application entry point with lifespan-managed resources."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import pairs, trading, signals, analytics, backtest
from api.ws import ConnectionManager, router as ws_router
from ingestion_massive.polygon_client import PolygonClient
from utils.background_price_poller import BackgroundPricePoller
from utils.config import get_config as _get_config
from utils.db import get_connection, init_schema
from utils.logging import configure_logging, get_logger
from utils.pipeline_scheduler import PipelineScheduler

configure_logging()
log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = _get_config()
    conn = get_connection(config.db_path)
    init_schema(conn)

    client = PolygonClient(
        api_key=config.polygon_api_key,
        rate_limit_per_minute=config.rate_limit_per_minute,
    )

    ws_manager = ConnectionManager()

    scheduler = PipelineScheduler(conn, client, config)
    scheduler.start()

    price_poller = BackgroundPricePoller(conn, config.polygon_api_key)
    price_poller.start()

    app.state.conn = conn
    app.state.config = config
    app.state.client = client
    app.state.ws_manager = ws_manager
    app.state.scheduler = scheduler

    log.info(
        "fastapi_started",
        db_path=config.db_path,
        plan_tier=config.plan_tier.value,
    )

    yield

    conn.close()
    log.info("fastapi_shutdown")


app = FastAPI(title="Lead-Lag Quant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(pairs.router, prefix="/api")
app.include_router(trading.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
