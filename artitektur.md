# VisionTrack — Multi-Camera Person Tracking & Re-Identification System

A production-ready, dockerized system for detecting, tracking, and re-identifying people across multiple IP/RTSP cameras in real time.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         VisionTrack System                           │
│                                                                      │
│  config/cameras.json                                                 │
│       │                                                              │
│       ▼                                                              │
│  CameraManager ──── hot reload ────────────────────────────────┐    │
│       │                                                         │    │
│       ├── CameraPipeline (cam01) ──────────────────────────┐   │    │
│       ├── CameraPipeline (cam02)                           │   │    │
│       └── CameraPipeline (camNN)                           │   │    │
│                                                             │   │    │
│  Per-camera loop (async + thread pool):                     │   │    │
│                                                             │   │    │
│  RTSP/Video ──► YOLO11 ──► ByteTrack ──► Crop ──► OSNet   │   │    │
│                                                    │        │   │    │
│                                             512-dim embedding│   │    │
│                                                    │        │   │    │
│                                                    ▼        │   │    │
│                                             IdentityService  │   │    │
│                                             │   └── Qdrant  │   │    │
│                                             │    cosine sim  │   │    │
│                                             │                │   │    │
│                                             ▼                │   │    │
│                                       GlobalPerson ID        │   │    │
│                                             │                │   │    │
│                              ┌──────────────┴──────────────┐ │   │    │
│                              │      WebSocket Broadcast     │ │   │    │
│                              └──────────────────────────────┘ │   │    │
│                                                               │   │    │
└───────────────────────────────────────────────────────────────┘   │    │
                                                                     │    │
