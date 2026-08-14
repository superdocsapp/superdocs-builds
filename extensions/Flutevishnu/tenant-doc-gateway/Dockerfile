# Single image used for BOTH the API and the worker (same code, different command).
# Keeping one image means the queue worker and the API can never drift apart.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so layer caches across code changes.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Runtime data dir for streamed uploads (also declared in .env.example UPLOAD_DIR).
RUN mkdir -p /data/uploads

# Non-root user for defense in depth.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Default command runs the API. The worker service overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
