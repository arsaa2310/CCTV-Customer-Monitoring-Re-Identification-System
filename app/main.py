"""
VisionTrack — Multi-Camera Person Tracking & Re-Identification System
FastAPI application entry point.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.api.stream import stream_router
from app.api.ws import ws_router
from app.core.config import settings
from app.core.logging import setup_root_logging
from app.services.camera_manager import CameraManager

# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start camera manager on startup, stop on shutdown."""
    setup_root_logging()
    manager: CameraManager = app.state.manager
    manager.startup()
    yield
    manager.shutdown()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Shared state
    app.state.manager = CameraManager()

    # Static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Snapshot files
    snapshots_dir = Path(__file__).parent.parent / "storage" / "snapshots"
    app.mount("/snapshots", StaticFiles(directory=str(snapshots_dir)), name="snapshots")

    # API routers
    app.include_router(api_router)
    app.include_router(stream_router)
    app.include_router(ws_router)

    # Template routes (dashboard pages)
    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    # ---- Page routes ----

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(
            "dashboard.html", {"request": request, "page": "dashboard"}
        )

    @app.get("/live", response_class=HTMLResponse)
    async def live(request: Request):
        return templates.TemplateResponse(
            "live.html", {"request": request, "page": "live"}
        )

    @app.get("/persons", response_class=HTMLResponse)
    async def persons(request: Request):
        return templates.TemplateResponse(
            "persons.html", {"request": request, "page": "persons"}
        )

    @app.get("/person/{person_id}", response_class=HTMLResponse)
    async def person_detail(person_id: str, request: Request):
        manager: CameraManager = request.app.state.manager
        data = {"person_id": person_id, "snapshot_paths": [], "cameras_seen": [],
                "history": [], "first_seen": None, "last_seen": None,
                "total_detections": 0, "name": None, "label": None,
                "qdrant_error": None}
        if manager.qdrant:
            try:
                loop = asyncio.get_event_loop()
                qdrant_host = settings.qdrant_host
                qdrant_port = settings.qdrant_port
                pid = person_id  # capture for lambda

                def _fetch_all():
                    """Run in thread — create own client to avoid sharing."""
                    from qdrant_client import QdrantClient as _QC
                    from qdrant_client.http import models as _m
                    c = _QC(host=qdrant_host, port=qdrant_port, timeout=15)
                    filt = _m.Filter(must=[_m.FieldCondition(
                        key="person_id", match=_m.MatchValue(value=pid)
                    )])
                    hist_pts, _ = c.scroll(
                        collection_name=settings.qdrant_collection,
                        scroll_filter=filt, limit=10000,
                        with_payload=True, with_vectors=False,
                    )
                    meta_pts, _ = c.scroll(
                        collection_name=settings.qdrant_collection,
                        scroll_filter=filt, limit=1,
                        with_payload=True, with_vectors=False,
                    )
                    c.close()
                    hist = [dict(r.payload or {}) for r in hist_pts]
                    hist.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                    meta_payload = dict(meta_pts[0].payload or {}) if meta_pts else {}
                    return hist, meta_payload

                history, meta_payload = await loop.run_in_executor(None, _fetch_all)
                cameras = sorted({e.get("camera", "") for e in history})
                
                snaps = []
                seen_snaps = set()
                for e in history:
                    p = e.get("snapshot")
                    if p and p not in seen_snaps:
                        seen_snaps.add(p)
                        snaps.append({
                            "path": p,
                            "timestamp": e.get("timestamp"),
                            "camera": e.get("camera")
                        })
                        
                ts = [e.get("timestamp", "") for e in history if e.get("timestamp")]
                data.update({
                    "history": history,
                    "cameras_seen": cameras,
                    "snapshot_paths": snaps,
                    "first_seen": min(ts) if ts else None,
                    "last_seen": max(ts) if ts else None,
                    "total_detections": len(history),
                    "name": meta_payload.get("person_name"),
                    "label": meta_payload.get("person_label"),
                })
            except Exception as exc:
                data["qdrant_error"] = str(exc)
        return templates.TemplateResponse(
            "person_detail.html", {"request": request, "page": "persons", **data}
        )

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        return templates.TemplateResponse(
            "history.html", {"request": request, "page": "history"}
        )

    @app.get("/search", response_class=HTMLResponse)
    async def search(request: Request):
        return templates.TemplateResponse(
            "search.html", {"request": request, "page": "search"}
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(
            "settings.html", {"request": request, "page": "settings"}
        )

    return app


app = create_app()
