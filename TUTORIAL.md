# VisionTrack - Multi-Camera Person Tracking System

Tutorial lengkap untuk setup, run, dan manage sistem.

---

## 📋 Prerequisites

Pastikan sudah install:

- **Docker** & **Docker Compose**
- **Python 3.8+** (untuk helper scripts)
- **NVIDIA GPU** (opsional, untuk akselerasi)
- **Ubuntu/Linux** (tested on Ubuntu 20.04+)

---

## 🚀 Quick Start (Setup dari Awal)

### 1. Clone dan Setup

```bash
# Clone repository
git clone <repo-url>
cd visiontrack_fixed3/project

# Install Python dependencies untuk scripts
pip install pyyaml requests

# (Optional) Setup virtual environment
python3 -m venv venv
source venv/bin/activate
```

### 2. Konfigurasi Kamera

Edit file `config/ipcam_config.json`:

```json
{
  "sources": [
    "0",
    "rtsp://192.168.1.100:554/stream",
    "rtsp://admin:password@192.168.1.101:554/stream"
  ],
  "camera_names": ["USB Camera", "Front Gate CCTV", "Parking CCTV"],
  "tracker": "rfdetr",
  "merger": "bev_cluster",
  "calibration_file": "calibration_data.json"
}
```

**Penjelasan:**

- `"0"` = USB camera (first device `/dev/video0`)
- `"1"` = USB camera (second device `/dev/video1`)
- `"rtsp://..."` = IP camera (CCTV, DVR, NVR)
- `camera_names` = Display name untuk setiap camera (order harus sama dengan sources)

### 3. Generate MediaMTX Config

```bash
python3 scripts/generate_mediamtx_config.py
```

Output:

- `docker/mediamtx.yml` - konfigurasi RTSP relay
- `config/cameras.json` - konfigurasi untuk aplikasi

### 4. Build & Start Container

```bash
# Dengan GPU (NVIDIA)
docker compose up -d

# Atau hanya CPU (pastikan ada docker-compose.cpu.yml)
docker compose -f docker-compose.cpu.yml up -d

# Atau dengan USB camera (gabungkan compose files)
docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d
```

Tunggu ~1-2 menit sampai semua services healthy:

```bash
docker compose ps
```

Output yang diharapkan:

```
NAME                    STATUS
visiontrack-app         Up (healthy)
visiontrack-mediamtx    Up
visiontrack-qdrant      Up (healthy)
```

### 5. Akses Dashboard

Buka browser:

- **Dashboard:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

---

## 🎥 Menambahkan Kamera

### Option A: Via Config File (Permanent)

Edit `config/ipcam_config.json`, tambahkan sumber:

```json
{
  "sources": ["0", "rtsp://192.168.1.102:554/stream"],
  "camera_names": ["USB Camera", "New CCTV"]
}
```

Lalu regenerate config:

```bash
python3 scripts/generate_mediamtx_config.py
```

Reload di app:

```bash
curl -X POST http://localhost:8000/api/cameras/reload
```

### Option B: Via API (Runtime)

```bash
# Format USB camera
curl -X POST http://localhost:8000/api/cameras/add \
  -H "Content-Type: application/json" \
  -d '{
    "source": "1",
    "name": "USB Kamera 2"
  }'

# Format RTSP camera
curl -X POST http://localhost:8000/api/cameras/add \
  -H "Content-Type: application/json" \
  -d '{
    "source": "rtsp://192.168.1.103:554/stream",
    "name": "Lobby CCTV"
  }'
```

Response:

```json
{
  "status": "success",
  "camera_id": "cam02",
  "message": "Camera added successfully"
}
```

### Option C: Via Dashboard

(UI akan ditambahkan di versi berikutnya - untuk sekarang gunakan Option A atau B)

---

## 🗑️ Menghapus Kamera

### Via API

```bash
# Lihat ID camera
curl http://localhost:8000/api/cameras | jq '.[].id'

# Hapus kamera
curl -X DELETE http://localhost:8000/api/cameras/cam01 \
  -H "Content-Type: application/json"
```

Response:

```json
{
  "status": "success",
  "message": "Camera cam01 removed successfully"
}
```

