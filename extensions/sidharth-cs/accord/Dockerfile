# Packaging only — the app itself is unchanged. Two stages: build the
# existing React frontend, then serve it from the existing FastAPI backend
# exactly as main.py already does locally (frontend/dist at /, mounted at
# /assets — see main.py's own comments). Chosen over Railway's Nixpacks/
# Railpack auto-builders after three failed attempts each hit real,
# under-documented multi-stage/input-chaining behavior for this repo's
# split backend/ + frontend/ layout — see PROGRESS.md M3 Railway migration
# for the concrete build-log evidence. Standard Python+Node multi-stage
# pattern; nothing app-specific here beyond the existing directory layout.

FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Railway injects $PORT at runtime; 8010 is only the local-dev fallback.
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8010}"]
