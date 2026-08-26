# API image — ClarityDocs pitch-script generator (FastAPI)
FROM python:3.12-slim

WORKDIR /app

# Install package + deps first for layer caching
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY config ./config
COPY evidence ./evidence
COPY scripts/docker-entrypoint-api.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/out /app/state

ENV PYTHONUNBUFFERED=1
ENV SUPERDOCS_CHAT_BATCH_CAP=2

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "generator.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
