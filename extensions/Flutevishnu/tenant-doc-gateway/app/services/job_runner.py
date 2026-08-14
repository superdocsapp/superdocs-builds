"""The actual work a queued job performs.

This lives in a service (not inside the Arq task) so tests can drive a job to
completion with a FAKE SuperDocs client and no Redis — exercising the real logic
without infrastructure.

Resumability: before calling SuperDocs we record a checkpoint (e.g. the upstream
job id). If the worker crashes and the job is retried, we resume from the
checkpoint instead of re-issuing the upstream call, so we never double-charge
operations.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.context import TenantContext
from app.config import Settings
from app.db.models import (
    ChangeStatus,
    Document,
    DocumentStatus,
    Job,
    JobStatus,
    JobType,
)
from app.db.repositories import DocumentRepository, ProposedChangeRepository
from app.integrations.superdocs.client import SuperDocsClient
from app.integrations.superdocs.exceptions import SuperDocsError
from app.logging import add_ops_cost, get_logger
from app.services import cost
from app.services.webhooks import send_webhook

_log = get_logger("job_runner")

_TERMINAL_UPSTREAM = {"completed", "failed"}
_POLL_INTERVAL_SECONDS = 2.0
_MAX_POLLS = 150  # ~5 minutes; long ops are expected (brief), so poll patiently.


async def run_job(
    job_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    superdocs: SuperDocsClient,
    settings: Settings,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
) -> None:
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        if job is None:
            _log.warning("job.missing", job_id=str(job_id))
            return
        ctx = TenantContext(tenant_id=job.tenant_id, api_key_id=job.tenant_id)
        job.attempts += 1
        job.status = JobStatus.RUNNING
        await session.commit()

        try:
            if job.type == JobType.UPLOAD:
                await _run_upload(session, ctx, job, superdocs)
            elif job.type == JobType.EDIT:
                await _run_edit(session, ctx, job, superdocs, settings, poll_interval)
            elif job.type == JobType.EXPORT:
                await _run_export(session, ctx, job, superdocs)
            else:  # pragma: no cover - guarded by enum
                raise ValueError(f"Unknown job type {job.type}")
        except SuperDocsError as exc:
            # Graceful degradation: surface the error on the job, never crash.
            job.status = JobStatus.FAILED
            job.error = str(exc)[:2000]
            await session.commit()
            _log.error("job.failed", job_id=str(job_id), error=str(exc))
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            job.status = JobStatus.FAILED
            job.error = str(exc)[:2000]
            await session.commit()
            _log.error("job.crashed", job_id=str(job_id), error=str(exc))

        await _maybe_webhook(session, job, settings)


async def _run_upload(
    session: AsyncSession, ctx: TenantContext, job: Job, superdocs: SuperDocsClient
) -> None:
    docs = DocumentRepository(session, ctx)
    document = await docs.get(job.document_id)  # type: ignore[arg-type]
    if document is None:
        raise ValueError("Document for upload job not found")

    result = await superdocs.upload_document(
        file_path=document.storage_path,
        filename=document.filename,
        content_type=document.content_type,
    )
    document.superdocs_document_id = result.document_id
    document.superdocs_session_id = result.session_id
    document.status = DocumentStatus.READY

    ops = cost.reconcile(cost.estimate_ops(JobType.UPLOAD), result.ops_cost)
    _finish_success(job, {"document": _doc_summary(document)}, ops)
    await session.commit()


async def _run_edit(
    session: AsyncSession,
    ctx: TenantContext,
    job: Job,
    superdocs: SuperDocsClient,
    settings: Settings,
    poll_interval: float,
) -> None:
    docs = DocumentRepository(session, ctx)
    document = await docs.get(job.document_id)  # type: ignore[arg-type]
    if document is None or not document.superdocs_session_id:
        raise ValueError("Document is not uploaded to SuperDocs yet")

    checkpoint = job.checkpoint or {}
    instruction = checkpoint.get("instruction") or (job.result or {}).get("instruction", "")

    # Resume: only START the upstream edit if we haven't already (checkpoint has
    # no upstream job id). This is what prevents a retry from double-charging.
    if not checkpoint.get("superdocs_job_id"):
        started = await superdocs.start_chat_async(
            session_id=document.superdocs_session_id,
            instruction=instruction,
            approval_mode="ask_every_time",
            model_tier=checkpoint.get("model_tier"),
        )
        job.superdocs_job_id = started.job_id
        job.checkpoint = {**checkpoint, "superdocs_job_id": started.job_id}
        await session.commit()
        latest = started
    else:
        job.superdocs_job_id = checkpoint["superdocs_job_id"]
        latest = await superdocs.get_job(job.superdocs_job_id)

    # Poll until the upstream reaches a terminal state or pauses for approval.
    polls = 0
    while latest.status not in _TERMINAL_UPSTREAM and latest.status != "awaiting_approval":
        if polls >= _MAX_POLLS:
            raise SuperDocsError("Timed out waiting for SuperDocs edit to progress")
        await asyncio.sleep(poll_interval)
        latest = await superdocs.get_job(job.superdocs_job_id or "")
        polls += 1

    ops = cost.reconcile(cost.estimate_ops(JobType.EDIT), latest.ops_cost)
    job.ops_cost = ops
    add_ops_cost(ops)

    if latest.status == "failed":
        raise SuperDocsError("SuperDocs reported the edit failed")

    changes = ProposedChangeRepository(session, ctx)
    if latest.pending_changes:
        # Persist each proposed change (already double-parsed) as its own row so
        # they can be approved/rejected INDEPENDENTLY, item by item.
        for raw in latest.pending_changes:
            await changes.create(
                job_id=job.id,
                document_id=document.id,
                chunk_id=str(raw.get("chunk_id")) if raw.get("chunk_id") else None,
                diff=raw,
                superdocs_change_ref=str(
                    raw.get("change_id") or raw.get("change_ref") or raw.get("id") or ""
                ),
            )
        job.status = JobStatus.AWAITING_APPROVAL
        job.result = {"pending_change_count": len(latest.pending_changes)}
    else:
        _finish_success(job, {"document_html": latest.document_html}, ops)
    await session.commit()


async def _run_export(
    session: AsyncSession, ctx: TenantContext, job: Job, superdocs: SuperDocsClient
) -> None:
    docs = DocumentRepository(session, ctx)
    document = await docs.get(job.document_id)  # type: ignore[arg-type]
    if document is None or not document.superdocs_session_id:
        raise ValueError("Document is not uploaded to SuperDocs yet")

    fmt = (job.checkpoint or {}).get("format", "docx")
    result = await superdocs.export_document(
        session_id=document.superdocs_session_id,
        fmt=fmt,
    )
    _finish_success(
        job,
        {
            "download_url": result.download_url,
            "content_base64": result.content_base64,
            "inline_content": result.inline_content,
            "format": fmt,
        },
        cost.reconcile(cost.estimate_ops(JobType.EXPORT), result.ops_cost),
    )
    await session.commit()


def _finish_success(job: Job, result: dict, ops: float) -> None:
    job.status = JobStatus.SUCCEEDED
    job.result = result
    job.ops_cost = ops


def _doc_summary(document: Document) -> dict:
    return {
        "id": str(document.id),
        "status": document.status.value,
        "superdocs_document_id": document.superdocs_document_id,
    }


async def _maybe_webhook(session: AsyncSession, job: Job, settings: Settings) -> None:
    if not job.webhook_url:
        return
    payload = {
        "event": "job.updated",
        "job_id": str(job.id),
        "status": job.status.value,
        "type": job.type.value,
        "ops_cost": job.ops_cost,
        "result": job.result,
        "error": job.error,
    }
    await send_webhook(
        job.webhook_url,
        payload,
        secret=settings.webhook_signing_secret,
        timeout=settings.webhook_timeout_seconds,
    )


# Re-export for callers that want the ChangeStatus enum alongside the runner.
__all__ = ["run_job", "ChangeStatus"]
