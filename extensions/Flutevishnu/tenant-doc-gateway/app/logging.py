"""Structured JSON logging and request middleware for cost tracking.

Core logging requirements:
1. Emit structured, machine-parseable JSON logs without leaking secrets.
2. Include a per-request `ops_cost` field to track downstream API token usage
   and operation costs for observability.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

# Request-scoped context that log lines automatically pick up.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")
# Workers/services increment this to attribute SuperDocs op cost to a request.
ops_cost_ctx: ContextVar[float] = ContextVar("ops_cost", default=0.0)


def _inject_context(_, __, event_dict: dict) -> dict:
    event_dict.setdefault("request_id", request_id_ctx.get())
    event_dict.setdefault("tenant_id", tenant_id_ctx.get())
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def add_ops_cost(amount: float) -> None:
    """Attribute SuperDocs operation cost to the current request/job."""
    ops_cost_ctx.set(ops_cost_ctx.get() + amount)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, resets cost, and emits one structured access log."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._log = get_logger("http")

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_ctx.set(request_id)
        tenant_id_ctx.set("-")
        ops_cost_ctx.set(0.0)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._log.info(
                "request.completed",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                ops_cost=round(ops_cost_ctx.get(), 4),
            )
