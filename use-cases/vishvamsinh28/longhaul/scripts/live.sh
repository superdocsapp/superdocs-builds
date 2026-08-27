#!/usr/bin/env bash
# The operator console, pointed at the real SuperDocs API.
#
# This spends operations. The console opens idle and does nothing until you press Run,
# and the budget is set in that same click — so nothing is charged by surprise.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  printf '\033[31mNo .env file.\033[0m Copy .env.example to .env and put your key in it.\n'
  printf 'Get one from use.superdocs.app -> Settings -> API Keys.\n'
  exit 2
fi

printf '\033[2mChecking the key (GET /v1/sessions — costs nothing)…\033[0m\n'
uv run longhaul doctor

STATE="${LONGHAUL_STATE_DIR:-state/live}"
printf '\n\033[1mConsole (LIVE · api.superdocs.app): http://127.0.0.1:8420\033[0m  ctrl-c to stop\n'
printf '\033[2mIt opens idle. Press Run when you want it to spend.\033[0m\n\n'
LONGHAUL_STATE_DIR="$STATE" uv run longhaul serve \
  --spec "${LONGHAUL_SPEC:-jobs/proof-compact.yaml}" --port 8420