### Via Config File

Edit `config/ipcam_config.json`, hapus sumber yang tidak diinginkan:

```json
{
  "sources": ["rtsp://192.168.1.102:554/stream"],
  "camera_names": ["New CCTV"]
}
```

Regenerate:

```bash
python3 scripts/generate_mediamtx_config.py
curl -X POST http://localhost:8000/api/cameras/reload
```

---

## 🛒 Customer Counting (Real-Time)

VisionTrack secara otomatis membedakan **Staff** dan **Customer**:

| Label | Perilaku |
|-------|----------|
| `staff` | Tidak dihitung, diabaikan dari counter |
| *(kosong / label lain)* | Dihitung sebagai **customer aktif** |

### Cara Kerja
1. Setiap person terdeteksi → sistem cek label di database
2. Jika **bukan staff** → masuk ke hitungan customer aktif
3. Jika **tidak terdeteksi selama 3 jam** → otomatis dikurangi dari count
4. Counter ditampilkan **real-time** di dashboard (oranye) via WebSocket

### Assign Label Staff

Buka halaman person di browser:
```
http://localhost:8000/person/Person_000001
```
Isi form **"Edit Identity"** → pilih label **Staff** → klik Simpan.

Atau via API:
```bash
curl -X PUT http://localhost:8000/api/person/Person_000001 \
  -H "Content-Type: application/json" \
  -d '{"name": "Pak Budi", "label": "staff"}'
```

### Cek Customer Count (API)

```bash
curl http://localhost:8000/api/customers/count
```

Response:
```json
{
  "active_customers": 3,
  "customer_ids": ["Person_000002", "Person_000004", "Person_000007"]
}
```

> ⚠️ Customer counter **reset saat app restart** (in-memory). Data person di Qdrant tetap tersimpan permanen.

---

## 👤 Mengelola Person (Label & Metadata)

### Melihat Semua Person

```bash
curl http://localhost:8000/api/persons?limit=50
```

Response:

```json
{
  "persons": [
    {
      "person_id": "Person_001",
      "name": null,
      "label": null,
      "first_seen": "2026-08-02T10:30:00",
      "last_seen": "2026-08-02T14:45:00",
      "detection_count": 145,
      "cameras": ["cam01", "cam02"],
      "color": "#FF5733"
    }
  ]
}
```

### Memberi Nama / Label Person

```bash
# Beri nama ke person ID
curl -X PUT http://localhost:8000/api/person/Person_001 \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Pak Budi",
    "label": "Visitor"
  }'
```

**Label options:** `visitor`, `staff`, `suspicious`, `vip`, atau custom string

Response:

```json
{
  "status": "success",
  "person_id": "Person_001",
  "name": "Pak Budi",
  "label": "Visitor",
  "updated_at": "2026-08-02T14:50:00"
}
```

### Lihat Detail Person

```bash
curl http://localhost:8000/api/person/Person_001
```

Response:

```json
{
  "person_id": "Person_001",
  "name": "Pak Budi",
  "label": "Visitor",
  "first_seen": "2026-08-02T10:30:00",
  "last_seen": "2026-08-02T14:45:00",
  "detection_count": 145,
  "history": [
    {
      "timestamp": "2026-08-02T14:45:00",
      "camera_id": "cam02",
      "camera_name": "Parking CCTV",
      "bbox": [100, 200, 250, 400],
      "snapshot": "/snapshots/Person_001/snap_001.jpg"
    }
  ]
}
```

### Hapus / Arsipkan Person

```bash
curl -X DELETE http://localhost:8000/api/person/Person_001
```

---

## 🔄 Reset Semua Data (Mulai dari Awal)

> ⚠️ **PERHATIAN:** Langkah ini akan menghapus semua data person, embeddings, dan snapshot secara permanen. Tidak bisa dibatalkan!

### Reset Total (Qdrant + Snapshot + Container)

Ini adalah cara paling bersih untuk memulai dari nol:

```bash
# Matikan semua container DAN hapus volumes
docker compose down -v

# (Opsional) Hapus snapshot yang tersimpan di disk
rm -rf storage/snapshots/*

# Bangun ulang dan jalankan lagi
docker compose up -d
```

