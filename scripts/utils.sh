#!/usr/bin/env bash
# ============================================================
# VisionTrack — Utility Scripts
# Usage:
#   ./scripts/utils.sh health      # Check service health
#   ./scripts/utils.sh reset-db    # Delete all Qdrant data
#   ./scripts/utils.sh logs        # Tail app logs
#   ./scripts/utils.sh reload-cam  # Hot-reload cameras.json
# ============================================================

set -euo pipefail

CMD="${1:-help}"
BASE_URL="http://localhost:8000"

case "$CMD" in
  health)
    echo "=== VisionTrack Health Check ==="
    echo ""
    echo "FastAPI:"
    curl -sf "${BASE_URL}/api/system" | python3 -m json.tool || echo "  ❌ FastAPI unreachable"
    echo ""
    echo "Qdrant:"
    curl -sf "http://localhost:6333/healthz" && echo "  ✅ Qdrant OK" || echo "  ❌ Qdrant unreachable"
    ;;

  reset-db)
    echo "⚠️  This will DELETE all person embeddings and tracking history."
    read -rp "Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" == "yes" ]; then
      curl -sf -X DELETE "http://localhost:6333/collections/person_embeddings" && echo "✅ Collection deleted"
      echo "Restart the app to recreate the collection:"
      echo "  docker compose restart fastapi"
    else
      echo "Aborted."
    fi
    ;;

  logs)
    docker compose logs -f --tail=100 fastapi
    ;;

  reload-cam)
    echo "Reloading cameras.json …"
    curl -sf -X POST "${BASE_URL}/api/cameras/reload" | python3 -m json.tool
    ;;

  *)
    echo "Usage: $0 {health|reset-db|logs|reload-cam}"
    exit 1
    ;;
esac
