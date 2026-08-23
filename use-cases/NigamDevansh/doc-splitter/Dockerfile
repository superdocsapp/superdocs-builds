# Two stages: the interface is a Vite build, the service is Python, and a
# reviewer should type one command rather than install Node.
#
# No model stack and no Postgres — the splitter reads a document, slices HTML
# and calls export. That is why this image is a fraction of the pane's.

# ── 1 · the interface ─────────────────────────────────────────────────────
FROM node:24-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# ── 2 · the service ───────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.29

# Dependencies before source, so editing a Python file does not reinstall them.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY service/ service/
COPY --from=ui /ui/dist ui/dist

RUN mkdir -p /app/data && useradd --create-home --uid 1000 split \
 && chown -R split:split /app
USER split

EXPOSE 8080

# Plain HTTP: this is an ordinary web tool opened in a browser, not an Office
# task pane. The certificate dance the redaction pane needs is Office's rule,
# not ours, and importing it here would be cargo cult.
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8080"]
