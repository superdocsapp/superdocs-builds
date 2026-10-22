#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtualenv
source venv/bin/activate

# Create storage directories
python -c "from app.config import get_settings; get_settings().ensure_directories()"

# Run alembic migrations
alembic upgrade head 2>/dev/null || echo "⚠ Alembic migration skipped (DB may already be up to date)"

# Start the server
echo "Starting Bates Packet Builder on http://localhost:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
