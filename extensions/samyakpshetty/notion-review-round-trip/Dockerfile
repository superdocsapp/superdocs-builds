# Python 3.12 — the host is 3.9, so every command runs in here (matches CI exactly).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so the layer caches across source edits.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev,web]"

# Source + tests are bind-mounted in compose for the dev loop; copied here so the
# image is self-contained for a clean `docker build`.
COPY tests ./tests

CMD ["python", "-c", "import notion_review; print(notion_review.__version__)"]
