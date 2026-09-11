"""
YOLO11 Person Detector using Ultralytics.
Wraps inference and filters results to the 'person' class (COCO class 0).
"""

from __future__ import annotations

import numpy as np
from ultralytics import YOLO

from app.core.config import settings
from app.core.device import device
from app.core.logging import get_logger
from app.core.models import BoundingBox

logger = get_logger("detector.yolo")

# COCO class index for "person"
PERSON_CLASS_ID = 0


class YOLODetector:
    """
    Wraps Ultralytics YOLO11 for single-class person detection.

    Usage:
        detector = YOLODetector()
        boxes, confs = detector.detect(frame)
    """

    def __init__(
        self,
        model_name: str = settings.yolo_model,
        confidence: float = 0.5,
    ) -> None:
        self._confidence = confidence
        self._dev = device()
        logger.info("Loading YOLO model: %s on %s", model_name, self._dev)
        self._model = YOLO(model_name)
        self._model.to(str(self._dev))
        logger.info("YOLO model loaded")

    def detect(
        self, frame: np.ndarray
    ) -> tuple[list[BoundingBox], list[float]]:
        """
        Run person detection on a single BGR frame.

        Returns:
            bboxes:  list of BoundingBox (pixel coords)
            scores:  list of float confidence values
        """
        results = self._model.predict(
            source=frame,
            conf=self._confidence,
            classes=[PERSON_CLASS_ID],
            verbose=False,
            device=str(self._dev),
        )

        bboxes: list[BoundingBox] = []
        scores: list[float] = []

        if results and results[0].boxes is not None:
            for box in results[0].boxes:
                xyxy = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0].cpu().numpy())
                bboxes.append(
                    BoundingBox(
                        x1=int(xyxy[0]),
                        y1=int(xyxy[1]),
                        x2=int(xyxy[2]),
                        y2=int(xyxy[3]),
                    )
                )
                scores.append(conf)

        return bboxes, scores

    def detect_raw(self, frame: np.ndarray) -> np.ndarray:
        """
        Return detections as Nx5 numpy array [x1,y1,x2,y2,conf].
        Required by ByteTrack integration.
        """
        bboxes, scores = self.detect(frame)
        if not bboxes:
            return np.empty((0, 5), dtype=np.float32)

        rows = []
        for bbox, score in zip(bboxes, scores):
            rows.append([bbox.x1, bbox.y1, bbox.x2, bbox.y2, score])
        return np.array(rows, dtype=np.float32)

    def update_confidence(self, confidence: float) -> None:
        self._confidence = confidence
