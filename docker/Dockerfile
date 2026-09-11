# ============================================================
# VisionTrack — FastAPI App Dockerfile (GPU)
# Base: python:3.12-slim-bookworm
# ============================================================

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# ── System dependencies ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgomp1 \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

# ── Step 1: numpy DULU (torchreid setup.py butuh numpy saat build) ──
RUN pip install numpy==1.26.4

# ── Step 2: PyTorch CUDA 12.1 ────────────────────────────────
RUN pip install \
    torch==2.3.0+cu121 \
    torchvision==0.18.0+cu121 \
    --index-url https://download.pytorch.org/whl/cu121

# ── Step 3: Torchreid dependencies lalu torchreid ────────────
RUN pip install Cython h5py six scipy opencv-python-headless gdown tensorboard \
    && pip install \
    --no-build-isolation \
    git+https://github.com/KaiyangZhou/deep-person-reid.git

# ── Step 4: App requirements ─────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# ── Step 5: Pre-download YOLO model ──────────────────────────
# RUN python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

# ── Application source ───────────────────────────────────────
COPY app/ ./app/
COPY config/ ./config/
RUN mkdir -p /app/storage/snapshots

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio"]
