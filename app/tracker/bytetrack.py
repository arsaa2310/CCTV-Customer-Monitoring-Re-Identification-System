"""
ByteTrack-based multi-object tracker.

Wraps the supervision ByteTrack implementation which ships with the
ultralytics/supervision package — no separate ByteTrack repo needed.

Each camera gets its own ByteTracker instance so tracks are independent.
"""

from __future__ import annotations

import numpy as np

from app.core.logging import get_logger
from app.core.models import BoundingBox, TrackedPerson

logger = get_logger("tracker.bytetrack")


class ByteTracker:
    """
    Wraps `supervision.ByteTrack` for person tracking within one camera.

    Args:
        camera_id:        Camera identifier string.
        max_age:          Frames before a lost track is deleted.
        min_hits:         Minimum detections before a track is confirmed.
    """

    def __init__(
        self,
        camera_id: str,
        max_age: int = 30,
        min_hits: int = 3,
    ) -> None:
        self._camera_id = camera_id
        self._max_age = max_age
        self._min_hits = min_hits
        self._frame_count = 0
        self._tracker = self._build_tracker()
        logger.info("ByteTracker initialised for camera %s", camera_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_tracker(self):  # type: ignore[return]
        """Build underlying tracker, preferring supervision then fallback."""
        try:
            import supervision as sv  # type: ignore
            return sv.ByteTrack(
                track_activation_threshold=0.25,
                lost_track_buffer=self._max_age,
                minimum_matching_threshold=0.8,
                frame_rate=30,
            )
        except Exception as exc:
            logger.warning("supervision ByteTrack unavailable (%s), using simple tracker", exc)
            return _SimpleTracker(max_age=self._max_age)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        detections_nx5: np.ndarray,
        frame_number: int,
        camera_id: str,
    ) -> list[TrackedPerson]:
        """
        Feed detections [x1,y1,x2,y2,conf] Nx5 and return active tracks.

        Returns list of TrackedPerson with stable track_ids.
        """
        self._frame_count = frame_number

        if detections_nx5.size == 0:
            return []

        try:
            import supervision as sv  # type: ignore

            sv_dets = sv.Detections(
                xyxy=detections_nx5[:, :4],
                confidence=detections_nx5[:, 4],
                class_id=np.zeros(len(detections_nx5), dtype=int),
            )
            tracked = self._tracker.update_with_detections(sv_dets)
            results: list[TrackedPerson] = []
            if tracked.tracker_id is None:
                return []
            for i, tid in enumerate(tracked.tracker_id):
                xyxy = tracked.xyxy[i].astype(int)
                conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.9
                results.append(
                    TrackedPerson(
                        track_id=int(tid),
                        bbox=BoundingBox(
                            x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3]
                        ),
                        confidence=conf,
                        camera_id=camera_id,
                        frame_number=frame_number,
                    )
                )
            return results

        except ImportError:
            return self._tracker.update(detections_nx5, frame_number, camera_id)

    def reset(self) -> None:
        self._tracker = self._build_tracker()
        self._frame_count = 0


# ---------------------------------------------------------------------------
# Minimal fallback tracker (IoU-based)
# ---------------------------------------------------------------------------

class _Track:
    _next_id = 1

    def __init__(self, bbox: np.ndarray, conf: float) -> None:
        self.id = _Track._next_id
        _Track._next_id += 1
        self.bbox = bbox
        self.conf = conf
        self.hits = 1
        self.age = 0
        self.confirmed = False


class _SimpleTracker:
    """IoU-based fallback — good enough for demo/CPU runs."""

    def __init__(self, max_age: int = 30) -> None:
        self._max_age = max_age
        self._tracks: list[_Track] = []

    def update(
        self,
        dets: np.ndarray,
        frame_number: int,
        camera_id: str,
    ) -> list[TrackedPerson]:
        # Age existing tracks
        for t in self._tracks:
            t.age += 1

        matched_track_ids: set[int] = set()
        results: list[TrackedPerson] = []

        for det in dets:
            bbox = det[:4]
            conf = float(det[4])
            best_iou, best_track = 0.0, None

            for t in self._tracks:
                iou = _iou(bbox, t.bbox)
                if iou > best_iou:
                    best_iou, best_track = iou, t

            if best_iou > 0.3 and best_track is not None:
                best_track.bbox = bbox
                best_track.conf = conf
                best_track.hits += 1
                best_track.age = 0
                if best_track.hits >= 3:
                    best_track.confirmed = True
                matched_track_ids.add(best_track.id)
                track = best_track
            else:
                track = _Track(bbox, conf)
                self._tracks.append(track)

            if track.confirmed or track.hits >= 2:
                b = track.bbox.astype(int)
                results.append(
                    TrackedPerson(
                        track_id=track.id,
                        bbox=BoundingBox(x1=b[0], y1=b[1], x2=b[2], y2=b[3]),
                        confidence=track.conf,
                        camera_id=camera_id,
                        frame_number=frame_number,
                    )
                )

        # Prune stale tracks
        self._tracks = [t for t in self._tracks if t.age <= self._max_age]
        return results


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1); ih = max(0, iy2 - iy1)
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return float(inter / union) if union > 0 else 0.0
