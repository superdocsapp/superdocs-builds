# Production image for the backend API. Does NOT bake in secrets --
# WORKFLOW_API_KEYS/TENANTS_CONFIG_PATH, BOX_*, SUPERDOCS_*, etc. are
# supplied at run time (see .env.example). Mount a volume at /data and
# set PERSISTENCE_DB_PATH=/data so each tenant's review queue, audit
# trail, and checkpoints (one SQLite file per tenant) survive a
# container restart.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

ENV PYTHONPATH=/app
ENV PERSISTENCE_DB_PATH=/data
ENV ENVIRONMENT=production

EXPOSE 8000

# Fails fast and loudly (see app/api/main.py's startup guards) if
# WORKFLOW_API_KEYS/TENANTS_CONFIG_PATH or PERSISTENCE_DB_PATH aren't
# supplied at run time -- this image will not silently serve an
# unauthenticated or non-durable API.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
