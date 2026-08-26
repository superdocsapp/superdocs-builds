#!/usr/bin/env bash
# ============================================================
#  SuperDocs Task 2 — Start All Services
#  Usage:  ./start.sh
#  Stops:  Ctrl+C  (kills all 4 background processes)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICES=(
  "resume-normaliser:8010"
  "claims-generator:8011"
  "template-filler:8012"
  "house-style-enforcer:8013"
)

# Dashboard served via HTTP to avoid file:// → http://localhost CORS blocks
DASHBOARD_PORT=8080

PIDS=()

cleanup() {
  echo ""
  echo "Stopping all services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "All services stopped."
}
trap cleanup EXIT INT TERM

# ── Check Python ──────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: Python 3 is required but not found on PATH." >&2
  exit 1
fi

PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
  echo "WARNING: Python 3.11+ is recommended (found $PY_MAJOR.$PY_MINOR)."
fi

# ── Install dependencies ──────────────────────────────────────
echo "============================================"
echo "  SuperDocs Task 2 — Service Launcher"
echo "============================================"
echo ""
echo "Installing / verifying dependencies..."
for entry in "${SERVICES[@]}"; do
  dir="${entry%%:*}"
  svc_path="$SCRIPT_DIR/$dir"
  if [[ ! -f "$svc_path/requirements.txt" ]]; then
    echo "  WARNING: $dir/requirements.txt not found, skipping pip install"
    continue
  fi
  "$PYTHON" -m pip install -q -r "$svc_path/requirements.txt"
done
echo ""

# ── Check .env files ──────────────────────────────────────────
echo "Checking .env files..."
MISSING_ENV=0
for entry in "${SERVICES[@]}"; do
  dir="${entry%%:*}"
  svc_path="$SCRIPT_DIR/$dir"
  if [[ ! -f "$svc_path/.env" ]]; then
    echo "  MISSING: $dir/.env  (copy $dir/.env.example → $dir/.env and add your SUPERDOCS_API_KEY)"
    MISSING_ENV=1
  else
    # Check that SUPERDOCS_API_KEY is set (not empty or placeholder)
    KEY=$(grep -E '^SUPERDOCS_API_KEY=' "$svc_path/.env" | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs 2>/dev/null || true)
    if [[ -z "$KEY" ]] || [[ "$KEY" == "your-superdocs-api-key-here" ]] || [[ "$KEY" == "<your_key>" ]]; then
      echo "  WARNING: $dir/.env has no real SUPERDOCS_API_KEY set"
    else
      echo "  OK: $dir/.env"
    fi
  fi
done

if [[ "$MISSING_ENV" -eq 1 ]]; then
  echo ""
  echo "One or more .env files are missing. The services will start but requests will fail."
  echo "Set up each .env then re-run this script (or restart just the affected service)."
  echo ""
fi

# ── Launch services ───────────────────────────────────────────
echo "Launching services..."
echo ""

for entry in "${SERVICES[@]}"; do
  dir="${entry%%:*}"
  port="${entry##*:}"
  svc_path="$SCRIPT_DIR/$dir"

  LOG_FILE="$svc_path/service.log"

  "$PYTHON" -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "$port" \
    --app-dir "$svc_path" \
    --log-level info \
    >> "$LOG_FILE" 2>&1 &

  PIDS+=($!)
  echo "  ✓ $dir  → http://localhost:$port  (log: $dir/service.log)"
done

echo ""

# ── Dashboard static server ───────────────────────────────────
# Serve the dashboard over HTTP so fetch() calls to localhost APIs work
# in all browsers (file:// URLs block cross-origin fetches in Safari).
"$PYTHON" -m http.server "$DASHBOARD_PORT" \
  --directory "$SCRIPT_DIR" \
  >> "$SCRIPT_DIR/dashboard.log" 2>&1 &
PIDS+=($!)
echo "  ✓ dashboard       → http://localhost:$DASHBOARD_PORT/test-dashboard.html"
echo ""

echo "All 4 services + dashboard running."
echo ""
echo "  🌐  Open this in your browser:"
echo "      http://localhost:$DASHBOARD_PORT/test-dashboard.html"
echo ""
echo "Health check URLs:"
for entry in "${SERVICES[@]}"; do
  port="${entry##*:}"
  dir="${entry%%:*}"
  echo "  http://localhost:$port/health   ($dir)"
done
echo ""
echo "Press Ctrl+C to stop all services."
echo "============================================"
echo ""

# ── Auto-open browser ─────────────────────────────────────────
sleep 1
if command -v open &>/dev/null; then
  open "http://localhost:$DASHBOARD_PORT/test-dashboard.html"
elif command -v xdg-open &>/dev/null; then
  xdg-open "http://localhost:$DASHBOARD_PORT/test-dashboard.html"
fi

# ── Wait (give services a moment then do health checks) ───────
sleep 4
echo "Running health checks..."
ALL_HEALTHY=1
for entry in "${SERVICES[@]}"; do
  dir="${entry%%:*}"
  port="${entry##*:}"
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/health" 2>/dev/null || echo "000")
  if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "  ✓ $dir (port $port) — healthy"
  else
    echo "  ✗ $dir (port $port) — HTTP $HTTP_STATUS (check $dir/service.log)"
    ALL_HEALTHY=0
  fi
done

echo ""
if [[ "$ALL_HEALTHY" -eq 1 ]]; then
  echo "All services healthy! You're good to go."
else
  echo "One or more services are not responding. Check the .log files above."
fi
echo ""

# Keep running until Ctrl+C
wait
