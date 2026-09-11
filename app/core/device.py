"""
Device detection: automatically selects CUDA if available, falls back to CPU.
"""

from __future__ import annotations

import torch
from app.core.logging import get_logger

logger = get_logger("core.device")


def get_device() -> torch.device:
    """Return best available torch device."""
    if torch.cuda.is_available():
        device = torch.device("cuda")
        logger.info(
            "CUDA device detected: %s (capability %s)",
            torch.cuda.get_device_name(0),
            torch.cuda.get_device_capability(0),
        )
    else:
        device = torch.device("cpu")
        logger.info("No CUDA detected — running on CPU")
    return device


_device: torch.device | None = None


def device() -> torch.device:
    """Cached device singleton."""
    global _device
    if _device is None:
        _device = get_device()
    return _device


def is_cuda_available() -> bool:
    return torch.cuda.is_available()
