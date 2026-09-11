#!/usr/bin/env bash
# ============================================================
# VisionTrack — Startup Script
# Usage:
#   ./scripts/start.sh           # GPU mode (default)
#   ./scripts/start.sh --cpu     # CPU mode
#   ./scripts/start.sh --build   # Force rebuild
#   ./scripts/start.sh --down    # Stop & remove containers
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

CPU_MODE=false
BUILD_FLAG=""
DOWN_MODE=false

for arg in "$@"; do
  case $arg in
    --cpu)   CPU_MODE=true ;;
    --build) BUILD_FLAG="--build" ;;
    --down)  DOWN_MODE=true ;;
  esac
done

# ── Stop ────────────────────────────────────────────────────
if $DOWN_MODE; then
  echo "⏹  Stopping VisionTrack …"
  docker compose down
  exit 0
fi

# ── Env file ────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "📝  Created .env from .env.example"
fi

# ── Build & launch ──────────────────────────────────────────
if $CPU_MODE; then
  echo "🖥  Starting VisionTrack (CPU mode) …"
  echo "🔧  Generating mediamtx and cameras config from ipcam_config.json (if present)"
  python3 scripts/generate_mediamtx_config.py || true
  docker compose \
    -f docker-compose.yml \
    -f docker-compose.cpu.yml \
    up -d $BUILD_FLAG
else
  echo "🚀  Starting VisionTrack (GPU mode) …"
  echo "🔧  Generating mediamtx and cameras config from ipcam_config.json (if present)"
  python3 scripts/generate_mediamtx_config.py || true
  docker compose up -d $BUILD_FLAG
fi

echo ""
echo "✅  VisionTrack is starting up."
echo "    Dashboard:  http://localhost:8000"
echo "    API docs:   http://localhost:8000/docs"
echo "    Qdrant UI:  http://localhost:6333/dashboard"
echo ""
echo "    Logs: docker compose logs -f fastapi"
