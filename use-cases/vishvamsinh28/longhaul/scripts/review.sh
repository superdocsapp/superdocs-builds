#!/usr/bin/env bash
# The browser review UI, wired to the local deterministic stand-in so it needs no key.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
WORK="$(mktemp -d)"
cleanup() { [[ -n "${FAKE_PID:-}" ]] && kill "$FAKE_PID" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

FAKE_STATE_DIR="$WORK/fake" FAKE_PORT="$PORT" uv run python tests/fake/server.py \
  >"$WORK/fake.log" 2>&1 &
FAKE_PID=$!
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/v1/sessions" >/dev/null 2>&1 && break
  sleep 0.2
done

export SUPERDOCS_API_KEY="sk_demo_00000000000000000000000000000000"
export SUPERDOCS_BASE_URL="http://127.0.0.1:$PORT"
export LONGHAUL_STATE_DIR="$WORK/state"

printf '\033[1mReview UI: http://127.0.0.1:8420\033[0m  (ctrl-c to stop)\n'
uv run longhaul serve --spec jobs/runbook-migration.yaml --port 8420
