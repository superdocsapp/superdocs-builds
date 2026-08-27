# Python 3.12 — every command runs in here, so local matches CI byte for byte.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

# Source and tests are bind-mounted in compose for the dev loop; copied here so the image
# is self-contained for a clean `docker build`.
COPY tests ./tests
COPY config ./config
COPY migrations ./migrations
COPY templates ./templates
COPY sample ./sample

CMD ["uvicorn", "inspection_report.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
