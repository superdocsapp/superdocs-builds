import asyncio
import os
import random
import socket
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

import httpx
from psycopg_pool import ConnectionPool

from app.config import Settings, get_settings
from app.persistence import ClaimedJob, DeliveryStore, LeaseLostError
from app.routes import Route
from app.superdocs import (
    DocumentResult,
    JobSnapshot,
    StartedJob,
    SuperDocsClient,
    SuperDocsHTTPError,
)
from scripts.migrate import migrate


class DocumentProcessor(Protocol):
    async def start_event(
        self,
        event_id: str,
        payload: dict[str, object],
        *,
        approval_mode: Literal["approve_all", "ask_every_time"],
        instruction: str | None = None,
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        target_document_id: str | None = None,
    ) -> StartedJob: ...

    async def get_job(self, job_id: str) -> JobSnapshot: ...

    async def submit_decisions(
        self,
        *,
        session_id: str,
        job_id: str,
        decisions: list[dict[str, object]],
    ) -> None: ...

    async def continue_job(self, *, session_id: str, job_id: str) -> None: ...

    async def export(
        self,
        *,
        event_id: str,
        session_id: str,
        job_id: str,
        export_format: str | None = None,
    ) -> DocumentResult: ...


def retry_delay(
    *,
    retry_count: int,
    base_seconds: float,
    max_seconds: float,
    retry_after_seconds: float | None = None,
) -> float:
    if retry_after_seconds is not None:
        return min(max_seconds, retry_after_seconds)
    exponential = min(max_seconds, base_seconds * (2**retry_count))
    return min(max_seconds, exponential * random.uniform(0.8, 1.2))


def record_failure(
    *, store: DeliveryStore, job: ClaimedJob, settings: Settings, error: Exception
) -> None:
    if isinstance(error, LeaseLostError):
        return
    if isinstance(error, SuperDocsHTTPError):
        if error.status_code in {401, 403, 404, 409}:
            store.needs_attention(job=job, reason=str(error))
            return
        if error.status_code == 429 or error.status_code >= 500:
            if job.retry_count < settings.worker_max_retries:
                store.retry(
                    job=job,
                    error=error,
                    delay_seconds=retry_delay(
                        retry_count=job.retry_count,
                        base_seconds=settings.retry_base_seconds,
                        max_seconds=settings.retry_max_seconds,
                        retry_after_seconds=error.retry_after_seconds,
                    ),
                )
            else:
                store.fail(job=job, error=error)
            return
        store.fail(job=job, error=error)
        return
    if isinstance(error, httpx.TimeoutException):
        store.needs_attention(
            job=job,
            reason="External timeout may have followed a side effect; reconcile before retrying",
        )
        return
    if isinstance(error, httpx.ConnectError):
        if job.retry_count < settings.worker_max_retries:
            store.retry(
                job=job,
                error=error,
                delay_seconds=retry_delay(
                    retry_count=job.retry_count,
                    base_seconds=settings.retry_base_seconds,
                    max_seconds=settings.retry_max_seconds,
                ),
            )
        else:
            store.fail(job=job, error=error)
        return
    store.fail(job=job, error=error)


