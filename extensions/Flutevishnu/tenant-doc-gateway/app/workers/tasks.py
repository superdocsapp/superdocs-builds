"""Arq task entrypoints.

These are thin: they build a real SuperDocs client + DB sessionmaker and hand
off to `job_runner.run_job`, which holds all the logic and is unit-tested with a
fake client.
"""

from __future__ import annotations

import uuid

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.integrations.superdocs.client import SuperDocsClient
from app.services.job_runner import run_job


async def process_job(ctx: dict, job_id: str) -> None:
    settings = get_settings()
    superdocs = SuperDocsClient(
        base_url=settings.superdocs_base_url,
        api_key=settings.superdocs_api_key,
        timeout_seconds=settings.superdocs_timeout_seconds,
    )
    try:
        await run_job(
            uuid.UUID(job_id),
            sessionmaker=get_sessionmaker(),
            superdocs=superdocs,
            settings=settings,
        )
    finally:
        await superdocs.aclose()
