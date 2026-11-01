#!/usr/bin/env bash
set -euo pipefail
# Do not set -x — that would leak SUPERDOCS_API_KEY.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -z "${SUPERDOCS_API_KEY:-}" ]]; then
  echo "SUPERDOCS_API_KEY is missing. Set SUPERDOCS_API_KEY=your-key-here" >&2
  exit 2
fi
python -m soc2_index.cli \
  --evidence fixtures/cedar-harbor-v1 \
  --out runs/v1 \
  --session cedar-harbor-idx-v1 \
  --generated-at 2025-06-01T00:00:00Z

python -m soc2_index.cli \
  --evidence fixtures/cedar-harbor-v2 \
  --from runs/v1 \
  --out runs/v2 \
  --generated-at 2025-06-21T00:00:00Z

echo "exports:"
ls -l runs/v1/export runs/v2/export
