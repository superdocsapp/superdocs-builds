from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import SecretStr

from app.config import Settings
from app.persistence import ClaimedJob
from app.superdocs import DocumentResult, JobSnapshot, StartedJob, SuperDocsHTTPError
from app.worker import record_failure, run_once

ROUTE_CONFIG = {
    "id": "incident-report",
    "enabled": True,
    "provider": "generic-hmac",
    "event_type": "incident.resolved",
    "payload_fields": ["type"],
    "workflow": {"mode": "generate"},
    "template": {"name": "incident-report", "required": True},
    "instruction": "Use the incident-report template.",
    "approval": {"mode": "manual", "policy": "ask_every_time"},
    "model": {"tier": "core", "thinking_depth": "balanced"},
    "export": {"format": "docx"},
}


class FakeStore:
    def __init__(self) -> None:
        self.job = ClaimedJob(
            job_id=uuid4(),
            delivery_id=uuid4(),
            external_delivery_id="evt_worker",
            input_data={"type": "incident.resolved"},
            attempt_count=1,
            superdocs_session_id=None,
            superdocs_job_id=None,
            external_wait_kind=None,
            retry_count=0,
            external_effect_started_at=None,
            recovered=False,
            leased_by="worker-test",
            route_config=ROUTE_CONFIG,
        )
        self.completed: dict[str, object] | None = None
        self.failed: Exception | None = None
        self.attention: str | None = None
        self.retried: tuple[Exception, float] | None = None
        self.clear_wait_kind: bool | None = None

    def claim(self, *, worker_id: str, lease_seconds: int) -> ClaimedJob | None:
        self.job = replace(self.job, leased_by=worker_id)
        return self.job

    def save_started(
        self,
        *,
        job: ClaimedJob,
        session_id: str,
        superdocs_job_id: str,
        poll_after_seconds: float,
    ) -> None:
        self.job = replace(
            job,
            superdocs_session_id=session_id,
            superdocs_job_id=superdocs_job_id,
        )

    def mark_starting(self, *, job: ClaimedJob) -> None:
        self.job = replace(job, external_effect_started_at=datetime.now(UTC))

    def mark_external_action(
        self, *, job: ClaimedJob, kind: str, delivery_state: str
    ) -> None:
        self.job = replace(job, external_wait_kind=kind)

    def requeue(
        self,
        *,
        job: ClaimedJob,
        poll_after_seconds: float,
        clear_wait_kind: bool = False,
    ) -> None:
        self.clear_wait_kind = clear_wait_kind
        self.job = replace(
            job,
            external_wait_kind=None if clear_wait_kind else job.external_wait_kind,
        )

    def complete(self, **kwargs: object) -> None:
        self.completed = kwargs

    def fail(self, *, job: ClaimedJob, error: Exception) -> None:
        self.failed = error

    def needs_attention(self, *, job: ClaimedJob, reason: str) -> None:
        self.attention = reason

    def retry(self, *, job: ClaimedJob, error: Exception, delay_seconds: float) -> None:
        self.retried = (error, delay_seconds)


