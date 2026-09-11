"""
Identity resolution service.

For each embedding:
1. Search Qdrant for similar persons.
2. If similarity ≥ threshold → reuse existing Person_ID.
3. Otherwise → mint a new Person_XXXXXX ID.
4. Store the embedding + payload in Qdrant.
5. Save a snapshot (with throttle logic).
6. Return GlobalPerson.

Snapshot throttle rules:
- New person  : capture the first `snapshot_initial_burst` frames (default 10),
                then once every `snapshot_interval_seconds` (default 60 s).
- Known person: capture once on first appearance (in this session),
                then once every `snapshot_interval_seconds`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.core.config import get_pipeline_settings
from app.core.logging import get_logger
from app.core.models import BoundingBox, GlobalPerson, QdrantPayload
from app.qdrant_client.qdrant_service import QdrantService
from app.services.snapshot_service import SnapshotService

logger = get_logger("services.identity")


@dataclass
class _CaptureState:
    """Tracks how many snapshots have been taken and when the last one was."""
    burst_count: int = 0          # how many burst frames captured so far
    burst_done: bool = False      # True once burst phase is complete
    last_snapshot_ts: float = 0.0 # epoch-seconds of the last saved snapshot
    minted_in_session: bool = False # Was this person newly created in this session?


class IdentityService:
    """
    Resolves a ReID embedding to a Global Person ID.
    Thread-safe (uses asyncio.Lock for ID counter).
    """

    def __init__(
        self,
        qdrant: QdrantService,
        snapshot_svc: SnapshotService,
    ) -> None:
        self._qdrant = qdrant
        self._snapshot = snapshot_svc
        self._lock = asyncio.Lock()
        self._person_counter: int | None = None   # lazy-loaded from Qdrant

        # Capture throttle state keyed by person_id
        self._capture_states: dict[str, _CaptureState] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def resolve(
        self,
        embedding: np.ndarray,
        camera_id: str,
        track_id: int,
        bbox: BoundingBox,
        crop_bgr: np.ndarray | None = None,
        camera_name: str = "",
    ) -> GlobalPerson:
        """
        Main entry point: returns a GlobalPerson with assigned ID.
        """
        cfg = get_pipeline_settings()
        emb_list = embedding.tolist()

        # Search for similar existing persons
        hits = self._qdrant.search_similar(
            embedding=emb_list,
            top_k=1,
            score_threshold=cfg.similarity_threshold,
        )

        if hits:
            # Re-use existing identity
            best = hits[0]
            person_id = best["person_id"]
            similarity = best["score"]
            is_new = False
            logger.debug(
                "Matched %s (sim=%.3f) on %s track=%d",
                person_id, similarity, camera_id, track_id,
            )
        else:
            # Mint a new ID
            async with self._lock:
                person_id = await self._next_person_id()
            similarity = 0.0
            is_new = True
            logger.info("New person %s detected on %s", person_id, camera_id)

        # ── Snapshot throttle logic ───────────────────────────────────────
        snapshot_path: str = ""
        if crop_bgr is not None and crop_bgr.size > 0:
            if self._should_capture(person_id, is_new, cfg):
                snapshot_path = self._snapshot.save(person_id, camera_id, crop_bgr)

        # Store in Qdrant
        payload = QdrantPayload(
            person_id=person_id,
            camera=camera_id,
            timestamp=datetime.utcnow().isoformat(),
            bbox=bbox.to_list(),
            snapshot=snapshot_path or None,
            track_id=track_id,
        )
        self._qdrant.upsert_embedding(emb_list, payload)

        return GlobalPerson(
            person_id=person_id,
            camera_id=camera_id,
            track_id=track_id,
            similarity=similarity,
            bbox=bbox,
            timestamp=datetime.utcnow(),
            snapshot_path=snapshot_path or None,
            is_new=is_new,
        )

    # ------------------------------------------------------------------
    # Snapshot throttle
    # ------------------------------------------------------------------

    def _should_capture(
        self,
        person_id: str,
        is_new: bool,
        cfg,
    ) -> bool:
        """
        Decide whether to save a snapshot for this detection event.

        Rules:
        - New person  : capture up to `snapshot_initial_burst` frames,
                        then every `snapshot_interval_seconds`.
        - Known person: capture once on first appearance (session),
                        then every `snapshot_interval_seconds`.
        """
        now = time.monotonic()
        state = self._capture_states.get(person_id)

        if state is None:
            # First time we ever see this person in this session
            state = _CaptureState()
            if is_new:
                state.minted_in_session = True
            else:
                state.minted_in_session = False
                state.burst_done = True  # skip burst for known persons
            self._capture_states[person_id] = state

        burst_limit = cfg.snapshot_initial_burst
        interval    = cfg.snapshot_interval_seconds

        if state.minted_in_session:
            # ── New / unregistered person ─────────────────────────────
            if not state.burst_done:
                # Still in burst phase
                state.burst_count += 1
                state.last_snapshot_ts = now
                if state.burst_count >= burst_limit:
                    state.burst_done = True
                    logger.debug(
                        "Burst complete for %s (%d frames captured)",
                        person_id, state.burst_count,
                    )
                return True
            else:
                # Burst done → throttle to interval
                if now - state.last_snapshot_ts >= interval:
                    state.last_snapshot_ts = now
                    return True
                return False
        else:
            # ── Known person ──────────────────────────────────────────
            if state.last_snapshot_ts == 0.0:
                # Very first appearance in this session → capture once
                state.last_snapshot_ts = now
                return True
            if now - state.last_snapshot_ts >= interval:
                state.last_snapshot_ts = now
                return True
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _next_person_id(self) -> str:
        """Return the next Person_XXXXXX string."""
        if self._person_counter is None:
            self._person_counter = self._qdrant.get_next_person_number()
        else:
            self._person_counter += 1
        return f"Person_{self._person_counter:06d}"
