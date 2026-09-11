"""
Qdrant vector-database client.

Responsibilities:
- Create / ensure the person_embeddings collection exists.
- Upsert new embeddings with full payload.
- Search for similar embeddings (cosine similarity).
- Query persons, history, etc.
- Auto-reconnect on stale HTTP keep-alive connections.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import settings
from app.core.logging import get_logger
from app.core.models import QdrantPayload

logger = get_logger("qdrant.service")

COLLECTION = settings.qdrant_collection
DIM = settings.embedding_dim


class QdrantService:
    """
    Thin, testable wrapper around the Qdrant Python client.
    Uses cosine distance (unit-length vectors → similarity = dot product).
    Auto-reconnects when the HTTP keep-alive connection goes stale.
    """

    def __init__(self) -> None:
        self._host = settings.qdrant_host
        self._port = settings.qdrant_port
        self._client: QdrantClient = self._make_client()
        self._ensure_collection()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _make_client(self) -> QdrantClient:
        """Create a fresh QdrantClient."""
        return QdrantClient(
            host=self._host,
            port=self._port,
            timeout=30,
        )

    def _reconnect(self) -> None:
        """Discard the stale client and open a fresh connection."""
        logger.warning("Qdrant connection lost — reconnecting …")
        try:
            self._client.close()
        except Exception:
            pass
        self._client = self._make_client()

    def _call(self, method_name: str, *args, **kwargs):
        """
        Execute a Qdrant operation with automatic reconnect on failure.
        Creates a fresh client if the shared one is stale.
        """
        _STALE = ("disconnected", "connection", "reset", "eof", "closed", "send a request", "refused")
        try:
            return getattr(self._client, method_name)(*args, **kwargs)
        except Exception as exc:
            if any(k in str(exc).lower() for k in _STALE):
                logger.warning("Qdrant connection error (%s) — reconnecting…", exc)
                self._reconnect()
                # Use a separate one-shot client for the retry to avoid any shared state
                fresh = self._make_client()
                try:
                    return getattr(fresh, method_name)(*args, **kwargs)
                finally:
                    try:
                        fresh.close()
                    except Exception:
                        pass
            raise

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def _ensure_collection(self) -> None:
        """Create collection if it does not exist."""
        existing = [c.name for c in self._call("get_collections").collections]
        if COLLECTION not in existing:
            self._call(
                "create_collection",
                collection_name=COLLECTION,
                vectors_config=qmodels.VectorParams(
                    size=DIM,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s (dim=%d)", COLLECTION, DIM)
        else:
            logger.info("Qdrant collection already exists: %s", COLLECTION)

    def health(self) -> bool:
        try:
            self._call("get_collections")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_embedding(
        self,
        embedding: list[float],
        payload: QdrantPayload,
    ) -> str:
        """Insert a new embedding point. Returns the assigned UUID."""
        point_id = str(uuid.uuid4())
        self._call(
            "upsert",
            collection_name=COLLECTION,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload.model_dump(),
                )
            ],
        )
        return point_id

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_similar(
        self,
        embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Return top-k similar embeddings with their payloads and scores."""
        results = self._call(
            "search",
            collection_name=COLLECTION,
            query_vector=embedding,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        out = []
        for r in results:
            entry = dict(r.payload or {})
            entry["score"] = r.score
            entry["point_id"] = str(r.id)
            out.append(entry)
        return out

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_all_persons(self, limit: int = 10000) -> list[dict[str, Any]]:
        """Return unique person records from the collection."""
        results, _ = self._call(
            "scroll",
            collection_name=COLLECTION,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        # Deduplicate by person_id — keep latest timestamp but preserve metadata
        persons: dict[str, dict[str, Any]] = {}
        for r in results:
            payload = dict(r.payload or {})
            pid = payload.get("person_id", "")
            if not pid:
                continue

            if pid not in persons:
                persons[pid] = payload
            else:
                existing = persons[pid]
                is_newer = payload.get("timestamp", "") > existing.get("timestamp", "")
                
                # We need to preserve snapshot, person_name, and person_label if they exist
                # in ANY point, because newer points might not have them (due to snapshot throttling
                # or metadata not being duplicated to every new detection).
                best_snapshot = payload.get("snapshot") or existing.get("snapshot")
                best_label = payload.get("person_label") or existing.get("person_label")
                best_name = payload.get("person_name") or existing.get("person_name")
                
                if is_newer:
                    # Update to the newer payload as base
                    new_payload = dict(payload)
                    new_payload["snapshot"] = best_snapshot
                    new_payload["person_label"] = best_label
                    new_payload["person_name"] = best_name
                    persons[pid] = new_payload
                else:
                    # Keep existing as base but update with any found metadata
                    existing["snapshot"] = best_snapshot
                    existing["person_label"] = best_label
                    existing["person_name"] = best_name

        return list(persons.values())

    def get_person_history(self, person_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return all events for a specific person, newest first."""
        results, _ = self._call(
            "scroll",
            collection_name=COLLECTION,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="person_id",
                        match=qmodels.MatchValue(value=person_id),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        events = [dict(r.payload or {}) for r in results]
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events

    def get_history(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return the most recent detection events across all persons."""
        results, _ = self._call(
            "scroll",
            collection_name=COLLECTION,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        events = [dict(r.payload or {}) for r in results]
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events

    def count_persons(self) -> int:
        """Count unique person IDs in the collection."""
        return len(self.get_all_persons())

    def get_next_person_number(self) -> int:
        """Return next integer for a new Person_XXXXXX ID."""
        all_persons = self.get_all_persons()
        if not all_persons:
            return 1
        numbers = []
        for p in all_persons:
            pid = p.get("person_id", "")
            if pid.startswith("Person_"):
                try:
                    numbers.append(int(pid.split("_")[1]))
                except (IndexError, ValueError):
                    pass
        return max(numbers, default=0) + 1

    def get_embedding_by_person(self, person_id: str) -> Optional[list[float]]:
        """Retrieve the most recent embedding for a given person_id."""
        results, _ = self._call(
            "scroll",
            collection_name=COLLECTION,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="person_id",
                        match=qmodels.MatchValue(value=person_id),
                    )
                ]
            ),
            limit=1,
            with_payload=False,
            with_vectors=True,
        )
        if results:
            return results[0].vector  # type: ignore[return-value]
        return None

    def get_person_metadata(self, person_id: str) -> dict[str, Any]:
        """
        Get person metadata (name, label) from the most up-to-date record.

        Fetches ALL points for this person and picks:
        1. The record with a non-empty `person_label` (i.e. one that has been
           manually updated), preferring the latest timestamp among those.
        2. If none has a label, fall back to the record with the latest timestamp.

        This ensures that after update_person_metadata() is called, the new
        label is reflected immediately even though older points exist without it.
        """
        results, _ = self._call(
            "scroll",
            collection_name=COLLECTION,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="person_id",
                        match=qmodels.MatchValue(value=person_id),
                    )
                ]
            ),
            limit=10000,
            with_payload=True,
            with_vectors=False,
        )
        if not results:
            return {"person_id": person_id, "name": None, "label": None}

        payloads = [dict(r.payload or {}) for r in results]

        # Prefer records that have an explicitly set label/name
        labelled = [p for p in payloads if p.get("person_label") or p.get("person_name")]
        candidates = labelled if labelled else payloads

        # Among candidates, pick the one with the newest timestamp
        best = max(candidates, key=lambda p: p.get("timestamp", ""), default=candidates[0])
        return {
            "person_id": person_id,
            "name": best.get("person_name"),
            "label": best.get("person_label"),
        }

    def update_person_metadata(
        self,
        person_id: str,
        name: str | None = None,
        label: str | None = None,
    ) -> None:
        """Update name/label for all embeddings of a person in one batch call."""
        results, _ = self._call(
            "scroll",
            collection_name=COLLECTION,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="person_id",
                        match=qmodels.MatchValue(value=person_id),
                    )
                ]
            ),
            limit=10000,
            with_payload=False,
            with_vectors=False,
        )
        update_payload: dict[str, Any] = {}
        if name is not None:
            update_payload["person_name"] = name
        if label is not None:
            update_payload["person_label"] = label

        if update_payload:
            point_ids = [r.id for r in results]
            if point_ids:
                self._call(
                    "set_payload",
                    collection_name=COLLECTION,
                    payload=update_payload,
                    points=point_ids,
                )
        logger.info(f"Updated metadata for person {person_id}: name={name}, label={label}")

    def delete_person(self, person_id: str) -> None:
        """Delete all embeddings for a person."""
        self._call(
            "delete",
            collection_name=COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="person_id",
                            match=qmodels.MatchValue(value=person_id),
                        )
                    ]
                )
            ),
        )
        logger.info(f"Deleted all embeddings for person {person_id}")
