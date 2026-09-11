"""
REST API routes for the Multi-Camera Person Tracking system.

Endpoints:
  GET  /api/cameras
  POST /api/cameras/add
  DELETE /api/cameras/{camera_id}
  POST /api/cameras/reload
  GET  /api/persons
  GET  /api/person/{id}
  PUT  /api/person/{id}
  DELETE /api/person/{id}
  GET  /api/history
  POST /api/search/image
  GET  /api/system
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

from app.core.logging import get_logger
from app.services.camera_manager import CameraManager

logger = get_logger("api.routes")

# Request models for type safety
class AddCameraRequest(BaseModel):
    source: str  # USB device ID or RTSP URL
    name: str
    
class UpdatePersonRequest(BaseModel):
    name: str | None = None
    label: str | None = None

router = APIRouter(prefix="/api")

# Dependency injected from app state
def get_manager(request: Request) -> CameraManager:
    return request.app.state.manager


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

@router.get("/cameras")
async def list_cameras(request: Request) -> list[dict[str, Any]]:
    """Return status of all configured cameras."""
    manager: CameraManager = get_manager(request)
    return manager.camera_statuses()


@router.post("/cameras/add")
async def add_camera(request: Request, body: AddCameraRequest) -> dict[str, Any]:
    """Add a new camera (USB or RTSP) and reload config."""
    try:
        # Read current config
        config_path = Path("config/ipcam_config.json")
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
        else:
            config = {"sources": [], "camera_names": []}
        
        # Append new source
        config["sources"].append(body.source)
        config["camera_names"].append(body.name)
        
        # Write back
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        
        # Regenerate mediamtx config
        import subprocess
        result = subprocess.run(
            ["python3", "scripts/generate_mediamtx_config.py"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            raise Exception(f"Config generation failed: {result.stderr}")
        
        # Reload in app
        manager: CameraManager = get_manager(request)
        manager.reload()
        
        # Identify new camera ID
        cam_count = len(config["sources"])
        camera_id = f"cam{cam_count:02d}"
        
        logger.info(f"Camera added: {camera_id} ({body.name})")
        return {
            "status": "success",
            "camera_id": camera_id,
            "name": body.name,
            "message": "Camera added successfully. Restart containers to apply."
        }
    except Exception as exc:
        logger.exception("Failed to add camera")
        raise HTTPException(500, f"Failed to add camera: {exc}")


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, request: Request) -> dict[str, Any]:
    """Remove a camera from config."""
    try:
        # Parse camera ID (cam01 → index 0)
        try:
            cam_idx = int(camera_id.replace("cam", "")) - 1
            if cam_idx < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "Invalid camera_id format. Use 'cam01', 'cam02', etc.")
        
        # Read config
        config_path = Path("config/ipcam_config.json")
        if not config_path.exists():
            raise HTTPException(404, "Config file not found")
        
        with open(config_path) as f:
            config = json.load(f)
        
        # Check index validity
        if cam_idx >= len(config.get("sources", [])):
            raise HTTPException(404, f"Camera {camera_id} not found")
        
        # Remove
        config["sources"].pop(cam_idx)
        config["camera_names"].pop(cam_idx)
        
        # Write back
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        
        # Regenerate
        import subprocess
        result = subprocess.run(
            ["python3", "scripts/generate_mediamtx_config.py"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            raise Exception(f"Config generation failed: {result.stderr}")
        
        # Reload
        manager: CameraManager = get_manager(request)
        manager.reload()
        
        logger.info(f"Camera removed: {camera_id}")
        return {
            "status": "success",
            "message": f"Camera {camera_id} removed successfully. Restart containers to apply."
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete camera")
        raise HTTPException(500, f"Failed to delete camera: {exc}")


@router.post("/cameras/reload")
async def reload_cameras(request: Request) -> dict[str, Any]:
    """Hot-reload cameras.json without restarting."""
    manager: CameraManager = get_manager(request)
    result = manager.reload()
    return result


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------

@router.get("/persons")
async def list_persons(request: Request, limit: int = 10000) -> list[dict[str, Any]]:
    """Return all known unique persons."""
    manager: CameraManager = get_manager(request)
    if manager.qdrant is None:
        raise HTTPException(503, "Qdrant not ready")
    return manager.qdrant.get_all_persons(limit=limit)


@router.get("/customers/count")
async def get_customer_count(request: Request) -> dict[str, Any]:
    """Return current active customer count (non-staff persons seen in last 3h)."""
    manager: CameraManager = get_manager(request)
    counter = manager.customer_counter
    if counter is None:
        return {"active_customers": 0, "customer_ids": []}
    return {
        "active_customers": counter.count,
        "customer_ids": counter.customer_ids,
    }


@router.get("/person/{person_id}")
async def get_person(person_id: str, request: Request) -> dict[str, Any]:
    """Return full detail for a specific person including history."""
    manager: CameraManager = get_manager(request)
    if manager.qdrant is None:
        raise HTTPException(503, "Qdrant not ready")

    loop = asyncio.get_event_loop()
    qdrant = manager.qdrant
    history = await loop.run_in_executor(
        None, lambda: qdrant.get_person_history(person_id, limit=200)
    )
    if not history:
        raise HTTPException(404, f"Person {person_id} not found")

    cameras = sorted({e.get("camera", "") for e in history})
    snapshots = [e.get("snapshot") for e in history if e.get("snapshot")]
    timestamps = [e.get("timestamp", "") for e in history if e.get("timestamp")]
    person_meta = await loop.run_in_executor(
        None, lambda: qdrant.get_person_metadata(person_id)
    )

    return {
        "person_id": person_id,
        "name": person_meta.get("name"),
        "label": person_meta.get("label"),
        "first_seen": min(timestamps) if timestamps else None,
        "last_seen": max(timestamps) if timestamps else None,
        "cameras_seen": cameras,
        "snapshot_paths": snapshots,
        "total_detections": len(history),
        "history": history,
    }


@router.put("/person/{person_id}")
async def update_person(
    person_id: str,
    request: Request,
    body: UpdatePersonRequest,
) -> dict[str, Any]:
    """Update person metadata (name, label)."""
    manager: CameraManager = get_manager(request)
    if manager.qdrant is None:
        raise HTTPException(503, "Qdrant not ready")

    loop = asyncio.get_event_loop()
    qdrant = manager.qdrant

    # Verify person exists
    history = await loop.run_in_executor(
        None, lambda: qdrant.get_person_history(person_id, limit=1)
    )
    if not history:
        raise HTTPException(404, f"Person {person_id} not found")

    try:
        await loop.run_in_executor(
            None,
            lambda: qdrant.update_person_metadata(
                person_id,
                name=body.name,
                label=body.label,
            ),
        )
        logger.info(f"Updated person {person_id}: name={body.name}, label={body.label}")
        import datetime
        return {
            "status": "success",
            "person_id": person_id,
            "name": body.name,
            "label": body.label,
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.exception("Failed to update person")
        raise HTTPException(500, f"Failed to update person: {exc}")


@router.delete("/person/{person_id}")
async def delete_person(person_id: str, request: Request) -> dict[str, Any]:
    """Remove a person from Qdrant database."""
    manager: CameraManager = get_manager(request)
    if manager.qdrant is None:
        raise HTTPException(503, "Qdrant not ready")

    loop = asyncio.get_event_loop()
    qdrant = manager.qdrant
    try:
        history = await loop.run_in_executor(
            None, lambda: qdrant.get_person_history(person_id, limit=1)
        )
        if not history:
            raise HTTPException(404, f"Person {person_id} not found")

        await loop.run_in_executor(None, lambda: qdrant.delete_person(person_id))
        logger.info(f"Deleted person {person_id}")
        return {
            "status": "success",
            "person_id": person_id,
            "message": f"Person {person_id} deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete person")
        raise HTTPException(500, f"Failed to delete person: {exc}")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/history")
async def get_history(request: Request, limit: int = 200) -> list[dict[str, Any]]:
    """Return recent detection events sorted newest-first."""
    manager: CameraManager = get_manager(request)
    if manager.qdrant is None:
        raise HTTPException(503, "Qdrant not ready")
    loop = asyncio.get_event_loop()
    qdrant = manager.qdrant
    return await loop.run_in_executor(None, lambda: qdrant.get_history(limit=limit))


# ---------------------------------------------------------------------------
# Search by image
# ---------------------------------------------------------------------------

@router.post("/search/image")
async def search_by_image(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """
    Upload an image of a person.
    Extracts ReID embedding and returns top-k similar persons.
    """
    manager: CameraManager = get_manager(request)

    if manager.qdrant is None:
        raise HTTPException(503, "Qdrant not ready")

    # Load image
    try:
        data = await file.read()
        pil_img = Image.open(io.BytesIO(data)).convert("RGB")
        img_array = np.array(pil_img)
        # RGB → BGR for OpenCV/ReID pipeline
        bgr = img_array[:, :, ::-1]
    except Exception as exc:
        raise HTTPException(400, f"Invalid image: {exc}")

    # Extract embedding via the reid model stored in manager
    # (access via CameraManager → shared services)
    try:
        from app.reid.osnet_reid import OSNetReID
        # The manager holds the shared reid instance
        reid_model = getattr(manager, "_reid", None)
        if reid_model is None:
            raise HTTPException(503, "ReID model not ready")
        embedding = reid_model.extract(bgr)
        emb_list = embedding.tolist()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Embedding extraction failed: {exc}")

    # Search Qdrant
    results = manager.qdrant.search_similar(
        embedding=emb_list,
        top_k=top_k,
        score_threshold=0.0,
    )
    return results


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

@router.get("/system")
async def system_info(request: Request) -> dict[str, Any]:
    """Return system health and statistics."""
    manager: CameraManager = get_manager(request)

    qdrant_ok = False
    total_persons = 0
    if manager.qdrant:
        qdrant_ok = manager.qdrant.health()
        try:
            total_persons = manager.qdrant.count_persons()
        except Exception:
            pass

    from app.core.device import is_cuda_available
    statuses = manager.camera_statuses()
    active = sum(1 for s in statuses if s["online"])

    return {
        "uptime_seconds": round(manager.uptime, 1),
        "total_persons": total_persons,
        "active_cameras": active,
        "total_cameras": len(statuses),
        "gpu_available": is_cuda_available(),
        "qdrant_status": "ok" if qdrant_ok else "error",
    }
