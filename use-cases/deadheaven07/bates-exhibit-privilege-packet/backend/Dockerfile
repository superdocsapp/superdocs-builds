FROM python:3.11-slim

# System deps: tesseract OCR, libreoffice (optional), poppler (pdf2image), libmagic
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libreoffice-core \
    poppler-utils \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pyproject.toml and create a dummy README so pip install works
COPY pyproject.toml ./
RUN touch README.md

# Install Python deps first (cache layer)
RUN pip install --no-cache-dir .

# Copy application code
COPY . .

# Create storage directories
RUN mkdir -p storage/originals storage/processed storage/working storage/final

EXPOSE 8000

# Run migrations then start server
CMD alembic upgrade head; \
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
