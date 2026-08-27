#!/bin/sh
# Renewal Desk runner for machines without a local Python.
#
# Runs the CLI inside the official python:3.12-slim image with this folder
# mounted. The project has no dependencies, so no image build is needed.
#
#     ./run.sh plan
#     ./run.sh run --sample 1
#     ./run.sh review
#     ./run.sh decide ACM-1042 approve
#     ./run.sh report
#
# The key is read from .env in this folder (see .env.example).

set -e
PROJECT="$(cd "$(dirname "$0")" && pwd)"

# MSYS_NO_PATHCONV keeps Git Bash on Windows from rewriting /app into a
# Windows path before docker sees it.
MSYS_NO_PATHCONV=1 exec docker run --rm \
  -v "$PROJECT:/app" \
  -w /app \
  python:3.12-slim \
  python renewal_desk.py "$@"
