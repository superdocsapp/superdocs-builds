#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== creating venv =="
python3 -m venv .venv
source .venv/bin/activate

echo "== installing dependencies =="
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "== running offline test suite =="
pytest tests/ -q

echo "== starting demo server on http://127.0.0.1:8000 =="
uvicorn app.api.main:app --reload
