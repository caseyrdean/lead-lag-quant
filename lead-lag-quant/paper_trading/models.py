"""Dataclass definitions for paper trading entities."""

from dataclasses import dataclass


@dataclass
class Portfolio:
    """Represents a paper trading portfolio with capital tracking."""

    portfolio_id: int
    starting_capital: float
    cash_balance: float
    created_at: str
    updated_at: str


@dataclass
class Position:
    """Represents an open paper trading position with average-cost basis."""

    position_id: int
    portfolio_id: int
    ticker: str
    shares: int
    avg_cost: float
    current_price: float | None
    last_price_at: str | None
    source_signal_id: int | None
    invalidation_threshold: float | None
    opened_at: str


@dataclass
class Trade:
    """Represents a completed paper trade (buy or sell)."""

    trade_id: int
    portfolio_id: int
    ticker: str
    side: str
    shares: int
    price: float
    realized_pnl: float | None
    source_signal_id: int | None
    executed_at: str
    notes: str | None
