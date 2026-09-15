"""
Shared Pydantic v2 data models for the tracking system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Detection & Tracking
# ---------------------------------------------------------------------------

class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def to_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]


class TrackedPerson(BaseModel):
    """A single person detection with track ID within one camera frame."""
    track_id: int
    bbox: BoundingBox
    confidence: float
    camera_id: str
    frame_number: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Person ReID
# ---------------------------------------------------------------------------

class PersonEmbedding(BaseModel):
    """ReID embedding result for a tracked person."""
    track_id: int
    camera_id: str
    embedding: list[float]          # 512-dim OSNet vector
    bbox: BoundingBox
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    snapshot_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Global Identity
# ---------------------------------------------------------------------------

class GlobalPerson(BaseModel):
    """A person identity resolved across cameras."""
    person_id: str                  # e.g. "Person_000001"
    camera_id: str
    track_id: int
    similarity: float
    bbox: BoundingBox
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    snapshot_path: Optional[str] = None
    label: Optional[str] = None
    is_new: bool = False            # True when this is a brand-new identity


# ---------------------------------------------------------------------------
# Qdrant Payload
# ---------------------------------------------------------------------------

class QdrantPayload(BaseModel):
    person_id: str
    camera: str
    timestamp: str
    bbox: list[int]
    snapshot: Optional[str] = None
    track_id: int


# ---------------------------------------------------------------------------
# History / Timeline
# ---------------------------------------------------------------------------

class HistoryEvent(BaseModel):
    person_id: str
    camera_id: str
    camera_name: str
    timestamp: datetime
    snapshot_path: Optional[str] = None
    bbox: list[int]


class PersonRecord(BaseModel):
    person_id: str
    first_seen: datetime
    last_seen: datetime
    cameras_seen: list[str]
    snapshot_paths: list[str]
    total_detections: int


# ---------------------------------------------------------------------------
# WebSocket events
# ---------------------------------------------------------------------------

class WSEvent(BaseModel):
    event_type: str          # new_person | new_detection | camera_offline | camera_online
    camera_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: dict            # arbitrary per-event data


# ---------------------------------------------------------------------------
# API response helpers
# ---------------------------------------------------------------------------

class CameraStatus(BaseModel):
    id: str
    name: str
    location: str
    rtsp: str
    online: bool
    fps: float = 0.0
    detection_count: int = 0


class SystemStatus(BaseModel):
    uptime_seconds: float
    total_persons: int
    active_cameras: int
    total_cameras: int
    gpu_available: bool
    qdrant_status: str
