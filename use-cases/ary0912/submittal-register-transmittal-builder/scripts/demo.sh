#!/bin/bash
set -e

echo "============================================================"
echo "DocTask: Seeding Complete Demo Dataset"
echo "============================================================"

# Navigate to project root
cd "$(dirname "$0")/.."

# Seed demo dataset using python
backend/.venv/bin/python scripts/seed_demo.py

echo ""
echo "Demo environment is ready!"
echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://localhost:3000"
