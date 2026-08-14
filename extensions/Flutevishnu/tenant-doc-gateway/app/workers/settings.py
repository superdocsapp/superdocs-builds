"""Arq worker configuration. Run with:  arq app.workers.settings.WorkerSettings"""

from __future__ import annotations

from arq.connections import RedisSettings

from app.config import get_settings
from app.logging import configure_logging
from app.workers.tasks import process_job


async def on_startup(ctx: dict) -> None:
    configure_logging(get_settings().log_level)


class WorkerSettings:
    functions = [process_job]
    on_startup = on_startup
    # Arq reads `redis_settings` at startup to connect to the queue broker.
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Bound concurrency so a burst of jobs can't exhaust upstream rate limits.
    max_jobs = 10
    job_timeout = 60 * 10  # 10 minutes; long ops are expected per the brief.
