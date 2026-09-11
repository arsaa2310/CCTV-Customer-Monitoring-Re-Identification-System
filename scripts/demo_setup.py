"""
Demo Camera Simulator.

For testing without real RTSP cameras, this script generates a
cameras.json that points to:
  - Webcam index 0 (if available), or
  - A synthetic test video generated with OpenCV.

Run BEFORE docker compose up to set up demo mode.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


CAMERAS_JSON = Path(__file__).parent / "config" / "cameras.json"


def build_demo_config(use_webcam: bool = False) -> dict:
    """Generate a demo cameras.json."""
    if use_webcam:
        streams = [
            {"id": "cam01", "name": "Webcam 0", "location": "Demo", "rtsp": "0"},
        ]
    else:
        # Use a short video file path (place test.mp4 in project root for demo)
        video = str(Path(__file__).parent / "test.mp4")
        streams = [
            {"id": "cam01", "name": "Test Video A", "location": "Demo", "rtsp": video},
            {"id": "cam02", "name": "Test Video B", "location": "Demo", "rtsp": video},
        ]

    return {
        "cameras": streams,
        "settings": {
            "similarity_threshold": 0.70,
            "detection_confidence": 0.45,
            "reid_batch_size": 4,
            "snapshot_interval": 30,
            "max_track_age": 30,
            "reconnect_delay": 3,
            "frame_skip": 3,
        },
    }


def main() -> None:
    use_webcam = "--webcam" in sys.argv

    cfg = build_demo_config(use_webcam)
    CAMERAS_JSON.parent.mkdir(exist_ok=True)

    with open(CAMERAS_JSON, "w") as f:
        json.dump(cfg, f, indent=4)

    print(f"Demo cameras.json written to {CAMERAS_JSON}")
    if not use_webcam:
        print("Tip: place a test.mp4 file in the project root for video-based demo.")
        print("     Or run with --webcam to use your webcam.")


if __name__ == "__main__":
    main()