Flag `-v` pada `docker compose down -v` akan menghapus:
- Volume `qdrant_storage` → semua embeddings & identity data terhapus
- Volume lain yang terdefinisi di `docker-compose.yml`

### Reset Hanya Database Qdrant (Tanpa Restart Total)

Jika ingin reset data person tapi tetap jaga container tetap hidup:

```bash
# Hapus collection di Qdrant
curl -X DELETE http://localhost:6333/collections/person_embeddings

# Restart app agar collection dibuat ulang
docker compose restart fastapi
```

### Reset Hanya Snapshot

```bash
# Hapus semua foto/snapshot yang tersimpan
rm -rf storage/snapshots/*

# Atau hapus snapshot person tertentu saja
rm -rf storage/snapshots/Person_000001/
```

### Cek Status Setelah Reset

```bash
# Cek container berjalan normal
docker compose ps

# Cek database kosong
curl http://localhost:8000/api/persons
# Seharusnya return [] (array kosong)

# Cek system status
curl http://localhost:8000/api/system
```



## 🔍 Search & Analytics

### Search by Image

Upload foto untuk mencari person yang mirip:

```bash
curl -X POST http://localhost:8000/api/search/image \
  -H "Content-Type: multipart/form-data" \
  -F "file=@person_photo.jpg" \
  -F "top_k=5"
```

Response:

```json
{
  "results": [
    {
      "person_id": "Person_001",
      "name": "Pak Budi",
      "similarity": 0.92,
      "snapshot": "/snapshots/Person_001/snap_001.jpg"
    }
  ]
}
```

### Get Detection History

```bash
curl http://localhost:8000/api/history?limit=100&camera_id=cam01
```

---

## 📊 System Monitoring

### Check System Status

```bash
curl http://localhost:8000/api/system
```

Response:

```json
{
  "uptime_seconds": 3600,
  "gpu_available": true,
  "gpu_info": "NVIDIA GeForce RTX 3050",
  "cameras": {
    "cam01": {
      "status": "online",
      "fps": 15,
      "detection_count": 245,
      "tracked_persons": 12
    },
    "cam02": {
      "status": "online",
      "fps": 15,
      "detection_count": 189,
      "tracked_persons": 8
    }
  }
}
```

---

## 🛠️ Troubleshooting

### Camera Offline / No Stream

```bash
# Cek apakah USB camera terdeteksi
ls -la /dev/video*

# Cek apakah CCTV accessible
curl -v rtsp://192.168.1.100:554/stream

# Lihat MediaMTX logs
docker compose logs mediamtx --tail 50

# Restart services
docker compose restart
```

### High Latency / Lag

Latency bisa sampai 500-1000ms karena:

1. USB → FFmpeg encoding (100-200ms)
2. RTSP transmission (100ms)
3. YOLO detection (50-100ms GPU, 300-500ms CPU)
4. ReID embedding (30-50ms GPU)
5. Browser MJPEG decode (100-200ms)

**Untuk kurangin latency:**

- Gunakan GPU (RTX series lebih cepat)
- Turunkan detection frame skip di `app/core/config.py`
- Reduce video resolution di config kamera

### Container Crash

```bash
# Lihat log error
docker compose logs fastapi --tail 100
docker compose logs mediamtx --tail 100

# Rebuild image
docker compose build --no-cache
docker compose up -d
```

---

## 🔐 Environment Variables

Edit `.env` file untuk custom config:

```env
# API
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=8000
FASTAPI_WORKERS=4

# CUDA/GPU
CUDA_VISIBLE_DEVICES=0
TF_CPP_MIN_LOG_LEVEL=2

# Detection
YOLO_MODEL=yolov8n.pt
YOLO_CONF_THRESHOLD=0.5

# ReID
REID_THRESHOLD=0.3

# Paths
SNAPSHOTS_DIR=/app/storage/snapshots
CONFIG_DIR=/app/config
```

---

## 📝 File Structure

