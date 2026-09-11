"""
MJPEG live stream endpoints and snapshot static file serving.

GET /stream/{camera_id}   → MJPEG stream for that camera
GET /snapshots/{path}     → serve saved snapshot images
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("api.stream")
stream_router = APIRouter()


# ---------------------------------------------------------------------------
# MJPEG stream
# ---------------------------------------------------------------------------

async def _generate_mjpeg(camera_id: str, request: Request):  # type: ignore[return]
    """Async generator that yields MJPEG frames."""
    manager = request.app.state.manager
    pipeline = manager.get_pipeline(camera_id)

    if pipeline is None:
        return

    while True:
        if await request.is_disconnected():
            break

        frame = pipeline.latest_frame
        if frame is None:
            await asyncio.sleep(0.05)
            continue

        # Overlay FPS
        overlay = frame.copy()
        cv2.putText(
            overlay,
            f"FPS: {pipeline.fps:.1f}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )

        _, buf = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 75])
        frame_bytes = buf.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )

        await asyncio.sleep(1 / 25)  # ~25 fps cap for web


@stream_router.get("/stream/{camera_id}")
async def live_stream(camera_id: str, request: Request) -> StreamingResponse:
    """MJPEG live stream for a single camera."""
    manager = request.app.state.manager
    if manager.get_pipeline(camera_id) is None:
        raise HTTPException(404, f"Camera {camera_id} not found")

    return StreamingResponse(
        _generate_mjpeg(camera_id, request),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Snapshot static serving
# ---------------------------------------------------------------------------

@stream_router.get("/snapshots/{person_id}/{filename}")
async def get_snapshot(person_id: str, filename: str) -> FileResponse:
    """Serve a saved snapshot image."""
    path = settings.snapshots_dir / person_id / filename
    if not path.exists():
        raise HTTPException(404, "Snapshot not found")
    return FileResponse(str(path))
