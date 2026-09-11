"""
Core configuration module.
Loads and validates application settings from cameras.json and environment variables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/app/storage"))
CAMERAS_JSON = CONFIG_DIR / "cameras.json"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class CameraConfig(BaseModel):
    id: str
    name: str
    location: str
    rtsp: str


class PipelineSettings(BaseModel):
    similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    detection_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reid_batch_size: int = Field(default=16, ge=1)
    snapshot_interval: int = Field(default=30, ge=1)
    max_track_age: int = Field(default=30, ge=1)
    reconnect_delay: int = Field(default=5, ge=1)
    frame_skip: int = Field(default=10, ge=1)
    # Capture throttle settings
    snapshot_initial_burst: int = Field(default=10, ge=1)   # frames to capture for new person
    snapshot_interval_seconds: int = Field(default=60, ge=1) # interval (seconds) after burst


class CamerasFile(BaseModel):
    cameras: list[CameraConfig]
    settings: PipelineSettings = Field(default_factory=PipelineSettings)


# ---------------------------------------------------------------------------
# App-wide settings via env vars
# ---------------------------------------------------------------------------

class AppSettings(BaseSettings):
    app_name: str = "Multi-Camera Person Tracking"
    app_version: str = "1.0.0"
    debug: bool = False

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "person_embeddings"

    # Storage
    storage_dir: Path = STORAGE_DIR
    snapshots_dir: Path = STORAGE_DIR / "snapshots"

    # Model
    yolo_model: str = "yolov8n.pt"
    reid_model: str = "osnet_x1_0"
    embedding_dim: int = 512

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    class Config:
        env_prefix = "APP_"
        env_file = ".env"


settings = AppSettings()


# ---------------------------------------------------------------------------
# cameras.json loader
# ---------------------------------------------------------------------------

def load_cameras_config() -> CamerasFile:
    """Load and parse cameras.json."""
    if not CAMERAS_JSON.exists():
        raise FileNotFoundError(f"cameras.json not found at {CAMERAS_JSON}")
    with open(CAMERAS_JSON, "r") as f:
        data: dict[str, Any] = json.load(f)
    return CamerasFile(**data)


def get_camera_list() -> list[CameraConfig]:
    return load_cameras_config().cameras


def get_pipeline_settings() -> PipelineSettings:
    return load_cameras_config().settings
