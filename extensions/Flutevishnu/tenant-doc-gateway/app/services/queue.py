"""Job queue abstraction.

The API only knows how to `enqueue(task_name, job_id)`. In production this is
backed by Arq + Redis; in tests it is a fake that records calls and never needs
Redis. This keeps the HTTP layer testable with zero infrastructure.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings


class JobQueue(Protocol):
    async def enqueue(self, task_name: str, job_id: uuid.UUID) -> None: ...


class ArqJobQueue:
    """Real queue: pushes onto Redis for the Arq worker to pick up."""

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, task_name: str, job_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(task_name, str(job_id))


_pool: ArqRedis | None = None


async def get_job_queue() -> JobQueue:
    """FastAPI dependency returning the process-wide Arq-backed queue."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return ArqJobQueue(_pool)


async def close_job_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
