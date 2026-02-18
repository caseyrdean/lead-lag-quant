"""Application configuration with Pydantic validation."""

import os
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class PlanTier(str, Enum):
    FREE = "free"
    PAID = "paid"


class AppConfig(BaseModel):
    polygon_api_key: str = Field(..., min_length=1)
    db_path: str = Field(default="data/market_data.db")
    plan_tier: PlanTier = Field(default=PlanTier.FREE)
    rate_limit_per_minute: int = Field(default=5)

    @field_validator("rate_limit_per_minute")
    @classmethod
    def validate_rate_limit(cls, v, info):
        if info.data.get("plan_tier") == PlanTier.FREE and v > 5:
            raise ValueError("Free tier limited to 5 requests/minute")
        return v


def get_config() -> AppConfig:
    """Load application config from environment variables.

    Reads:
        POLYGON_API_KEY (required)
        DB_PATH (default: data/market_data.db)
        PLAN_TIER (default: free)

    Raises:
        ValueError: If POLYGON_API_KEY is not set.
    """
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise ValueError(
            "POLYGON_API_KEY environment variable is required. "
            "Set it in your .env file or environment."
        )

    return AppConfig(
        polygon_api_key=api_key,
        db_path=os.environ.get("DB_PATH", "data/market_data.db"),
        plan_tier=os.environ.get("PLAN_TIER", "free"),
    )
