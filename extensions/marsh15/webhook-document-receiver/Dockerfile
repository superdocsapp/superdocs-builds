FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.17 && uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY routes ./routes
COPY templates ./templates
RUN addgroup --system app && adduser --system --ingroup app app
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
