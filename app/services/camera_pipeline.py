"""
Per-camera processing pipeline.

Each camera runs in its own asyncio task:
  RTSP → YOLO → ByteTrack → Crop → OSNet → Qdrant → WS broadcast

Design:
- Heavy CPU work (detect, embed) runs in asyncio's default thread pool
  via run_in_executor to avoid blocking the event loop.
- The identity_service.resolve() is async; it is called directly in the
  async outer loop, not inside the executor.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import cv2
import numpy as np

from app.core.config import CameraConfig, get_pipeline_settings
from app.core.logging import get_logger
from app.core.models import BoundingBox, GlobalPerson, TrackedPerson
from app.detector.yolo_detector import YOLODetector
from app.reid.osnet_reid import OSNetReID
from app.services.identity_service import IdentityService
from app.tracker.bytetrack import ByteTracker
from app.websocket.manager import make_event, ws_manager

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.customer_counter import CustomerCounter


class CameraPipeline:
    """
    Manages the full processing loop for one camera.

    Responsibilities:
    - Open / reconnect RTSP stream.
    - Detect → track → embed → resolve ID → broadcast.
    - Report FPS and online/offline status.
    """

    def __init__(
        self,
        config: CameraConfig,
        detector: YOLODetector,
        reid: OSNetReID,
        identity: IdentityService,
        customer_counter: "CustomerCounter | None" = None,
    ) -> None:
        self._cfg = config
        self._detector = detector
        self._reid = reid
        self._identity = identity
        self._customer_counter = customer_counter
        self._logger = get_logger("pipeline", config.id)

        self._tracker = ByteTracker(camera_id=config.id)
        self._running = False
        self._task: asyncio.Task | None = None

        # Telemetry
        self.fps: float = 0.0
        self.online: bool = False
        self.detection_count: int = 0
        self._frame_number: int = 0

        # Latest annotated frame for MJPEG streaming
        self._latest_frame: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(
            self._run(), name=f"pipeline-{self._cfg.id}"
        )
        self._logger.info("Pipeline started for %s", self._cfg.name)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        self._logger.info("Pipeline stopped for %s", self._cfg.name)

    @property
    def camera_id(self) -> str:
        return self._cfg.id

    @property
    def latest_frame(self) -> np.ndarray | None:
        return self._latest_frame

    # ------------------------------------------------------------------
    # Main async loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        cfg = get_pipeline_settings()
        delay = cfg.reconnect_delay

        while self._running:
            cap = await asyncio.get_event_loop().run_in_executor(
                None, self._open_stream
            )
            if cap is None:
                self._logger.warning(
                    "Cannot open stream %s — retry in %ds", self._cfg.rtsp, delay
                )
                await self._set_offline()
                await asyncio.sleep(delay)
                continue

            self._logger.info("Stream opened: %s", self._cfg.rtsp)
            await self._set_online()

            fps_counter = 0
            fps_timer = time.time()

            try:
                while self._running:
                    # Read frame in thread pool (blocking I/O)
                    ret, frame = await asyncio.get_event_loop().run_in_executor(
                        None, cap.read
                    )
                    if not ret or frame is None:
                        self._logger.warning(
                            "Frame read failed on %s", self._cfg.id
                        )
                        break

                    self._frame_number += 1

                    # Frame skip — still update latest_frame for MJPEG
                    if self._frame_number % cfg.frame_skip != 0:
                        self._latest_frame = frame
                        await asyncio.sleep(0)
                        continue

                    # ── Detection + Tracking (CPU-bound → thread pool) ──────
                    dets, tracked = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self._detect_and_track,
                        frame,
                    )

                    # ── Per-person: embed + identity (async) ──────────────
                    annotated = frame.copy()
                    for person in tracked:
                        crop = self._crop(frame, person.bbox)
                        if crop is None:
                            continue

                        # Embedding in thread pool
                        embedding = await asyncio.get_event_loop().run_in_executor(
                            None, self._reid.extract, crop
                        )

                        # Identity resolution (async — touches Qdrant)
                        try:
                            gp = await self._identity.resolve(
                                embedding=embedding,
                                camera_id=self._cfg.id,
                                track_id=person.track_id,
                                bbox=person.bbox,
                                crop_bgr=crop,
                                camera_name=self._cfg.name,
                            )
                        except Exception as exc:
                            self._logger.error(
                                "Identity resolution error: %s", exc
                            )
                            continue

                        self.detection_count += 1

                        # Update customer counter (non-blocking)
                        if self._customer_counter is not None:
                            asyncio.ensure_future(
                                self._customer_counter.on_detection(
                                    gp.person_id,
                                    self._identity._qdrant,
                                )
                            )

                        # Annotate
                        self._draw_annotation(annotated, gp)

                        # Broadcast detection event
                        asyncio.ensure_future(
                            self._broadcast_detection(gp)
                        )

                    self._latest_frame = annotated

                    # FPS accounting
                    fps_counter += 1
                    elapsed = time.time() - fps_timer
                    if elapsed >= 1.0:
                        self.fps = fps_counter / elapsed
                        fps_counter = 0
                        fps_timer = time.time()

                    await asyncio.sleep(0)  # yield to event loop

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error(
                    "Pipeline error on %s: %s", self._cfg.id, exc, exc_info=True
                )
            finally:
                await asyncio.get_event_loop().run_in_executor(None, cap.release)
                await self._set_offline()
                if self._running:
                    await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Synchronous helpers (safe to run in thread pool)
    # ------------------------------------------------------------------

    def _open_stream(self) -> cv2.VideoCapture | None:
        """Open RTSP/video/webcam stream."""
        rtsp = self._cfg.rtsp
        cap = cv2.VideoCapture(rtsp)

        # Numeric string → webcam index
        if not cap.isOpened() and rtsp.isdigit():
            cap = cv2.VideoCapture(int(rtsp))

        if not cap.isOpened():
            return None

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _detect_and_track(
        self, frame: np.ndarray
    ) -> tuple[np.ndarray, list[TrackedPerson]]:
        """Run YOLO detection + ByteTrack. Returns (raw_dets, tracked_persons)."""
        dets = self._detector.detect_raw(frame)
        tracked = self._tracker.update(dets, self._frame_number, self._cfg.id)
        return dets, tracked

    @staticmethod
    def _crop(frame: np.ndarray, bbox: BoundingBox) -> np.ndarray | None:
        h, w = frame.shape[:2]
        x1 = max(0, bbox.x1)
        y1 = max(0, bbox.y1)
        x2 = min(w, bbox.x2)
        y2 = min(h, bbox.y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]

    @staticmethod
    def _draw_annotation(frame: np.ndarray, gp: GlobalPerson) -> None:
        bbox = gp.bbox
        color = (0, 255, 130) if not gp.is_new else (0, 180, 255)
        cv2.rectangle(frame, (bbox.x1, bbox.y1), (bbox.x2, bbox.y2), color, 2)
        lines = [
            gp.person_id,
            f"T:{gp.track_id}  S:{gp.similarity:.2f}",
        ]
        y = max(bbox.y1 - 36, 0)
        for line in lines:
            cv2.putText(
                frame, line, (bbox.x1, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2,
            )
            y += 17

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    async def _set_online(self) -> None:
        self.online = True
        await ws_manager.broadcast(
            make_event("camera_online", self._cfg.id, {"name": self._cfg.name})
        )

    async def _set_offline(self) -> None:
        self.online = False
        await ws_manager.broadcast(
            make_event("camera_offline", self._cfg.id, {"name": self._cfg.name})
        )

    async def _broadcast_detection(self, gp: GlobalPerson) -> None:
        event_type = "new_person" if gp.is_new else "new_detection"
        await ws_manager.broadcast(
            make_event(
                event_type,
                self._cfg.id,
                {
                    "person_id": gp.person_id,
                    "track_id": gp.track_id,
                    "similarity": round(gp.similarity, 3),
                    "bbox": gp.bbox.to_list(),
                    "snapshot": gp.snapshot_path,
                    "camera_name": self._cfg.name,
                },
            )
        )
