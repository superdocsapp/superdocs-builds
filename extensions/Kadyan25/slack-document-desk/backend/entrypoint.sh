#!/usr/bin/env bash
set -e

echo "Applying migrations (retrying until the database accepts connections)..."
until python -m alembic upgrade head; do
  echo "Database not ready yet, retrying in 2s..."
  sleep 2
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
