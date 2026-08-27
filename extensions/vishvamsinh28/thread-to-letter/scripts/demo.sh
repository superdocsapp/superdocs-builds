#!/usr/bin/env bash
# The whole pipeline against the local stand-in. No key, no network, no cost.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
WORK="$(mktemp -d)"
cleanup(){ [[ -n "${FAKE_PID:-}" ]] && kill "$FAKE_PID" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

FAKE_PORT="$PORT" uv run python tests/fake/server.py >"$WORK/fake.log" 2>&1 &
FAKE_PID=$!
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/v1/sessions" >/dev/null 2>&1 && break; sleep 0.2
done

export SUPERDOCS_API_KEY="sk_demo_00000000000000000000000000000000"
export SUPERDOCS_BASE_URL="http://127.0.0.1:$PORT"

printf '\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
printf '\033[1mA messy thread. Two real commitments buried in hedges.\033[0m\n'
printf '\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
uv run thread2letter show threads/migration-project.mbox

printf '\n\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
printf '\033[1mWhat was actually committed to — and what was refused.\033[0m\n'
printf '\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
uv run thread2letter run threads/migration-project.mbox --auto --format markdown \
  --from "you@example.com" --out "$WORK/out"

printf '\n\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
printf '\033[1mThe letter it wrote\033[0m\n'
printf '\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
cat "$WORK"/out/*.md

printf '\n\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
printf '\033[1mThe reply draft, ready to open in a mail client\033[0m\n'
printf '\033[2m─────────────────────────────────────────────────────────────\033[0m\n'
head -22 "$WORK"/out/reply-*.eml

printf '\n\033[2mNote: this ran against the local stand-in, so the classification above is\033[0m\n'
printf '\033[2mfixed test data. `make live` runs the same pipeline against the real API.\033[0m\n'
