#!/bin/sh
# Renewal Desk review console. Opens on http://localhost:7000
set -e
PROJECT="$(cd "$(dirname "$0")" && pwd)"
echo "Starting the review console on http://localhost:7000  (Ctrl-C to stop)"
MSYS_NO_PATHCONV=1 exec docker run --rm -p 7000:7000 -v "$PROJECT:/app" -w /app \
  python:3.12-slim python renewal_desk.py serve --port 7000