async def run_once(
    *,
    store: DeliveryStore,
    processor: DocumentProcessor,
    settings: Settings,
    worker_id: str,
) -> bool:
    job = store.claim(worker_id=worker_id, lease_seconds=settings.worker_lease_seconds)
    if job is None:
        return False
    try:
        if job.superdocs_job_id is None:
            if job.recovered and job.external_effect_started_at is not None:
                store.needs_attention(
                    job=job,
                    reason=(
                        "Worker lease expired after a possible SuperDocs start; "
                        "reconcile before retrying"
                    ),
                )
                return True
            route = Route.model_validate(job.route_config)
            approval_mode = route.approval.policy
            target_document_id: str | None = None
            if route.workflow.target is not None:
                target_document_id = os.environ.get(route.workflow.target.file_id_env)
                if not target_document_id:
                    store.needs_attention(
                        job=job,
                        reason=(
                            f"Route requires configured document environment variable "
                            f"{route.workflow.target.file_id_env}"
                        ),
                    )
                    return True
            template_instruction = (
                f'Use the uploaded SuperDocs template named "{route.template.name}" as the '
                f"starting structure. {route.instruction}"
            )
            store.mark_starting(job=job)
            try:
                started = await processor.start_event(
                    str(job.delivery_id),
                    job.input_data,
                    approval_mode=approval_mode,
                    instruction=template_instruction,
                    model_tier=route.model.tier,
                    thinking_depth=route.model.thinking_depth,
                    target_document_id=target_document_id,
                )
            except httpx.ConnectError as exc:
                record_failure(store=store, job=job, settings=settings, error=exc)
                return True
            except Exception:  # noqa: BLE001 - any ambiguous external result must halt
                store.needs_attention(
                    job=job,
                    reason=(
                        "SuperDocs start failed after the external effect may have begun; "
                        "reconcile before retrying"
                    ),
                )
                return True
            store.save_started(
                job=job,
                session_id=started.session_id,
                superdocs_job_id=started.job_id,
                poll_after_seconds=settings.job_poll_interval_seconds,
            )
            return True

        if job.superdocs_session_id is None:
            store.needs_attention(job=job, reason="SuperDocs job has no persisted session ID")
            return True

        if job.external_wait_kind in {
            "submitting_decisions",
            "continuing_job",
            "exporting",
        }:
            store.needs_attention(
                job=job,
                reason=(
                    f"Worker lease expired during {job.external_wait_kind}; "
                    "reconcile SuperDocs state before retrying"
                ),
            )
            return True

        if (
            job.external_effect_started_at is not None
            and job.external_wait_kind is None
            and (datetime.now(UTC) - job.external_effect_started_at).total_seconds()
            > settings.job_timeout_seconds
        ):
            store.needs_attention(
                job=job,
                reason="SuperDocs job exceeded the configured polling deadline; reconcile status",
            )
            return True

        if job.external_wait_kind == "change_review":
            decisions = store.decision_payload(job)
            if not decisions:
                store.needs_attention(job=job, reason="Review resumed without decisions")
                return True
            store.mark_external_action(
                job=job,
                kind="submitting_decisions",
                delivery_state="approving",
            )
            try:
                await processor.submit_decisions(
                    session_id=job.superdocs_session_id,
                    job_id=job.superdocs_job_id,
                    decisions=decisions,
                )
            except Exception:  # noqa: BLE001 - fail closed after a mutating request
                store.needs_attention(
                    job=job,
                    reason=(
                        "Decision submission returned an ambiguous result; "
                        "reconcile SuperDocs state before retrying"
                    ),
                )
                return True
            store.requeue(
                job=job,
                poll_after_seconds=settings.job_poll_interval_seconds,
                clear_wait_kind=True,
            )
            return True

        try:
            snapshot = await processor.get_job(job.superdocs_job_id)
        except httpx.TimeoutException as exc:
            if job.retry_count < settings.worker_max_retries:
                store.retry(
                    job=job,
                    error=exc,
                    delay_seconds=retry_delay(
                        retry_count=job.retry_count,
                        base_seconds=settings.retry_base_seconds,
                        max_seconds=settings.retry_max_seconds,
                    ),
                )
            else:
                store.fail(job=job, error=exc)
            return True
        if snapshot.status in {"pending", "in_progress"}:
            store.requeue(job=job, poll_after_seconds=settings.job_poll_interval_seconds)
        elif snapshot.status == "awaiting_approval":
            if snapshot.awaiting_kind == "change_review":
                store.save_review(job=job, changes=snapshot.pending_changes)
            elif snapshot.awaiting_kind == "continue_prompt":
                store.mark_external_action(
                    job=job,
                    kind="continuing_job",
                    delivery_state="processing",
                )
                try:
                    await processor.continue_job(
                        session_id=job.superdocs_session_id,
                        job_id=job.superdocs_job_id,
                    )
                except Exception:  # noqa: BLE001 - fail closed after a mutating request
                    store.needs_attention(
                        job=job,
                        reason=(
                            "Continue request returned an ambiguous result; "
                            "reconcile SuperDocs state before retrying"
                        ),
                    )
                    return True
                store.requeue(
                    job=job,
                    poll_after_seconds=settings.job_poll_interval_seconds,
                    clear_wait_kind=True,
                )
            else:
                store.needs_attention(
                    job=job,
                    reason=f"Unknown SuperDocs awaiting kind: {snapshot.awaiting_kind}",
                )
        elif snapshot.status == "completed":
            route = Route.model_validate(job.route_config)
            store.mark_external_action(
                job=job,
                kind="exporting",
                delivery_state="exporting",
            )
            try:
                result = await processor.export(
                    event_id=str(job.delivery_id),
                    session_id=job.superdocs_session_id,
                    job_id=job.superdocs_job_id,
                    export_format=route.export.format,
                )
            except Exception:  # noqa: BLE001 - an export may have succeeded remotely
                store.needs_attention(
                    job=job,
                    reason=(
                        "Export request returned an ambiguous result; "
                        "reconcile SuperDocs state before retrying"
                    ),
                )
                return True
            store.complete(
                job=job,
                export_format=route.export.format,
                filename=result.filename,
                mime_type=result.content_type,
                content=result.content,
                max_artifact_bytes=settings.max_artifact_bytes,
                superdocs_session_id=result.session_id,
                superdocs_job_id=result.job_id,
            )
        elif snapshot.status in {"failed", "cancelled"}:
            store.fail(job=job, error=RuntimeError(f"SuperDocs job {snapshot.status}"))
        else:
            store.needs_attention(
                job=job,
                reason=f"Unknown SuperDocs job status: {snapshot.status}",
            )
    except LeaseLostError:
        return True
    except Exception as exc:  # noqa: BLE001 - outer worker boundary records safe failures
        record_failure(store=store, job=job, settings=settings, error=exc)
    return True


async def serve() -> None:
    settings = get_settings()
    migrate()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=settings.database_pool_max_size,
        open=False,
    )
    pool.open(wait=True)
    client = SuperDocsClient(settings)
    store = DeliveryStore(pool)
    try:
        while True:
            worked = await run_once(
                store=store,
                processor=client,
                settings=settings,
                worker_id=worker_id,
            )
            if not worked:
                await asyncio.sleep(settings.worker_poll_interval_seconds)
    finally:
        await client.close()
        pool.close()


if __name__ == "__main__":
    asyncio.run(serve())
