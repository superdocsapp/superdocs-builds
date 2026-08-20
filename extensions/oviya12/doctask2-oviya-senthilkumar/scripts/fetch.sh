#!/usr/bin/env bash
# Fetch the two pinned spec versions from the published SuperDocs docs repo and
# (re)generate the breaking-demo spec. Pinned by commit SHA for reproducibility.
# If offline, keeps the vendored copies already committed to specs/.
set -euo pipefail
cd "$(dirname "$0")/.."

OLD_SHA=a8351de   # 2026-06-24  (65 paths)
NEW_SHA=ac0d44c   # 2026-07-23  (77 paths) — latest openapi.json commit

fetch_spec() {
  local url="$1" out="$2"
  if curl -fsSL "$url" -o "$out.tmp" 2>/dev/null && [ -s "$out.tmp" ]; then
    mv "$out.tmp" "$out"; echo "  fetched $out"
  else
    rm -f "$out.tmp"; echo "  (offline) kept vendored $out"
  fi
}

mkdir -p specs
echo "fetching pinned specs from github.com/superdocsapp/docs ..."
fetch_spec "https://raw.githubusercontent.com/superdocsapp/docs/${OLD_SHA}/openapi.json" specs/superdocs-old.json
fetch_spec "https://raw.githubusercontent.com/superdocsapp/docs/${NEW_SHA}/openapi.json" specs/superdocs-new.json
python scripts/make_breaking_demo.py
