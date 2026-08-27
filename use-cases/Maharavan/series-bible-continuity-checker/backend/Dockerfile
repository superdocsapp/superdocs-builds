FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "series_bible.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
