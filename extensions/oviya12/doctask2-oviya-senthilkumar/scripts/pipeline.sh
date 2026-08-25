#!/usr/bin/env bash
# One-command pipeline: fetch -> generate -> compat -> mock -> smoke.
# Portable: runs on Linux/macOS/CI and on Windows Git Bash. Tools (oasdiff,
# openapi-generator, prism) run in Docker so a clean machine needs only Docker,
# plus python3 + node to run the smoke tests.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
export MSYS_NO_PATHCONV=1   # harmless on Linux; needed for Docker -v on Git Bash

GEN_IMG=openapitools/openapi-generator-cli@sha256:338dc617d26fb4a515891dee8a5c345ad302e191c6010c6a1f77ed6f6ff7476a
OASDIFF_IMG=tufin/oasdiff@sha256:8f7daabad46bc986290da569589046813de8bfd669fc4bffc3c78060ab2a548d
PRISM_IMG=stoplight/prism@sha256:08dc16243047a3263beca814b544a5be81e9ec25ca5757cdc4170c84f7431355
OLD=specs/superdocs-old.json
NEW=specs/superdocs-new.json
BREAKING=specs/superdocs-breaking.json
MOCK_URL=${SUPERDOCS_MOCK_URL:-http://localhost:4010}

oasdiff() { docker run --rm -v "${ROOT}:/work" "$OASDIFF_IMG" "$@"; }
gen()     { docker run --rm -v "${ROOT}:/local" "$GEN_IMG" "$@"; }

if [[ "${SKIP_FETCH:-0}" == "1" ]]; then
  echo "== 0/5  use supplied specs (SKIP_FETCH=1) =="
else
  echo "== 0/5  fetch pinned specs =="
  bash scripts/fetch.sh
fi

echo "== 1/5  generate typed clients (openapi-generator) =="
gen generate -i "/local/$NEW" -g python -o /local/clients/python \
  --additional-properties=packageName=superdocs_client,projectName=superdocs-client,library=urllib3 \
  --skip-validate-spec >/dev/null
gen generate -i "/local/$NEW" -g typescript-axios -o /local/clients/typescript \
  --additional-properties=npmName=superdocs-client,supportsES6=true,withSeparateModelsAndApi=true,apiPackage=api,modelPackage=models \
  --skip-validate-spec >/dev/null
python scripts/patch_generated.py --spec "$NEW"
echo "   python: $(find clients/python -type f | wc -l | tr -d ' ') files | typescript: $(find clients/typescript -type f | wc -l | tr -d ' ') files"

echo "== 2/5  compatibility report (old -> new) =="
oasdiff changelog -f json "/work/$OLD" "/work/$NEW" > reports/changelog.json 2>/dev/null
python scripts/compat.py --changelog reports/changelog.json --base "$OLD" --revision "$NEW" --out reports --gate

echo "   breaking-gate demo (new -> synthesized breaking) —"
oasdiff changelog -f json "/work/$NEW" "/work/$BREAKING" > reports/changelog-breaking.json 2>/dev/null
if python scripts/compat.py --changelog reports/changelog-breaking.json --base "$NEW" --revision "$BREAKING" --out reports/breaking-demo --gate; then
  echo "   ERROR: gate did NOT fail on breaking changes"; exit 1
else
  echo "   gate correctly returned non-zero on breaking changes (CI would fail)"
fi

echo "== 3/5  mock server (prism) =="
docker rm -f superdocs-mock >/dev/null 2>&1 || true
docker run -d --rm --name superdocs-mock -p 4010:4010 -v "${ROOT}:/tmp" "$PRISM_IMG" mock -h 0.0.0.0 "/tmp/$NEW" >/dev/null
trap 'docker rm -f superdocs-mock >/dev/null 2>&1 || true' EXIT
for i in $(seq 1 30); do curl -fsS -H 'Authorization: Bearer smoke-test-token' -o /dev/null "$MOCK_URL/v1/users/me" 2>/dev/null && break; sleep 1; done
echo "   prism serving $NEW at $MOCK_URL"

echo "== 4/5  python smoke (generated client -> mock) =="
[ -d .venv ] || python -m venv .venv
PYBIN=.venv/Scripts/python.exe; [ -x "$PYBIN" ] || PYBIN=.venv/bin/python
"$PYBIN" -m pip install -q --upgrade pip >/dev/null
"$PYBIN" -m pip install -q -e clients/python pytest >/dev/null
SUPERDOCS_MOCK_URL="$MOCK_URL" "$PYBIN" -m pytest tests/python -q

echo "== 5/5  typescript smoke (generated client -> mock) =="
[ -d node_modules ] || npm install --silent
SUPERDOCS_MOCK_URL="$MOCK_URL" npx tsx tests/typescript/smoke.ts

echo ""
echo "PIPELINE OK — clients generated, compat report written, gate verified, both smoke tests passed."
