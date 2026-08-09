"""End-to-end orchestration shared by all agent-framework bindings."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable

from .client import SuperDocsClient
from .errors import JobFailedError, JobTimeoutError
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
                    f"Job {job_id} did not reach the expected state within {self.timeout:g}s"
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
    ) -> EditResult:
        session_id = session_id or f"adapter-{uuid.uuid4().hex}"
        upload = self.client.upload_document(file_path, session_id)
        job_id = self.client.start_edit(
            upload.session_id,
            instruction,
            model_tier=model_tier,
            thinking_depth=thinking_depth,
        )
        awaiting = self._wait_until(
            job_id,
            {JobStatus.AWAITING_APPROVAL, JobStatus.COMPLETED},
            on_progress,
        )

        approved_ids: tuple[str, ...] = ()
        if awaiting.status is JobStatus.AWAITING_APPROVAL:
            approved_ids = tuple(change.change_id for change in awaiting.proposed_changes)
            self.client.approve_changes(upload.session_id, awaiting, approved=True)
            completed = self._wait_until(job_id, {JobStatus.COMPLETED}, on_progress)
        else:
            completed = awaiting

        exported = self.client.export_document(
            upload.session_id,
            export_format=export_format,
            filename=output_filename,
        )
        return EditResult(
            session_id=upload.session_id,
            document_id=upload.document_id,
            job_id=job_id,
            approved_change_ids=approved_ids,
            export=exported,
            final_result=completed.result,
        )
