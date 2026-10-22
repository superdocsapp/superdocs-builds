from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .models import (
    OPEN_MODES,
    STATUS_AWAITING_APPROVAL,
    TERMINAL_STATUSES,
    ApprovalDecision,
    ExportResult,
    JobSnapshot,
    SessionDocument,
    SessionJobSummary,
    UploadResult,
)
from .transport import Transport


class JobTimeout(Exception):
    pass


class SuperDocsClient:
    def __init__(self, transport: Transport):
        self._t = transport

    async def upload_document(
        self,
        filename: str,
        file_bytes: bytes,
        session_id: str | None = None,
        return_html: bool = False,
        open_mode: str | None = None,
    ) -> UploadResult:
        if open_mode is not None and open_mode not in OPEN_MODES:
            raise ValueError(
                f"open_mode must be one of {sorted(OPEN_MODES)}, got {open_mode!r}; "
                "use 'background' to add a document without stealing focus"
            )
        payload: dict[str, Any] = {
            "filename": filename,
            "file_base64": base64.b64encode(file_bytes).decode("ascii"),
            "return_html": return_html,
        }
        if session_id is not None:
            payload["session_id"] = session_id
        if open_mode is not None:
            payload["open_mode"] = open_mode
        data = await self._t.post("/v1/documents/upload-base64", payload)
        result_session = data.get("session_id") or session_id
        if not result_session:
            raise ValueError("upload response did not include a session_id")
        return UploadResult(
            session_id=str(result_session),
            filename=filename,
            chunks_count=data.get("chunks_count"),
            version_id=data.get("version_id"),
            document_id=data.get("document_id"),
        )

    async def start_edit(
        self,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        document_id: str | None = None,
        cross_session_search: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }
        if model_tier:
            payload["model_tier"] = model_tier
        if document_id:
            payload["document_id"] = document_id
        if cross_session_search:
            payload["cross_session_search"] = True
        data = await self._t.post("/v1/chat/async", payload)
        job_id = data.get("job_id")
        if not job_id:
            raise ValueError(f"chat/async response missing job_id: {data}")
        return str(job_id)

    async def list_session_documents(self, session_id: str) -> list[SessionDocument]:
        data = await self._t.get(f"/v1/sessions/{session_id}/documents")
        items = data.get("documents", data if isinstance(data, list) else [])
        return [SessionDocument.from_api(item) for item in items]

    async def focus_document(self, session_id: str, document_id: str) -> dict[str, Any]:
        return await self._t.post(
            f"/v1/sessions/{session_id}/documents/{document_id}/focus", {}
        )

    async def get_job(self, job_id: str) -> JobSnapshot:
        data = await self._t.get(f"/v1/jobs/{job_id}")
        return JobSnapshot.from_api(job_id, data)

    async def submit_decisions(
        self, session_id: str, job_id: str, decisions: list[ApprovalDecision]
    ) -> dict[str, Any]:
        if not decisions:
            raise ValueError("submit_decisions requires at least one decision")
        top_level_approved = all(d.approved for d in decisions)
        payload: dict[str, Any] = {
            "job_id": job_id,
            "approved": top_level_approved,
            "changes": [
                d
                for d in (
                    {
                        "change_id": dec.change_id,
                        "approved": dec.approved,
                        **({"feedback": dec.feedback} if dec.feedback else {}),
                    }
                    for dec in decisions
                )
            ],
        }
        return await self._t.post(f"/v1/chat/{session_id}/approve", payload)

    async def continue_job(
        self, session_id: str, job_id: str, cont: bool = True
    ) -> dict[str, Any]:
        return await self._t.post(
            f"/v1/chat/{session_id}/continue",
            {"job_id": job_id, "continue": cont},
        )

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        return await self._t.post(f"/v1/jobs/{job_id}/cancel", {})

    async def list_session_jobs(self, session_id: str) -> list[SessionJobSummary]:
        data = await self._t.get(f"/v1/sessions/{session_id}/jobs")
        jobs = data.get("jobs", data if isinstance(data, list) else [])
        summaries = []
        for item in jobs:
            meta = item.get("metadata") or {}
            summaries.append(
                SessionJobSummary(
                    job_id=str(item["job_id"]),
                    status=item.get("status", ""),
                    awaiting_kind=meta.get("awaiting_kind"),
                )
            )
        return summaries

    async def export_document(
        self,
        session_id: str,
        fmt: str = "docx",
        filename: str | None = None,
    ) -> ExportResult:
        options: dict[str, Any] = {}
        if filename:
            options["filename"] = filename
        payload: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if options:
            payload["options"] = options
        data = await self._t.post("/v1/documents/export", payload)
        raw_bytes = data.get("content_bytes")
        return ExportResult(
            filename=data.get("filename") or (filename or "export") + f".{fmt}",
            fmt=data.get("format", fmt),
            content_b64=data.get("content_b64") or data.get("base64"),
            download_url=data.get("download_url"),
            raw={} if raw_bytes else data,
            content_raw=raw_bytes,
            warnings=data.get("warnings"),
        )


ProgressCallback = Callable[[float, JobSnapshot], Awaitable[None]]


async def wait_for_turnpoint(
    client: SuperDocsClient,
    job_id: str,
    *,
    interval_seconds: float = 2.0,
    max_wait_seconds: float = 900.0,
    warn_after_seconds: float = 60.0,
    on_progress: ProgressCallback | None = None,
) -> JobSnapshot:
    start = time.monotonic()
    last_warn = 0.0
    while True:
        snapshot = await client.get_job(job_id)
        if snapshot.status in TERMINAL_STATUSES:
            return snapshot
        if snapshot.status == STATUS_AWAITING_APPROVAL:
            return snapshot
        elapsed = time.monotonic() - start
        if elapsed > max_wait_seconds:
            raise JobTimeout(
                f"job {job_id} stuck in {snapshot.status!r} for {elapsed:.0f}s; "
                f"cancel it via cancel_job({job_id!r}) or raise max_wait_seconds"
            )
        stale_for = elapsed - last_warn
        if on_progress and elapsed > warn_after_seconds and stale_for >= warn_after_seconds:
            await on_progress(elapsed, snapshot)
            last_warn = elapsed
        await asyncio.sleep(interval_seconds)
