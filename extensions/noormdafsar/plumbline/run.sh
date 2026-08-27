#!/bin/sh
# Plumbline for machines without a local Python. Same arguments as the CLI.
set -e
P="$(cd "$(dirname "$0")" && pwd)"
MSYS_NO_PATHCONV=1 exec docker run --rm -v "$P:/app" -w /app python:3.12-slim \
  python plumbline.py "$@"
