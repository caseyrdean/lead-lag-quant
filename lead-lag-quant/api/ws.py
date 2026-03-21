"""WebSocket connection manager for real-time price, signal, and status broadcasts."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from utils.logging import get_logger

log = get_logger("api.ws")

router = APIRouter()


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts JSON messages."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        log.info("ws_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        log.info("ws_disconnected", total=len(self._connections))

    async def broadcast(self, event_type: str, data: dict) -> None:
        payload = json.dumps({"type": event_type, "data": data})
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)

    def broadcast_sync(self, event_type: str, data: dict) -> None:
        """Fire-and-forget broadcast from a sync (threaded) context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(self.broadcast(event_type, data), loop)
        except RuntimeError:
            pass


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    manager: ConnectionManager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
