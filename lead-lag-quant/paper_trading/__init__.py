"""Paper trading simulation package.

Provides portfolio management, position tracking, trade execution,
and price polling for simulated paper trading against live market data.
"""

from paper_trading.db import init_paper_trading_schema
from paper_trading.engine import (
    SIZING_FRACTIONS,
    auto_execute_signals,
    close_position,
    compute_share_quantity,
    get_open_positions_display,
    get_portfolio_summary,
    get_trade_history_display,
    open_or_add_position,
    set_capital,
)
from paper_trading.price_poller import (
    fetch_snapshot_price,
    is_market_open,
    poll_and_update_prices,
)

__all__ = [
    "SIZING_FRACTIONS",
    "auto_execute_signals",
    "close_position",
    "compute_share_quantity",
    "fetch_snapshot_price",
    "get_open_positions_display",
    "get_portfolio_summary",
    "get_trade_history_display",
    "init_paper_trading_schema",
    "is_market_open",
    "open_or_add_position",
    "poll_and_update_prices",
    "set_capital",
]
