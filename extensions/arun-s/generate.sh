#!/usr/bin/env bash
# Task 2.1 — generate typed SuperDocs clients from the public OpenAPI spec.
set -euo pipefail
SPEC_URL="${SPEC_URL:-https://api.superdocs.app/openapi.json}"
mkdir -p openapi python typescript go
echo "Fetching spec: $SPEC_URL"
curl -fsSL "$SPEC_URL" -o openapi/superdocs.json || {
  echo "Try SPEC_URL=https://docs.superdocs.app/openapi.json ./generate.sh"; exit 1; }
echo "Spec saved to openapi/superdocs.json ($(wc -c < openapi/superdocs.json) bytes)"
# Python:  pip install openapi-python-client && openapi-python-client generate --path openapi/superdocs.json --output-path python
# TS:      npx @openapitools/openapi-generator-cli generate -i openapi/superdocs.json -g typescript-axios -o typescript
# Go:      npx @openapitools/openapi-generator-cli generate -i openapi/superdocs.json -g go -o go
echo "Next: run the generators above, then ../doctask-arun-s: pytest conformance/"