```
project/
├── config/
│   ├── ipcam_config.json      # User kamera config (edit ini)
│   ├── cameras.json           # App camera config (auto-generated)
│   └── calibration_data.json  # (Optional)
├── docker/
│   ├── Dockerfile             # Image untuk GPU
│   ├── Dockerfile.cpu         # Image untuk CPU only
│   ├── mediamtx.yml          # RTSP relay config (auto-generated)
│   └── nginx.conf
├── scripts/
│   ├── generate_mediamtx_config.py  # Generate config dari ipcam_config.json
│   ├── start.sh
│   └── demo_setup.py
├── app/
│   ├── main.py                # FastAPI entry point
│   ├── api/
│   │   └── routes.py          # REST endpoints
│   ├── services/
│   │   ├── camera_manager.py
│   │   ├── camera_pipeline.py # Detection loop
│   │   ├── identity_service.py # Person ID resolution
│   │   └── snapshot_service.py
│   ├── detector/
│   │   └── yolo_detector.py
│   ├── tracker/
│   │   └── bytetrack.py
│   ├── reid/
│   │   └── osnet_reid.py
│   └── core/
│       ├── config.py
│       ├── models.py
│       ├── device.py
│       └── logging.py
├── docker-compose.yml         # Main (GPU + RTSP)
├── docker-compose.cpu.yml     # CPU variant
├── docker-compose.usb.yml     # USB camera overlay
├── requirements.txt
└── README.md
```

---

## 🚀 Production Deployment

### Scale untuk Multiple GPUs

Edit `docker-compose.yml`:

```yaml
services:
  fastapi:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 2
              capabilities: [gpu]
```

### Persistent Volumes

```yaml
volumes:
  snapshots_volume:
    driver: local
  qdrant_volume:
    driver: local

services:
  fastapi:
    volumes:
      - snapshots_volume:/app/storage/snapshots
  qdrant:
    volumes:
      - qdrant_volume:/qdrant/storage
```

### Monitoring & Logging

```bash
# Real-time logs
docker compose logs -f

# Save logs
docker compose logs > logs.txt

# Check resource usage
docker stats
```

---

## 📞 API Reference Lengkap

### Cameras

| Method | Endpoint                | Description                |
| ------ | ----------------------- | -------------------------- |
| GET    | `/api/cameras`          | List semua kamera & status |
| POST   | `/api/cameras/add`      | Tambah kamera baru         |
| DELETE | `/api/cameras/{cam_id}` | Hapus kamera               |
| POST   | `/api/cameras/reload`   | Reload config              |

### Persons

| Method | Endpoint                  | Description                  |
| ------ | ------------------------- | ---------------------------- |
| GET    | `/api/persons`            | List semua person terdeteksi |
| GET    | `/api/person/{person_id}` | Detail person + history      |
| PUT    | `/api/person/{person_id}` | Update name/label person     |
| DELETE | `/api/person/{person_id}` | Hapus person dari DB         |
| POST   | `/api/search/image`       | Search person by image       |

### System

| Method | Endpoint       | Description             |
| ------ | -------------- | ----------------------- |
| GET    | `/api/system`  | System status & metrics |
| GET    | `/api/history` | Detection history       |

---

## 💡 Tips & Tricks

### Performance Tuning

- **Higher FPS:** Reduce detection skip (detect setiap frame) di `camera_pipeline.py`
- **Lower Latency:** Gunakan USB direct, skip RTSP relay
- **More Accuracy:** Increase `YOLO_CONF_THRESHOLD` di `.env`
- **Better ReID:** Lower `REID_THRESHOLD` untuk strict matching

### Custom YOLO Model

```bash
# Download model lain (misal yolov8m untuk akurasi lebih tinggi)
python3 -c "from ultralytics import YOLO; YOLO('yolov8m.pt')"

# Update di .env
YOLO_MODEL=yolov8m.pt

# Restart
docker compose restart fastapi
```

### Backup & Restore

```bash
# Backup database
docker cp visiontrack-qdrant:/qdrant/storage ./qdrant_backup

# Restore
docker cp ./qdrant_backup visiontrack-qdrant:/qdrant/storage
```

---

## 📞 Support

Untuk masalah atau feature request, buka issue atau hubungi team development.

**Last Updated:** August 2, 2026
