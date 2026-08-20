"""
Per-API-key rate limiting.

In-process token bucket, keyed by the caller's API key (falls back to
client IP for unauthenticated requests, e.g. hitting a protected route
with no/bad key -- still worth throttling to slow down credential
guessing).

LIMITATION: this state lives in the process's memory. That's fine for a
single Render instance (the default `starter` plan is one instance), but
if you ever scale to multiple instances/workers, each one enforces its
own limit independently -- the effective limit becomes (per-instance
limit x instance count), not a true global limit. At that point, swap
the in-memory buckets below for Redis (e.g. `redis` + a sliding-window
Lua script, or a package like `slowapi` backed by Redis) so all
instances share one counter. That swap is intentionally NOT done here
since it requires provisioning Redis, which is a real infra decision for
you to make, not something to silently add.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

DEFAULT_LIMIT = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))
DEFAULT_WINDOW_S = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))


class InMemoryRateLimiter:
    def __init__(self, limit: int = DEFAULT_LIMIT, window_s: int = DEFAULT_WINDOW_S):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = int(self.window_s - (now - hits[0])) + 1
                return False, retry_after
            hits.append(now)
            return True, 0


_limiter = InMemoryRateLimiter()


def _client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return f"key:{auth.removeprefix('Bearer ').strip()}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/healthz",):
            return await call_next(request)
        key = _client_key(request)
        allowed, retry_after = _limiter.allow(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Retry after {retry_after}s."},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
