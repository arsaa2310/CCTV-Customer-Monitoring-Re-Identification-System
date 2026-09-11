"""
Structured logging configuration.
Creates per-camera loggers with JSON-formatted output.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


def get_logger(name: str, camera_id: str | None = None) -> logging.Logger:
    """
    Return a structured logger.
    If camera_id is provided, all log records include it automatically.
    """
    logger_name = f"{name}.{camera_id}" if camera_id else name
    logger = logging.getLogger(logger_name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger


def setup_root_logging(level: int = logging.INFO) -> None:
    """Configure root-level logging once at startup."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
    # Silence noisy libraries
    for lib in ("urllib3", "httpx", "httpcore", "PIL", "ultralytics"):
        logging.getLogger(lib).setLevel(logging.WARNING)
