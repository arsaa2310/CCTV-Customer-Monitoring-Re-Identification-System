"""
Snapshot storage service.
Saves cropped person images to: storage/snapshots/Person_XXXXXX/cam_NNN.jpg
"""

from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("services.snapshot")


class SnapshotService:
    """Manages saving and retrieving person snapshot images."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or settings.snapshots_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        person_id: str,
        camera_id: str,
        crop: np.ndarray,
    ) -> str:
        """
        Save a cropped person image.

        Returns:
            Relative path string, e.g. "snapshots/Person_000001/cam01_001.jpg"
        """
        person_dir = self._base / person_id
        person_dir.mkdir(parents=True, exist_ok=True)

        # Count existing files to generate sequence number
        existing = list(person_dir.glob(f"{camera_id}_*.jpg"))
        seq = len(existing) + 1
        filename = f"{camera_id}_{seq:03d}.jpg"
        filepath = person_dir / filename

        if crop is not None and crop.size > 0:
            cv2.imwrite(str(filepath), crop)
        else:
            logger.warning("Empty crop for %s — skipping snapshot", person_id)
            return ""

        rel_path = f"snapshots/{person_id}/{filename}"
        logger.debug("Saved snapshot %s", rel_path)
        return rel_path

    def list_snapshots(self, person_id: str) -> list[str]:
        """Return relative paths for all snapshots of a person."""
        person_dir = self._base / person_id
        if not person_dir.exists():
            return []
        return [
            f"snapshots/{person_id}/{p.name}"
            for p in sorted(person_dir.glob("*.jpg"))
        ]

    def get_absolute(self, rel_path: str) -> Path:
        """Convert a relative snapshot path to an absolute Path."""
        return settings.storage_dir / rel_path


# Module-level singleton
snapshot_service = SnapshotService()
