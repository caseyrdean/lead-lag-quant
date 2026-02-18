"""Pydantic models for Polygon.io API response validation."""

from pydantic import BaseModel, ConfigDict, field_validator


class TickerPair(BaseModel):
    """A pair of tickers representing a leader-follower relationship."""

    model_config = ConfigDict(extra="ignore")

    leader: str
    follower: str

    @field_validator("leader", "follower")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper()
        if not v.isalpha() or len(v) < 1 or len(v) > 10:
            raise ValueError(
                f"Ticker must be 1-10 uppercase letters, got '{v}'"
            )
        return v

    @field_validator("follower")
    @classmethod
    def follower_must_differ(cls, v: str, info) -> str:
        leader = info.data.get("leader")
        if leader and v.upper() == leader.upper():
            raise ValueError("Follower must differ from leader")
        return v


class AggBar(BaseModel):
    """A single aggregate bar from the Polygon.io /v2/aggs endpoint."""

    model_config = ConfigDict(extra="ignore")

    t: int
    o: float
    h: float
    l: float
    c: float
    v: float
    vw: float | None = None
    n: int | None = None
    otc: bool | None = None


class SplitRecord(BaseModel):
    """A stock split record from Polygon.io /v3/reference/splits."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    ticker: str
    execution_date: str
    split_from: float
    split_to: float


class DividendRecord(BaseModel):
    """A dividend record from Polygon.io /v3/reference/dividends."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    ticker: str
    cash_amount: float
    ex_dividend_date: str
    pay_date: str | None = None
    declaration_date: str | None = None
    record_date: str | None = None
    frequency: int | None = None
