# One stage: this service has no UI. It is a proxy — a request comes in, gates
# run, a request goes out — so the image is a Python runtime, five dependencies
# and nothing else.
#
# No LangGraph, no Postgres, no model stack. That is the point of
# `cp -r extensions/policy-gateway` being a complete pull request.

FROM python:3.12-slim AS runtime
WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.29

# Source BEFORE install, deliberately — the usual deps-first trick installs a
# distribution with no modules in it, and that fails in a genuinely confusing
# way: uvicorn puts the working directory on sys.path so the SERVER comes up
# fine, while the `gateway` console script (which does not) dies with
# ModuleNotFoundError. The service looks healthy and
# `docker compose exec gateway gateway audit verify` is broken — exactly the
# command an operator reaches for first.
#
# The cost is that editing a Python file re-resolves the dependencies. With
# five pure-Python packages that is a few seconds, and correctness is worth
# more than those seconds here.
COPY pyproject.toml ./
COPY gateway/ gateway/
RUN uv pip install --system --no-cache .

# The audit log lives here and compose mounts a volume over it. It must be
# writable by the runtime user: the gateway fails CLOSED on an unwritable log
# and will refuse to start, which is the correct behaviour and an infuriating
# one to debug if the reason is a permission bit set at build time.
RUN mkdir -p /app/data \
 && useradd --create-home --uid 1000 gateway \
 && chown -R gateway:gateway /app
USER gateway

EXPOSE 8080

# Plain HTTP. TLS terminates at the ingress in front of this — a policy gateway
# that also wants to be a TLS endpoint is two services wearing one coat.
#
# One worker on purpose. The quota counters and the audit chain head are
# in-process state; a second worker would keep its own copy of both, so two
# workers would mean two half-counted quotas and two writers racing on one
# chain. Scaling past one process needs shared state — noted in README.md as
# the honest v1 limit rather than hidden behind a --workers flag that appears
# to work until the invoice disagrees.
CMD ["uvicorn", "gateway.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
