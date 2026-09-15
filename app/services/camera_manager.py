"""
Camera Manager.

Loads cameras.json, starts a CameraPipeline per camera,
and hot-reloads when cameras.json is changed (via /api/cameras/reload).

Shared ML models are instantiated once and injected into each pipeline.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from app.core.config import CameraConfig, load_cameras_config
from app.core.logging import get_logger
from app.detector.yolo_detector import YOLODetector
from app.qdrant_client.qdrant_service import QdrantService
from app.reid.osnet_reid import OSNetReID
from app.services.camera_pipeline import CameraPipeline
from app.services.customer_counter import CustomerCounter
from app.services.identity_service import IdentityService
from app.services.snapshot_service import SnapshotService

logger = get_logger("services.camera_manager")


class CameraManager:
    """
    Manages lifecycle of all camera pipelines.

    Shared resources (detector, reid, identity) are created once
    to avoid redundant model loading.
    """

    def __init__(self) -> None:
        self._pipelines: dict[str, CameraPipeline] = {}
        self._start_time = time.time()

        # Shared ML infrastructure — created lazily on first startup
        self._detector: YOLODetector | None = None
        self._reid: OSNetReID | None = None
        self._identity: IdentityService | None = None
        self._qdrant: QdrantService | None = None
        self._snapshot: SnapshotService | None = None
        self._customer_counter: CustomerCounter | None = None
        self._cleanup_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Startup / Shutdown
    # ------------------------------------------------------------------

    def startup(self) -> None:
        """Called at FastAPI startup. Initialise models and launch pipelines."""
        logger.info("Camera manager starting up …")
        self._init_shared_services()
        self._sync_cameras()
        # Start customer counter background sweep
        if self._customer_counter:
            self._customer_counter.start_sweep()
        # Start ghost-person cleanup task
        try:
            loop = asyncio.get_event_loop()
            self._cleanup_task = loop.create_task(self._ghost_cleanup_loop())
        except RuntimeError:
            pass  # no event loop yet (tests etc.)

    def shutdown(self) -> None:
        """Called at FastAPI shutdown. Stop all pipelines."""
        logger.info("Camera manager shutting down …")
        for pid, pipeline in self._pipelines.items():
            pipeline.stop()
        self._pipelines.clear()
        if self._customer_counter:
            self._customer_counter.stop()
        if self._cleanup_task:
            self._cleanup_task.cancel()

    # ------------------------------------------------------------------
    # Hot reload
    # ------------------------------------------------------------------

    def reload(self) -> dict[str, Any]:
        """
        Re-read cameras.json and reconcile running pipelines.
        Starts new cameras and stops removed ones.
        """
        logger.info("Hot-reloading cameras.json …")
        result = self._sync_cameras()
        return result

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def pipelines(self) -> dict[str, CameraPipeline]:
        return self._pipelines

    def get_pipeline(self, camera_id: str) -> CameraPipeline | None:
        return self._pipelines.get(camera_id)

    def camera_statuses(self) -> list[dict[str, Any]]:
        try:
            cameras = load_cameras_config().cameras
        except Exception:
            cameras = []

        statuses = []
        for cam in cameras:
            p = self._pipelines.get(cam.id)
            statuses.append(
                {
                    "id": cam.id,
                    "name": cam.name,
                    "location": cam.location,
                    "rtsp": cam.rtsp,
                    "online": p.online if p else False,
                    "fps": round(p.fps, 1) if p else 0.0,
                    "detection_count": p.detection_count if p else 0,
                    "staff_boundary": cam.staff_boundary,
                }
            )
        return statuses

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_shared_services(self) -> None:
        """Initialise ML models and database clients (once)."""
        logger.info("Initialising shared services …")

        self._qdrant = QdrantService()
        self._snapshot = SnapshotService()
        self._detector = YOLODetector()
        self._reid = OSNetReID()
        self._identity = IdentityService(self._qdrant, self._snapshot)
        self._customer_counter = CustomerCounter()

        logger.info("Shared services ready")

    def _sync_cameras(self) -> dict[str, Any]:
        """Start new cameras, stop removed ones. Returns summary."""
        try:
            file_cfg = load_cameras_config()
        except Exception as exc:
            logger.error("Failed to load cameras.json: %s", exc)
            return {"error": str(exc)}

        desired_ids = {c.id for c in file_cfg.cameras}
        current_ids = set(self._pipelines.keys())

        started, stopped = [], []

        # Stop removed cameras
        for cam_id in current_ids - desired_ids:
            self._pipelines[cam_id].stop()
            del self._pipelines[cam_id]
            stopped.append(cam_id)
            logger.info("Stopped removed camera: %s", cam_id)

        # Start new cameras
        for cam_cfg in file_cfg.cameras:
            if cam_cfg.id not in self._pipelines:
                pipeline = self._build_pipeline(cam_cfg)
                pipeline.start()
                self._pipelines[cam_cfg.id] = pipeline
                started.append(cam_cfg.id)
                logger.info("Started camera: %s (%s)", cam_cfg.id, cam_cfg.name)

        return {
            "started": started,
            "stopped": stopped,
            "active": list(self._pipelines.keys()),
        }

    def _build_pipeline(self, cfg: CameraConfig) -> CameraPipeline:
        assert self._detector is not None, "detector not initialised"
        assert self._reid is not None, "reid not initialised"
        assert self._identity is not None, "identity not initialised"

        return CameraPipeline(
            config=cfg,
            detector=self._detector,
            reid=self._reid,
            identity=self._identity,
            customer_counter=self._customer_counter,
        )

    # ------------------------------------------------------------------
    # Qdrant / system access helpers (used by API routes)
    # ------------------------------------------------------------------

    @property
    def qdrant(self) -> QdrantService | None:
        return self._qdrant

    @property
    def customer_counter(self) -> CustomerCounter | None:
        return self._customer_counter

    # ------------------------------------------------------------------
    # Ghost-person cleanup (1-snapshot persons older than 5 minutes)
    # ------------------------------------------------------------------

    async def _ghost_cleanup_loop(self) -> None:
        """Background task: every 2 minutes, delete ghost persons."""
        await asyncio.sleep(60)  # wait 1 min before first run
        while True:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._cleanup_ghosts
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Ghost cleanup error: %s", exc)
            await asyncio.sleep(120)  # run every 2 minutes

    def _cleanup_ghosts(self) -> None:
        """Synchronous: find and delete ghost persons from Qdrant + snapshots."""
        if self._qdrant is None:
            return
        try:
            ghosts = self._qdrant.get_ghost_persons(
                min_age_minutes=5,
                low_snapshot_age_minutes=31,
                low_snapshot_threshold=15,
            )
        except Exception as exc:
            logger.warning("Could not get ghost persons: %s", exc)
            return

        if not ghosts:
            return

        logger.info("Ghost cleanup: found %d persons to delete", len(ghosts))
        for ghost in ghosts:
            pid = ghost["person_id"]
            reason = ghost.get("reason", "unknown")
            snap_count = ghost.get("snapshot_count", 0)
            snapshot_paths: list[str] = ghost.get("snapshot_paths", [])

            try:
                self._qdrant.delete_person(pid)
            except Exception as exc:
                logger.warning("Failed to delete ghost %s from Qdrant: %s", pid, exc)
                continue

            # Delete all snapshot files
            for snapshot in snapshot_paths:
                try:
                    path = Path(snapshot)
                    if not path.is_absolute():
                        path = Path("/app") / path
                    if path.exists():
                        path.unlink()
                        logger.debug("Deleted ghost snapshot: %s", path)
                except Exception as exc:
                    logger.warning("Could not delete snapshot %s: %s", snapshot, exc)

            logger.info(
                "Deleted person %s | reason=%s | snapshots=%d | last_seen=%s",
                pid, reason, snap_count, ghost.get("last_seen"),
            )

        # ── Rule 3: persons with ZERO snapshots (noise / false tracks) ──
        try:
            no_snap_ids = self._qdrant.get_persons_without_snapshot()
        except Exception as exc:
            logger.warning("Could not get zero-snapshot persons: %s", exc)
            no_snap_ids = []

        if no_snap_ids:
            logger.info("Zero-snapshot cleanup: deleting %d persons", len(no_snap_ids))
            for pid in no_snap_ids:
                try:
                    self._qdrant.delete_person(pid)
                    logger.info("Deleted zero-snapshot person: %s", pid)
                except Exception as exc:
                    logger.warning("Failed to delete %s: %s", pid, exc)

