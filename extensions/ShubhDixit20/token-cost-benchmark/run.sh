#!/usr/bin/env bash
# One-command reproduction of the benchmark, per "a runner reproduces
# everything with one command."
#
# Default: mock mode (free, offline, deterministic) across the full corpus,
# 3 repeats for variance, then builds the tables/charts.
#
# For a real-API run:
#   SUPERDOCS_API_KEY=sk-... ./run.sh --mode real --small-sample --budget-usd 0.50
# (always small-sample + a tight budget first; see README "Budget guard.")
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv 2>/dev/null || true
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
pip install -q -r requirements.txt --break-system-packages 2>/dev/null || pip install -q -r requirements.txt

echo "== Running tests (no live key required) =="
python3 -m pytest tests/ -q

echo "== Running benchmark =="
python3 -m benchmark.runner \
  --corpus-dir data/corpus \
  --results-dir data/results \
  --repeats 3 \
  "$@"

echo "== Building reports =="
python3 -m benchmark.report data/results

echo "Done. See data/results/ for raw_edits.csv, summary tables, and charts."
