"""Idempotency for money/token-costing operations.

CONTRACT (what this must guarantee):
- The SAME Idempotency-Key + SAME request body must NEVER create two jobs or
  double-charge SuperDocs — even under two truly concurrent requests.
- The SAME key + a DIFFERENT body is a client bug -> 409 (never a silent wrong
  replay).
- A completed operation replays its stored response verbatim.

HOW the concurrency guarantee works (this is the important part):
We do NOT "check then insert" (that has a race window). We INSERT FIRST and let
the DB's UNIQUE(tenant_id, key) constraint be the arbiter. Exactly one racing
transaction wins the insert; the other gets an IntegrityError, rolls back, reads
the winner's row, and replays it. No application-level lock required — the
database is the single source of truth for "who got there first".
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import TenantContext
from app.db.models import IdempotencyKey, IdempotencyStatus

# The producer creates the durable side effect (e.g. a Job row) and returns the
# HTTP status, the response body, and the created job id (if any).
Producer = Callable[[AsyncSession], Awaitable[tuple[int, dict[str, Any], uuid.UUID | None]]]


@dataclass
class IdempotencyOutcome:
    replayed: bool
    status_code: int
    body: dict[str, Any]
    job_id: uuid.UUID | None


def compute_request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _get_row(session: AsyncSession, ctx: TenantContext, key: str) -> IdempotencyKey | None:
    result = await session.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == ctx.tenant_id,
            IdempotencyKey.key == key,
        )
    )
    return result.scalar_one_or_none()


async def run_idempotent(
    session: AsyncSession,
    ctx: TenantContext,
    key: str,
    request_payload: dict[str, Any],
    producer: Producer,
) -> IdempotencyOutcome:
    request_hash = compute_request_hash(request_payload)

    # Step 1: try to claim the key by INSERTING it. The unique constraint makes
    # this the atomic "compare-and-swap" that decides the winner.
    row = IdempotencyKey(
        tenant_id=ctx.tenant_id,
        key=key,
        request_hash=request_hash,
        status=IdempotencyStatus.PROCESSING,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # Someone else already claimed this key. Roll back our failed insert and
        # replay/deny based on their row (which is now committed).
        await session.rollback()
        return await _replay_existing(session, ctx, key, request_hash)

    # Step 2: we own the key. Produce the side effect in the SAME transaction so
    # the job and the idempotency record commit together, atomically.
    status_code, body, job_id = await producer(session)
    row.status = IdempotencyStatus.COMPLETED
    row.response_status = status_code
    row.response_body = body
    row.job_id = job_id
    await session.commit()
    return IdempotencyOutcome(replayed=False, status_code=status_code, body=body, job_id=job_id)


async def _replay_existing(
    session: AsyncSession, ctx: TenantContext, key: str, request_hash: str
) -> IdempotencyOutcome:
    existing = await _get_row(session, ctx, key)
    if existing is None:
        # Extremely rare (row vanished between conflict and read). Treat as retryable.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency conflict; please retry.",
        )
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was reused with a different request body.",
        )
    if existing.status == IdempotencyStatus.COMPLETED:
        return IdempotencyOutcome(
            replayed=True,
            status_code=existing.response_status or status.HTTP_200_OK,
            body=existing.response_body or {},
            job_id=existing.job_id,
        )
    # Winner still in-flight (has not committed yet). Ask the client to retry.
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="A request with this Idempotency-Key is still processing.",
    )
