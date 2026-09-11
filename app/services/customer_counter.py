"""
Customer Counter Service.

Tracks active (non-staff) customers in memory.

Rules:
- Person with label == "staff" → ignored.
- Everyone else (no label or any other label) → counted as customer.
- If a customer hasn't been seen for TIMEOUT_HOURS, they are removed automatically.
- Broadcasts "customer_count_update" via WebSocket on every change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.qdrant_client.qdrant_service import QdrantService

logger = get_logger("services.customer_counter")

TIMEOUT_HOURS: float = 3.0        # hours of inactivity before removal
SWEEP_INTERVAL_SECONDS: int = 300  # how often to run the cleanup sweep (5 min)


class CustomerCounter:
    """
    In-memory store of active customer person_ids and their last-seen timestamp.
    Thread/async-safe via asyncio.Lock.
    """

    def __init__(self) -> None:
        # person_id → last_seen datetime
        self._active: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._prev_count: int = -1   # detect changes for WS broadcast
        self._sweep_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_sweep(self) -> None:
        """Start background cleanup task. Call once after event loop is running."""
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(
                self._sweep_loop(), name="customer-counter-sweep"
            )
            logger.info("Customer counter sweep task started (interval=%ds)", SWEEP_INTERVAL_SECONDS)

    def stop(self) -> None:
        if self._sweep_task:
            self._sweep_task.cancel()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._active)

    @property
    def customer_ids(self) -> list[str]:
        return list(self._active.keys())

    async def on_detection(self, person_id: str, qdrant: "QdrantService") -> None:
        """
        Called every time a person is detected by the camera pipeline.
        Fetches label from Qdrant, then updates the counter accordingly.
        Broadcasts via WebSocket if count changed.
        """
        # Fetch label in executor (blocking Qdrant call)
        loop = asyncio.get_event_loop()
        meta = await loop.run_in_executor(
            None, lambda: qdrant.get_person_metadata(person_id)
        )
        label = (meta.get("label") or "").strip().lower()
        is_staff = label == "staff"

        changed = False
        async with self._lock:
            if is_staff:
                # Remove from customers if previously counted
                if person_id in self._active:
                    del self._active[person_id]
                    changed = True
                    logger.info("Removed staff from customer count: %s", person_id)
            else:
                # Add or update last-seen
                is_new = person_id not in self._active
                self._active[person_id] = datetime.utcnow()
                if is_new:
                    changed = True
                    logger.info("New customer detected: %s (total=%d)", person_id, len(self._active))

        if changed:
            await self._broadcast()

    async def remove_customer(self, person_id: str) -> None:
        """Manually remove a customer (e.g. when person is deleted from DB)."""
        async with self._lock:
            if person_id in self._active:
                del self._active[person_id]
        await self._broadcast()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _sweep_loop(self) -> None:
        """Periodically remove customers not seen for TIMEOUT_HOURS."""
        while True:
            try:
                await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
                await self._sweep_inactive()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Sweep error: %s", exc)

    async def _sweep_inactive(self) -> None:
        cutoff = datetime.utcnow() - timedelta(hours=TIMEOUT_HOURS)
        removed = []
        async with self._lock:
            for pid, last_seen in list(self._active.items()):
                if last_seen < cutoff:
                    del self._active[pid]
                    removed.append(pid)
        if removed:
            logger.info(
                "Swept %d inactive customer(s) (timeout=%dh): %s",
                len(removed), int(TIMEOUT_HOURS), removed,
            )
            await self._broadcast()

    async def _broadcast(self) -> None:
        """Broadcast customer_count_update event if count changed."""
        from app.websocket.manager import ws_manager  # avoid circular import
        count = len(self._active)
        if count == self._prev_count:
            return
        self._prev_count = count
        await ws_manager.broadcast_raw({
            "event_type": "customer_count_update",
            "camera_id": "system",
            "timestamp": datetime.utcnow().isoformat(),
            "payload": {
                "count": count,
                "customer_ids": list(self._active.keys()),
            },
        })
        logger.info("Customer count updated → %d", count)
