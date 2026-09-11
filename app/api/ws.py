"""
WebSocket endpoint: /ws/events

Clients subscribe to receive real-time events:
  - new_person
  - new_detection
  - camera_online
  - camera_offline
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.websocket.manager import ws_manager

logger = get_logger("api.ws")

ws_router = APIRouter()


@ws_router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Handle a WebSocket client connection."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; we only push, not receive
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
        ws_manager.disconnect(websocket)
