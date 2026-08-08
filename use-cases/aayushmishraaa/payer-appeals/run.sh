#!/usr/bin/env bash
# From a clean clone to a running app.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
[ -f .env ] && set -a && . ./.env && set +a
if [ -z "${SUPERDOCS_API_KEY:-}" ]; then
  echo "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and add your key." >&2
  exit 1
fi
exec ./.venv/bin/python -m uvicorn app.main:app --reload --port 8080
