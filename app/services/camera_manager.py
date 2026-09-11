"""
Camera Manager.

Loads cameras.json, starts a CameraPipeline per camera,
and hot-reloads when cameras.json is changed (via /api/cameras/reload).

Shared ML models are instantiated once and injected into each pipeline.
"""

from __future__ import annotations

import time
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

    def shutdown(self) -> None:
        """Called at FastAPI shutdown. Stop all pipelines."""
        logger.info("Camera manager shutting down …")
        for pid, pipeline in self._pipelines.items():
            pipeline.stop()
        self._pipelines.clear()
        if self._customer_counter:
            self._customer_counter.stop()

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
