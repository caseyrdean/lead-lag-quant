"""Tests for api/ws.py ConnectionManager broadcast_sync thread safety."""

import asyncio
from unittest.mock import MagicMock, patch

from api.ws import ConnectionManager


def test_broadcast_sync_uses_run_coroutine_threadsafe():
    """broadcast_sync must schedule via run_coroutine_threadsafe, not loop.create_task."""
    manager = ConnectionManager()
    mock_loop = MagicMock()

    with patch("api.ws.asyncio.get_running_loop", return_value=mock_loop), \
         patch("api.ws.asyncio.run_coroutine_threadsafe") as mock_rct:
        manager.broadcast_sync("price_update", {"ticker": "AAPL", "price": 150.0})

    mock_rct.assert_called_once()
    # Verify create_task was NOT used as the scheduling mechanism
    mock_loop.create_task.assert_not_called()


def test_broadcast_sync_handles_no_loop():
    """broadcast_sync must not raise when no event loop is running."""
    manager = ConnectionManager()

    with patch("api.ws.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        # Should not raise — RuntimeError is caught and passed
        manager.broadcast_sync("price_update", {"ticker": "AAPL", "price": 150.0})
