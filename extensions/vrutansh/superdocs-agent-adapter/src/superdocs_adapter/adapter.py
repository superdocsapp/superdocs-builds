"""End-to-end orchestration shared by all agent-framework bindings."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path

from .checkpoints import (
    CHECKPOINT_VERSION,
    FileCheckpointStore,
    RunCheckpoint,
    RunPhase,
    operation_fingerprint,
)
from .client import SuperDocsClient
from .errors import ConfigurationError, JobFailedError, JobTimeoutError
from .models import EditResult, ExportFormat, Job, JobStatus

ProgressCallback = Callable[[Job], None]


class SuperDocsAdapter:
    """Runs the minimum SuperDocs contract as one reusable operation."""

    def __init__(
        self,
        client: SuperDocsClient,
        *,
        poll_interval: float = 2.0,
        timeout: float = 600.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._sleep = sleep
        self._monotonic = monotonic

    def _wait_until(
        self,
        job_id: str,
        desired: set[JobStatus],
        on_progress: ProgressCallback | None,
    ) -> Job:
        started = self._monotonic()
        while True:
            job = self.client.get_job(job_id, compact=True)
            if on_progress:
                on_progress(job)
            if job.status in desired:
                return self.client.get_job(job_id, compact=False)
            if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                raise JobFailedError(job.error or f"Job ended with status {job.status.value}")
            if self._monotonic() - started >= self.timeout:
                raise JobTimeoutError(
                    f"Job {job_id} is still processing after {self.timeout:g}s; rerun with the "
                    "same checkpoint to resume instead of starting another edit"
                )
            self._sleep(self.poll_interval)

    def edit_and_export(
        self,
        file_path: str | Path,
        instruction: str,
        *,
        session_id: str | None = None,
        export_format: ExportFormat = ExportFormat.TXT,
        output_filename: str = "superdocs-output",
        model_tier: str = "core",
        thinking_depth: str = "balanced",
        on_progress: ProgressCallback | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> EditResult:
        fingerprint = operation_fingerprint(
            file_path, instruction, export_format, model_tier, thinking_depth
        )
        store = FileCheckpointStore(checkpoint_path) if checkpoint_path else None
        checkpoint = store.load() if store else None
        resumed = checkpoint is not None

        if checkpoint and checkpoint.fingerprint != fingerprint:
            raise ConfigurationError(
                "Checkpoint belongs to different inputs; use a different checkpoint path or "
                "restore the original document and instruction"
            )

        if checkpoint is None:
            requested_session = session_id or f"adapter-{uuid.uuid4().hex}"
            upload = self.client.upload_document(file_path, requested_session)
            checkpoint = RunCheckpoint(
                version=CHECKPOINT_VERSION,
                fingerprint=fingerprint,
                phase=RunPhase.UPLOADED,
                session_id=upload.session_id,
                document_id=upload.document_id,
            )
            if store:
                store.save(checkpoint)
        elif session_id and checkpoint.session_id != session_id:
            raise ConfigurationError(
                "Explicit session_id does not match the saved checkpoint session"
            )

        if checkpoint.job_id is None:
            # A crash can occur after SuperDocs accepts chat/async but before job_id is saved.
            # The session is unique to this operation, so its newest job is safe to adopt.
            existing_jobs = (
                self.client.list_session_jobs(checkpoint.session_id, limit=1) if resumed else ()
            )
            job_id = (
                existing_jobs[0].job_id
                if existing_jobs
                else self.client.start_edit(
                    checkpoint.session_id,
                    instruction,
                    model_tier=model_tier,
                    thinking_depth=thinking_depth,
                )
            )
            checkpoint = RunCheckpoint(
                version=checkpoint.version,
                fingerprint=checkpoint.fingerprint,
                phase=RunPhase.EDITING,
                session_id=checkpoint.session_id,
                document_id=checkpoint.document_id,
                job_id=job_id,
            )
            if store:
                store.save(checkpoint)
        else:
            job_id = checkpoint.job_id

        awaiting = self._wait_until(
            job_id,
            {JobStatus.AWAITING_APPROVAL, JobStatus.COMPLETED},
            on_progress,
        )

        approved_ids = checkpoint.approved_change_ids
        if awaiting.status is JobStatus.AWAITING_APPROVAL:
            current_ids = tuple(change.change_id for change in awaiting.proposed_changes)
            approved_ids = approved_ids or current_ids
            self.client.approve_changes(checkpoint.session_id, awaiting, approved=True)
            checkpoint = RunCheckpoint(
                version=checkpoint.version,
                fingerprint=checkpoint.fingerprint,
                phase=RunPhase.APPROVED,
                session_id=checkpoint.session_id,
                document_id=checkpoint.document_id,
                job_id=job_id,
                approved_change_ids=approved_ids,
            )
            if store:
                store.save(checkpoint)
            completed = self._wait_until(job_id, {JobStatus.COMPLETED}, on_progress)
        else:
            completed = awaiting

        checkpoint = RunCheckpoint(
            version=checkpoint.version,
            fingerprint=checkpoint.fingerprint,
            phase=RunPhase.COMPLETED,
            session_id=checkpoint.session_id,
            document_id=checkpoint.document_id,
            job_id=job_id,
            approved_change_ids=approved_ids,
        )
        if store:
            store.save(checkpoint)

        exported = self.client.export_document(
            checkpoint.session_id,
            export_format=export_format,
            filename=output_filename,
        )
        return EditResult(
            session_id=checkpoint.session_id,
            document_id=checkpoint.document_id,
            job_id=job_id,
            approved_change_ids=approved_ids,
            export=exported,
            final_result=completed.result,
            resumed=resumed,
        )
