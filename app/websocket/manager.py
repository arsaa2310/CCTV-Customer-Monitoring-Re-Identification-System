"""
WebSocket Connection Manager.

Maintains the set of active WebSocket clients and broadcasts
structured events to all of them.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger
from app.core.models import WSEvent

logger = get_logger("websocket.manager")


class ConnectionManager:
    """Thread-safe WebSocket connection manager (asyncio-safe)."""

    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)
        logger.info("WS client connected (total=%d)", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._active:
            self._active.remove(ws)
        logger.info("WS client disconnected (total=%d)", len(self._active))

    async def broadcast(self, event: WSEvent) -> None:
        """Send event to all connected clients. Dead clients are silently removed."""
        if not self._active:
            return

        message = event.model_dump_json()
        dead: list[WebSocket] = []

        for ws in list(self._active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def broadcast_raw(self, data: dict[str, Any]) -> None:
        """Broadcast an arbitrary dict as JSON."""
        message = json.dumps(data, default=str)
        dead: list[WebSocket] = []

        for ws in list(self._active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self._active)


# Module-level singleton
ws_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------

def make_event(
    event_type: str,
    camera_id: str,
    payload: dict[str, Any],
) -> WSEvent:
    return WSEvent(
        event_type=event_type,
        camera_id=camera_id,
        timestamp=datetime.utcnow(),
        payload=payload,
    )