┌───────────────────────────────────────────────────────────────────┐    │
│  FastAPI                                                          │    │
│   ├── REST API   /api/*                                           │    │
│   ├── WebSocket  /ws/events                                       │    │
│   ├── MJPEG      /stream/{camera_id}                             │    │
│   └── Dashboard  / /live /persons /history /search /settings     │    │
└───────────────────────────────────────────────────────────────────┘    │
                                                                          │
┌─────────────────┐    ┌────────────────────────────────────────────────┐│
│  Qdrant         │◄───│  Collection: person_embeddings                 ││
│  Vector DB      │    │  512-dim COSINE vectors + payload              ││
│  :6333          │    │  {person_id, camera, timestamp, bbox, snapshot}││
└─────────────────┘    └────────────────────────────────────────────────┘│
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web Framework | FastAPI + Uvicorn |
| Detection | Ultralytics YOLO11 (COCO pretrained) |
| Tracking | ByteTrack (via supervision library) |
| Re-ID | Torchreid OSNet x1.0 (Market-1501 pretrained) |
| Vector DB | Qdrant |
| Frontend | Jinja2 + Vanilla JS + WebSocket |
| Containerisation | Docker + Docker Compose |
| GPU | CUDA 12.1 (automatic fallback to CPU) |

---

## Quick Start

### Prerequisites

- Docker 24+ and Docker Compose v2
- NVIDIA GPU with CUDA 12.1+ drivers (optional — CPU mode available)
- NVIDIA Container Toolkit (for GPU mode)

### 1. Clone the project

```bash
git clone <repo-url> visiontrack
cd visiontrack
```

### 2. Configure cameras

Edit `config/cameras.json`:

```json
{
    "cameras": [
        {
            "id": "cam01",
            "name": "Front Door",
            "location": "Building A",
            "rtsp": "rtsp://192.168.1.10/live"
        },
        {
            "id": "cam02",
            "name": "Lobby",
            "location": "Building A",
            "rtsp": "rtsp://192.168.1.11/live"
        }
    ],
    "settings": {
        "similarity_threshold": 0.75,
        "detection_confidence": 0.50,
        "reid_batch_size": 8,
        "snapshot_interval": 30,
        "max_track_age": 30,
        "reconnect_delay": 5,
        "frame_skip": 2
    }
}
```

> **Adding a new camera:** only edit `cameras.json` and click "Reload" in Settings — no code changes, no restart required.

### 3. Launch (GPU mode)

```bash
docker compose up -d
```

### 4. Launch (CPU mode)

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d
```

### 5. Access the dashboard

| URL | Description |
|---|---|
| http://localhost:8000 | Dashboard |
| http://localhost:8000/live | Live camera streams |
| http://localhost:8000/persons | All detected persons |
| http://localhost:8000/history | Detection timeline |
| http://localhost:8000/search | Image-based person search |
| http://localhost:8000/settings | System settings & camera reload |
| http://localhost:8000/docs | Swagger API docs |
| http://localhost:6333/dashboard | Qdrant vector DB UI |

---

## Project Structure

```
project/
├── app/
│   ├── api/
│   │   ├── routes.py          # REST API endpoints
│   │   ├── stream.py          # MJPEG stream + snapshot serving
│   │   └── ws.py              # WebSocket /ws/events
│   ├── core/
│   │   ├── config.py          # Settings, cameras.json loader
│   │   ├── device.py          # CUDA / CPU auto-detection
│   │   ├── logging.py         # Structured per-camera logging
│   │   └── models.py          # Shared Pydantic v2 data models
│   ├── detector/
│   │   └── yolo_detector.py   # YOLO11 person detector wrapper
│   ├── tracker/
│   │   └── bytetrack.py       # ByteTrack multi-object tracker
│   ├── reid/
│   │   └── osnet_reid.py      # OSNet x1.0 embedding extractor
│   ├── qdrant_client/
│   │   └── qdrant_service.py  # Qdrant vector DB client
│   ├── services/
│   │   ├── camera_pipeline.py # Per-camera processing pipeline
│   │   ├── camera_manager.py  # Lifecycle + hot-reload manager
│   │   ├── identity_service.py# Global person ID resolution
│   │   └── snapshot_service.py# Crop image persistence
│   ├── websocket/
│   │   └── manager.py         # WS connection manager + broadcaster
│   ├── templates/             # Jinja2 HTML pages
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── live.html
│   │   ├── persons.html
│   │   ├── person_detail.html
│   │   ├── history.html
│   │   ├── search.html
│   │   └── settings.html
│   ├── static/                # CSS, JS, images
│   │   ├── css/main.css
│   │   ├── js/main.js
│   │   └── img/
│   └── main.py                # FastAPI app factory + page routes
├── config/
│   └── cameras.json           # Camera configuration (edit this)
├── storage/
│   └── snapshots/             # Saved person crops (auto-created)
│       └── Person_000001/
│           ├── cam01_001.jpg
│           └── cam02_003.jpg
├── docker/
│   ├── Dockerfile             # GPU image
│   ├── Dockerfile.cpu         # CPU-only image
│   └── nginx.conf             # Nginx reverse proxy config
├── scripts/
│   ├── start.sh               # Launch helper
│   ├── utils.sh               # Health check, reset, logs
│   └── demo_setup.py          # Generate demo cameras.json
├── docker-compose.yml         # Primary compose (GPU)
├── docker-compose.cpu.yml     # CPU override
├── requirements.txt
├── .env.example
└── README.md
```

---

## Pipeline Detail

### 1. Person Detection (YOLO11)

- Model: `yolo11n.pt` (nano, ~6 MB — fast)
- Filters COCO class 0 (person) only
- Configurable confidence threshold

### 2. Multi-Object Tracking (ByteTrack)

- Each camera has its own independent tracker instance
- Assigns stable per-camera `track_id` across frames
- Falls back to IoU tracker if `supervision` is unavailable

### 3. ReID Embedding (OSNet x1.0)

- Input: 256×128 px crop (H×W), BGR→RGB normalised
- Output: 512-dimensional L2-normalised feature vector
- No training — uses pretrained Market-1501 weights

### 4. Global Identity Resolution

```
embedding → Qdrant cosine search (top-1, threshold=0.75)
    │
    ├── score ≥ threshold → reuse Person_XXXXXX
    └── score < threshold → mint new Person_XXXXXX
         │
         ▼
    upsert to Qdrant + save snapshot
```

### 5. WebSocket Events

```json
{
  "event_type": "new_person",
  "camera_id": "cam01",
  "timestamp": "2026-07-25T14:20:15",
  "payload": {
    "person_id": "Person_000023",
    "track_id": 7,
    "similarity": 0.0,
    "bbox": [100, 50, 250, 400],
    "snapshot": "snapshots/Person_000023/cam01_001.jpg"
  }
}
```

Event types: `new_person`, `new_detection`, `camera_online`, `camera_offline`

---

## REST API Reference

### Cameras

| Method | Path | Description |
|---|---|---|
| GET | `/api/cameras` | List all cameras with online status |
| POST | `/api/cameras/reload` | Hot-reload cameras.json |

### Persons

| Method | Path | Description |
|---|---|---|
| GET | `/api/persons?limit=100` | All unique detected persons |
| GET | `/api/person/{id}` | Full detail + history for one person |

### History

| Method | Path | Description |
|---|---|---|
| GET | `/api/history?limit=200` | Recent detection events, newest first |

### Search

| Method | Path | Description |
|---|---|---|
| POST | `/api/search/image?top_k=10` | Upload image → top-K similar persons |

### System

| Method | Path | Description |
|---|---|---|
| GET | `/api/system` | Uptime, GPU status, Qdrant health, counts |

### Streaming

| Method | Path | Description |
|---|---|---|
| GET | `/stream/{camera_id}` | MJPEG live stream |
| GET | `/snapshots/{person_id}/{file}` | Saved snapshot image |

### WebSocket

| Path | Description |
|---|---|
| `/ws/events` | Real-time event stream (JSON frames) |

---

## Configuration Reference

### cameras.json settings

| Key | Default | Description |
|---|---|---|
| `similarity_threshold` | `0.75` | Cosine similarity cutoff for identity matching |
| `detection_confidence` | `0.50` | YOLO minimum detection confidence |
| `reid_batch_size` | `8` | Crops per OSNet forward pass |
| `snapshot_interval` | `30` | Minimum frames between snapshots per person |
| `max_track_age` | `30` | Frames before a lost track is pruned |
| `reconnect_delay` | `5` | Seconds between RTSP reconnect attempts |
| `frame_skip` | `2` | Process 1 in every N frames (CPU throttle) |

### Environment variables (.env)

| Variable | Default | Description |
|---|---|---|
| `APP_QDRANT_HOST` | `qdrant` | Qdrant hostname |
| `APP_QDRANT_PORT` | `6333` | Qdrant port |
| `APP_YOLO_MODEL` | `yolo11n.pt` | YOLO model file |
| `APP_EMBEDDING_DIM` | `512` | Embedding dimension |
| `APP_DEBUG` | `false` | Enable debug logging |

---

## Adding a New Camera

1. Open `config/cameras.json`
2. Add a new entry to the `cameras` array:
   ```json
   {
     "id": "cam03",
     "name": "Parking Lot",
     "location": "Building B",
     "rtsp": "rtsp://192.168.1.12/stream"
   }
   ```
3. Either:
   - Click **Settings → Reload Cameras** in the dashboard, or
   - `curl -X POST http://localhost:8000/api/cameras/reload`

No restart required.

---

## Deployment Notes

### Nginx (production)

Uncomment the `nginx` service in `docker-compose.yml` to enable the reverse proxy on port 80. It handles WebSocket upgrade headers and disables buffering for MJPEG streams.

### Qdrant persistence

Qdrant data is stored in the `visiontrack_qdrant_data` Docker volume. It persists across container restarts. To reset:

```bash
./scripts/utils.sh reset-db
```

### Resource requirements

| Mode | Min RAM | GPU VRAM |
|---|---|---|
| CPU (2 cameras) | 4 GB | — |
| GPU (4 cameras) | 8 GB | 4 GB |
| GPU (8+ cameras) | 16 GB | 8 GB |

---

## Useful Commands

```bash
# View logs
docker compose logs -f fastapi

# Check health
./scripts/utils.sh health

# Reload cameras after editing cameras.json
./scripts/utils.sh reload-cam

# Stop everything
docker compose down

# Stop and delete volumes (full reset)
docker compose down -v
```

---

## License

MIT
