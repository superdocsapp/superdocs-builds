FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EDIT_PRECISION_PROJECT_ROOT=/app
WORKDIR /app
COPY README.md ./README.md
COPY backend/ ./backend/
RUN pip install --no-cache-dir ./backend
COPY corpus/ ./corpus/
COPY results/ ./results/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
EXPOSE 8080
CMD ["uvicorn", "edit_precision_evaluator.api:app", "--host", "0.0.0.0", "--port", "8080"]
