#!/bin/sh
# Cause + fix printed before uvicorn starts. Exit 1 on missing config.
set -eu

fail() {
  echo "ERROR: $1" >&2
  echo "Cause: $2" >&2
  echo "Fix: $3" >&2
  exit 1
}

if [ ! -d /app/config ]; then
  fail \
    "config/ directory is missing inside the container." \
    "The image was built without the project config tree." \
    "Rebuild from use-cases/kathans22/pitch-deck-narrative with: docker compose build --no-cache"
fi

if [ ! -f /app/config/deck-manifest.yaml ]; then
  fail \
    "config/deck-manifest.yaml is missing." \
    "Mount or image copy did not include the deck manifest." \
    "Ensure config/ is present in the build context, then: docker compose up --build"
fi

KEY="${SUPERDOCS_API_KEY:-}"
if [ -z "$KEY" ]; then
  fail \
    "SUPERDOCS_API_KEY is not set." \
    "Compose started without a usable .env (or the variable is empty)." \
    "From this folder: cp .env.example .env  then set SUPERDOCS_API_KEY=sk_…  then: docker compose up --build"
fi

if [ "$KEY" = "your-key-here" ]; then
  fail \
    "SUPERDOCS_API_KEY is still the placeholder." \
    ".env was copied from .env.example but the key was not replaced." \
    "Edit .env and set SUPERDOCS_API_KEY to a real sk_ key from use.superdocs.app → Settings → API Keys"
fi

exec "$@"