class FakeProcessor:
    approval_mode: str | None = None
    instruction: str | None = None
    target_document_id: str | None = None

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
    ) -> StartedJob:
        self.approval_mode = approval_mode
        self.instruction = instruction
        self.target_document_id = target_document_id
        return StartedJob(session_id="session_1", job_id="superdocs_job_1")

    async def get_job(self, job_id: str) -> JobSnapshot:
        return JobSnapshot(status="completed")

    async def export(
        self,
        *,
        event_id: str,
        session_id: str,
        job_id: str,
        export_format: str | None = None,
    ) -> DocumentResult:
        return DocumentResult(
            session_id=session_id,
            job_id=job_id,
            filename="incident.docx",
            content=b"docx-bytes",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


class FailingExportProcessor(FakeProcessor):
    async def export(self, **kwargs: object) -> DocumentResult:
        raise SuperDocsHTTPError(status_code=503, path="/v1/documents/export")


class ContinueProcessor(FakeProcessor):
    continued = False

    async def get_job(self, job_id: str) -> JobSnapshot:
        return JobSnapshot(status="awaiting_approval", awaiting_kind="continue_prompt")

    async def continue_job(self, *, session_id: str, job_id: str) -> None:
        self.continued = True


async def test_run_once_persists_start_before_polling_and_export() -> None:
    store = FakeStore()
    processor = FakeProcessor()
    settings = Settings(
        superdocs_api_key=SecretStr("test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
    )

    started = await run_once(
        store=store,  # type: ignore[arg-type]
        processor=processor,  # type: ignore[arg-type]
        settings=settings,
        worker_id="worker-test",
    )
    assert started is True
    assert processor.approval_mode == "ask_every_time"
    assert 'template named "incident-report"' in (processor.instruction or "")
    assert store.job.superdocs_job_id == "superdocs_job_1"
    assert store.completed is None

    completed = await run_once(
        store=store,  # type: ignore[arg-type]
        processor=processor,  # type: ignore[arg-type]
        settings=settings,
        worker_id="worker-test",
    )
    assert completed is True
    assert store.failed is None
    assert store.completed is not None
    assert store.completed["content"] == b"docx-bytes"


async def test_recovered_ambiguous_start_requires_attention() -> None:
    store = FakeStore()
    store.job = replace(
        store.job,
        recovered=True,
        external_effect_started_at=datetime.now(UTC),
    )
    settings = Settings(
        superdocs_api_key=SecretStr("test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
    )

    worked = await run_once(
        store=store,  # type: ignore[arg-type]
        processor=FakeProcessor(),  # type: ignore[arg-type]
        settings=settings,
        worker_id="replacement-worker",
    )

    assert worked is True
    assert store.attention is not None
    assert "reconcile" in store.attention
    assert store.completed is None


async def test_ambiguous_export_failure_requires_attention_without_retry() -> None:
    store = FakeStore()
    store.job = replace(
        store.job,
        superdocs_session_id="session_1",
        superdocs_job_id="job_1",
    )
    settings = Settings(
        superdocs_api_key=SecretStr("test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
    )

    worked = await run_once(
        store=store,  # type: ignore[arg-type]
        processor=FailingExportProcessor(),  # type: ignore[arg-type]
        settings=settings,
        worker_id="worker-test",
    )

    assert worked is True
    assert store.attention is not None
    assert "reconcile" in store.attention
    assert store.retried is None
    assert store.completed is None


async def test_successful_continue_clears_external_action_marker() -> None:
    store = FakeStore()
    store.job = replace(
        store.job,
        superdocs_session_id="session_1",
        superdocs_job_id="job_1",
    )
    processor = ContinueProcessor()
    settings = Settings(
        superdocs_api_key=SecretStr("test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
    )

    worked = await run_once(
        store=store,  # type: ignore[arg-type]
        processor=processor,  # type: ignore[arg-type]
        settings=settings,
        worker_id="worker-test",
    )

    assert worked is True
    assert processor.continued is True
    assert store.clear_wait_kind is True
    assert store.job.external_wait_kind is None
    assert store.attention is None


def test_rate_limit_obeys_retry_after() -> None:
    store = FakeStore()
    settings = Settings(
        superdocs_api_key=SecretStr("test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
    )
    error = SuperDocsHTTPError(
        status_code=429,
        path="/v1/jobs/job_1",
        request_id="req_1",
        retry_after_seconds=7,
    )

    record_failure(store=store, job=store.job, settings=settings, error=error)  # type: ignore[arg-type]

    assert store.retried is not None
    assert store.retried[1] == 7


def test_conflict_requires_reconciliation() -> None:
    store = FakeStore()
    settings = Settings(
        superdocs_api_key=SecretStr("test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
    )
    error = SuperDocsHTTPError(
        status_code=409,
        path="/v1/chat/session/approve",
        request_id="req_2",
    )

    record_failure(store=store, job=store.job, settings=settings, error=error)  # type: ignore[arg-type]

    assert store.retried is None
    assert store.attention is not None
