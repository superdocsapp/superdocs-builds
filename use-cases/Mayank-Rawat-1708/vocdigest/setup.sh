#!/usr/bin/env bash
#
# VocDigest one-command setup.
#
# Brings up Postgres, installs backend dependencies, runs migrations, runs the test
# suite (which needs no API keys), generates sample data, and starts the API, the MCP
# server and the frontend.
#
# Usage:
#   ./setup.sh              full setup and start everything
#   ./setup.sh --test-only  install dependencies and run the tests, start nothing
#   ./setup.sh --no-docker  skip Postgres and use SQLite (no database server needed)

set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { echo -e "\n${CYAN}==>${NC} $1"; }
ok()   { echo -e "${GREEN}  ok${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }
die()  { echo -e "${RED}  x${NC} $1"; exit 1; }

TEST_ONLY=false
USE_DOCKER=true
for arg in "$@"; do
  case "$arg" in
    --test-only) TEST_ONLY=true ;;
    --no-docker) USE_DOCKER=false ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ---------------------------------------------------------------- prerequisites
step "Checking prerequisites"
command -v python3 >/dev/null || die "python3 not found (3.11+ required)"
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "python $PY_VERSION"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || die "Python 3.11+ required, found $PY_VERSION"

# ---------------------------------------------------------------- configuration
step "Configuring environment"
if [ ! -f .env ]; then
  cp .env.example .env
  ok "created .env from .env.example"
  warn "Add SUPERDOCS_API_KEY and GROQ_API_KEY to .env before running a live digest."
  warn "Neither key is needed for the test suite."
else
  ok ".env already exists (left untouched)"
fi

# ---------------------------------------------------------------- database
if [ "$USE_DOCKER" = true ] && [ "$TEST_ONLY" = false ]; then
  step "Starting Postgres with pgvector"
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    docker compose up -d postgres
    printf "  waiting for Postgres"
    for _ in $(seq 1 40); do
      if docker compose exec -T postgres pg_isready -U vocdigest -d vocdigest >/dev/null 2>&1; then
        echo ""; ok "Postgres ready"; break
      fi
      printf "."; sleep 1
    done
  else
    warn "Docker unavailable — falling back to SQLite"
    USE_DOCKER=false
  fi
fi

if [ "$USE_DOCKER" = false ]; then
  # SQLite needs no server. The models are dialect-portable, so this is a real fallback
  # rather than a degraded mode — only pgvector similarity search is unavailable.
  export DATABASE_URL="sqlite+aiosqlite:///./data/vocdigest.db"
  export AUTO_CREATE_TABLES=true
  mkdir -p data
  ok "using SQLite at ./data/vocdigest.db"
fi

# ---------------------------------------------------------------- dependencies
step "Installing backend dependencies"
# Use an existing .venv if one is present. Homebrew Python refuses a system-wide pip
# install (PEP 668), so without this the script fails on macOS unless the caller
# remembered to activate the venv first.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -d "$ROOT/.venv" ]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  ok "activated existing .venv"
elif [ -z "${VIRTUAL_ENV:-}" ]; then
  python3 -m venv "$ROOT/.venv"
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  ok "created .venv"
else
  ok "using active venv: $VIRTUAL_ENV"
fi

python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r backend/requirements.txt
ok "backend dependencies installed"

# ---------------------------------------------------------------- migrations
if [ "$USE_DOCKER" = true ] && [ "$TEST_ONLY" = false ]; then
  step "Running database migrations"
  PYTHONPATH="$ROOT" alembic upgrade head && ok "schema at head"
fi

# ---------------------------------------------------------------- tests
step "Running tests (no API keys required)"
if PYTHONPATH="$ROOT" python3 -m pytest backend/tests/ -q --no-header; then
  ok "all tests passed"
else
  die "tests failed — stopping before starting services"
fi

if [ "$TEST_ONLY" = true ]; then
  echo -e "\n${GREEN}Tests complete.${NC} Re-run without --test-only to start the stack."
  exit 0
fi

# ---------------------------------------------------------------- sample data
step "Generating sample data"
if [ ! -f sample_data/q3_2026_conversations.csv ]; then
  PYTHONPATH="$ROOT" python3 scripts/generate_sample_data.py
else
  ok "sample data already present"
fi

# ---------------------------------------------------------------- services
step "Starting services"
mkdir -p data logs

PYTHONPATH="$ROOT" python3 -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 8000 > logs/api.log 2>&1 &
API_PID=$!
ok "API starting (pid $API_PID) — logs/api.log"

PYTHONPATH="$ROOT" python3 -m backend.mcp.server > logs/mcp.log 2>&1 &
MCP_PID=$!
ok "MCP server starting (pid $MCP_PID) — logs/mcp.log"

printf "  waiting for API"
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo ""; ok "API healthy"; break
  fi
  printf "."; sleep 1
done

step "Installing frontend dependencies"
cd frontend
npm install --silent --no-audit --no-fund
ok "frontend dependencies installed"

echo -e "\n${GREEN}VocDigest is running.${NC}"
echo "  Frontend : http://localhost:3000"
echo "  API docs : http://localhost:8000/docs"
echo "  MCP      : http://localhost:8001"
echo ""
echo "  Stop the background services with: kill $API_PID $MCP_PID"
echo ""
npm run dev
