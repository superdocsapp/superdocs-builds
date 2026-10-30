# syntax=docker/dockerfile:1
#
# The mock, containerised: REST at /v1/* and MCP at /mcp/ on one port, exactly as
# api.superdocs.app serves them.
#
# Two properties this image is built for, in order:
#
#   1. It starts fast. Startup time is a graded property of this project, so the runtime
#      layer carries Starlette, uvicorn and nothing else -- no build tools, no compiler,
#      no test dependencies.
#   2. It needs no network and no key. Every response comes from the cassettes baked into
#      the image, so a CI job can run offline and a sandboxed runner will not surprise you.

# ---------------------------------------------------------------- build
FROM python:3.12-slim AS build

WORKDIR /build
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src/ ./src/
# The wheel bundles the fixtures (see pyproject's force-include), so they have to be in
# the build context before the install, not after it.
COPY spec/ ./spec/
COPY cassettes/ ./cassettes/
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="sdmock" \
      org.opencontainers.image.description="Offline mock server and contract-test fixtures for the SuperDocs REST API and MCP server" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/superdocsapp/superdocs-builds"

# Unbuffered so container logs appear immediately; no .pyc writes to a read-only layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH" \
    SDMOCK_HOST=0.0.0.0 \
    SDMOCK_PORT=8080 \
    SDMOCK_CASSETTES=/app/cassettes \
    SDMOCK_SPEC=/app/spec

COPY --from=build /venv /venv

WORKDIR /app
# The data the mock serves, also on disk and pointed at by SDMOCK_CASSETTES / SDMOCK_SPEC,
# so an integrator can mount their own recordings over the baked-in ones. Kept as a
# separate layer from the code so re-recording a scenario rebuilds only this.
COPY spec/ ./spec/
COPY cassettes/ ./cassettes/

# Never root. The mock reads its own fixtures and writes nothing.
RUN useradd --create-home --uid 10001 sdmock \
 && chown -R sdmock:sdmock /app
USER sdmock

EXPOSE 8080

# The readiness signal a compose file or an orchestrator waits on. Deliberately the
# zero-auth REST probe, mirroring the real service's own unauthenticated /health.
HEALTHCHECK --interval=5s --timeout=3s --start-period=2s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2).status==200 else 1)"

ENTRYPOINT ["sdmock"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080", "--quiet"]
