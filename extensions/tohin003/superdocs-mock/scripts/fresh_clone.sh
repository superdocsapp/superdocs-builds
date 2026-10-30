#!/usr/bin/env bash
# Walk the README quickstart on a clean checkout, and fail if any step is wrong.
#
# "A stranger can go from clone to working in minutes" is a claim like any other, so it is
# tested rather than hoped. CI runs this on every push; run it yourself before believing
# the README.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
SERVER=""
cleanup() { [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> copying the tree to a clean directory (no .venv, no caches)"
rsync -a --exclude .venv --exclude .git --exclude '__pycache__' \
      --exclude '.pytest_cache' "$HERE/" "$WORK/"
cd "$WORK"

echo "==> python -m venv .venv && pip install -e '.[test]'"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e '.[test]'

echo "==> pytest  (no API key, no network)"
env -u SUPERDOCS_API_KEY ./.venv/bin/python -m pytest contract/ -q

echo "==> sdmock serve, then the four-call contract over both transports"
./.venv/bin/sdmock serve --port 8123 --quiet &
SERVER=$!
for _ in $(seq 1 100); do
  curl -sf http://127.0.0.1:8123/health >/dev/null 2>&1 && break
  sleep 0.1
done

curl -sf -o /dev/null -H "Authorization: Bearer sk_test_anything" \
     -H "X-Mock-Scenario: styled-document" \
     -X POST http://127.0.0.1:8123/v1/documents/upload
echo "    upload ok"

curl -sf -o /dev/null -X POST -H "Authorization: Bearer sk_test_anything" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
     http://127.0.0.1:8123/mcp/
echo "    MCP tools/list ok"

echo "==> sdmock catalogue"
./.venv/bin/sdmock catalogue >/dev/null
echo "    catalogue ok"

echo
echo "fresh clone -> working mock: OK"
