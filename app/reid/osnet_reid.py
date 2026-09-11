"""
Person Re-Identification using Torchreid OSNet x1.0.
Extracts 512-dimensional cosine-normalised embeddings.
No training — inference only with pretrained weights.
"""

from __future__ import annotations

import numpy as np
import torch
import torchvision.transforms as T
from PIL import Image

from app.core.config import settings
from app.core.device import device
from app.core.logging import get_logger

logger = get_logger("reid.osnet")

# Normalisation parameters from ImageNet / OSNet training
_MEAN = [0.485, 0.456, 0.406]
_STD  = [0.229, 0.224, 0.225]
_INPUT_SIZE = (256, 128)   # (H, W) expected by OSNet


class OSNetReID:
    """
    Wraps torchreid OSNet x1.0 for embedding extraction.

    The model is loaded once and shared. Each camera pipeline
    calls extract() with a cropped BGR numpy array.
    """

    def __init__(self, model_name: str = "osnet_x1_0") -> None:
        self._device = device()
        self._model_name = model_name
        self._model = self._load_model(model_name)
        self._transform = self._build_transform()
        logger.info("OSNet ReID model ready on %s", self._device)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load_model(self, model_name: str) -> torch.nn.Module:
        try:
            import torchreid  # type: ignore
            model = torchreid.models.build_model(
                name=model_name,
                num_classes=1000,   # pretrained on Market-1501 (751 IDs) or Duke
                pretrained=True,
            )
            model = model.to(self._device)
            model.eval()
            logger.info("Loaded torchreid %s (pretrained)", model_name)
            return model
        except Exception as exc:
            logger.warning("torchreid unavailable (%s) — using stub model", exc)
            return _StubReIDModel(self._device)

    def _build_transform(self) -> T.Compose:
        return T.Compose([
            T.Resize(_INPUT_SIZE),
            T.ToTensor(),
            T.Normalize(mean=_MEAN, std=_STD),
        ])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, crop_bgr: np.ndarray) -> np.ndarray:
        """
        Extract a single 512-d L2-normalised embedding from a BGR crop.

        Args:
            crop_bgr: HxWx3 numpy array (BGR, uint8)

        Returns:
            embedding: 1-D numpy array of shape (512,), float32
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return np.zeros(settings.embedding_dim, dtype=np.float32)

        # BGR → RGB → PIL
        rgb = crop_bgr[:, :, ::-1]
        pil = Image.fromarray(rgb.astype(np.uint8))

        tensor = self._transform(pil).unsqueeze(0).to(self._device)

        with torch.no_grad():
            feat = self._model(tensor)

        emb = feat.cpu().numpy().flatten().astype(np.float32)
        # L2-normalise for cosine similarity via dot product
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb

    def extract_batch(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        """
        Extract embeddings for a batch of BGR crops.
        More efficient than calling extract() in a loop.
        """
        if not crops:
            return []

        tensors = []
        for crop in crops:
            if crop is None or crop.size == 0:
                tensors.append(torch.zeros(3, *_INPUT_SIZE))
                continue
            rgb = crop[:, :, ::-1]
            pil = Image.fromarray(rgb.astype(np.uint8))
            tensors.append(self._transform(pil))

        batch = torch.stack(tensors).to(self._device)

        with torch.no_grad():
            feats = self._model(batch)

        embeddings = feats.cpu().numpy().astype(np.float32)

        results = []
        for emb in embeddings:
            norm = np.linalg.norm(emb)
            results.append(emb / norm if norm > 0 else emb)
        return results


# ---------------------------------------------------------------------------
# Stub for environments where torchreid is unavailable (e.g. pure CPU docker)
# ---------------------------------------------------------------------------

class _StubReIDModel(torch.nn.Module):
    """Random but deterministic embedding generator — for testing only."""

    def __init__(self, dev: torch.device) -> None:
        super().__init__()
        self._dev = dev
        # Fixed linear to be deterministic per instance
        self.fc = torch.nn.Linear(3 * 256 * 128, settings.embedding_dim)
        self.to(dev)
        logger.warning("Using STUB ReID model — embeddings are NOT meaningful!")

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # type: ignore[override]
        flat = x.view(x.size(0), -1)
        return self.fc(flat)
