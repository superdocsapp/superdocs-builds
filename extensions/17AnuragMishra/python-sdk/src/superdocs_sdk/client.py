from __future__ import annotations

import mimetypes
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Self, cast

from .core import (
    approval_body,
    chat_body,
    export_body,
    mutation_headers,
    page_from_payload,
    parse_change_batch,
    progress_event,
)
from .errors import SuperDocsTimeoutError
from .models import (
    ApprovalDecision,
    ApprovalMode,
    ChatResult,
    DocumentDetail,
    DocumentExport,
    ExportFormat,
    Job,
    Page,
    ProgressEvent,
    ProposedChangeBatch,
    SavedDocument,
    Session,
    SessionHistory,
    UploadResult,
)
from .transport import (
    HttpxSyncTransport,
    SyncTransport,
    api_key_from_env,
    ensure_success,
    iter_sse_lines,
    request_with_retries,
    with_query,
)

SMALL_UPLOAD_LIMIT = 100_000


class SuperDocsClient:
    def __init__(
        self,
        *,
        api_key: str,
        transport: SyncTransport | None = None,
        timeout: float = 60.0,
        retries: int = 2,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.transport = transport or HttpxSyncTransport(api_key)
        self.timeout = timeout
        self.retries = retries
        self.idempotency_key_factory = idempotency_key_factory

    @classmethod
    def from_env(cls, **kwargs: Any) -> SuperDocsClient:
        return cls(api_key=api_key_from_env(), **kwargs)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return "SuperDocsClient(api_key='***')"

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close:
            close()

    def chat(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: ApprovalMode | None = None,
        timeout: float | None = None,
        idempotency_key: str | None = None,
        **extra: Any,
    ) -> ChatResult:
        body = chat_body(
            session_id=session_id,
            message=message,
            document_html=document_html,
            approval_mode=approval_mode,
            extra=extra,
        )
        return ChatResult.model_validate(
            self._json(
                "POST", "/v1/chat", body, timeout=timeout, idempotency_key=idempotency_key
            )
        )

    def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: ApprovalMode | None = None,
        timeout: float | None = None,
        idempotency_key: str | None = None,
        **extra: Any,
    ) -> Job:
        body = chat_body(
            session_id=session_id,
            message=message,
            document_html=document_html,
            approval_mode=approval_mode,
            extra=extra,
        )
        data = self._json(
            "POST", "/v1/chat/async", body, timeout=timeout, idempotency_key=idempotency_key
        )
        return Job.model_validate({"status": "queued", **data})

    def get_job(self, job_id: str, *, timeout: float | None = None) -> Job:
        return Job.model_validate(self._json("GET", f"/v1/jobs/{job_id}", None, timeout=timeout))

    def wait(
        self,
        job_id: str,
        *,
        poll_interval_s: float = 2.0,
        timeout_s: float = 300.0,
        request_timeout: float | None = None,
    ) -> Job:
        deadline = time.monotonic() + timeout_s
        while True:
            job = self.get_job(job_id, timeout=request_timeout)
            if job.is_terminal or job.needs_input:
                return job
            if time.monotonic() >= deadline:
                raise SuperDocsTimeoutError(
                    f"Timed out waiting for SuperDocs job {job_id}",
                    code="job_timeout",
                    suggested_action="Resume polling the same job_id; the server-side job may still be running.",
                )
            time.sleep(min(poll_interval_s, max(0.0, deadline - time.monotonic())))

    def progress(
        self, job_id: str, session_id: str, *, timeout: float | None = None
    ) -> Iterator[ProgressEvent]:
        path = with_query(f"/v1/chat/{session_id}/stream", job_id=job_id)
        for event in iter_sse_lines(
            self.transport.stream_lines(path, timeout=timeout or self.timeout)
        ):
            yield progress_event(event)

    @staticmethod
    def parse_change_batch(event: ProgressEvent) -> ProposedChangeBatch:
        return parse_change_batch(event)

    def approve_change(
        self,
        *,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: list[ApprovalDecision] | None = None,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._json(
                "POST",
                f"/v1/chat/{session_id}/approve",
                approval_body(job_id=job_id, approved=approved, changes=changes),
                timeout=timeout,
                idempotency_key=idempotency_key,
            ),
        )

    def create_session(
        self,
        *,
        timeout: float | None = None,
        idempotency_key: str | None = None,
        **metadata: Any,
    ) -> Session:
        return Session.model_validate(
            self._json(
                "POST",
                "/v1/sessions/init",
                metadata,
                timeout=timeout,
                idempotency_key=idempotency_key,
            )
        )

    def list_sessions(
        self, *, limit: int = 50, cursor: str | None = None, timeout: float | None = None
    ) -> Page[Session]:
        payload = self._json(
            "GET", with_query("/v1/sessions", limit=limit, cursor=cursor), None, timeout=timeout
        )
        return cast(Page[Session], page_from_payload(payload, Session))

    def iter_sessions(self, *, limit: int = 50, timeout: float | None = None) -> Iterator[Session]:
        cursor = None
        while True:
            page = self.list_sessions(limit=limit, cursor=cursor, timeout=timeout)
            yield from page.items
            cursor = page.next_cursor
            if not cursor:
                return

    def get_session_history(
        self,
        session_id: str,
        *,
        include_document_html: bool = True,
        timeout: float | None = None,
    ) -> SessionHistory:
        path = with_query(
            f"/v1/sessions/{session_id}/history",
            include_document_html=str(include_document_html).lower(),
        )
        return SessionHistory.model_validate(self._json("GET", path, None, timeout=timeout))

    def delete_session(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._json(
                "DELETE",
                f"/v1/sessions/{session_id}",
                None,
                timeout=timeout,
                idempotency_key=idempotency_key,
            ),
        )

    def list_documents(
        self, *, limit: int = 50, cursor: str | None = None, timeout: float | None = None
    ) -> Page[SavedDocument]:
        payload = self._json(
            "GET", with_query("/v1/documents", limit=limit, cursor=cursor), None, timeout=timeout
        )
        return cast(Page[SavedDocument], page_from_payload(payload, SavedDocument))

    def iter_documents(
        self, *, limit: int = 50, timeout: float | None = None
    ) -> Iterator[SavedDocument]:
        cursor = None
        while True:
            page = self.list_documents(limit=limit, cursor=cursor, timeout=timeout)
            yield from page.items
            cursor = page.next_cursor
            if not cursor:
                return

    def get_document(self, document_id: str, *, timeout: float | None = None) -> DocumentDetail:
        return DocumentDetail.model_validate(
            self._json("GET", f"/v1/documents/{document_id}", None, timeout=timeout)
        )

    def archive_document(
        self,
        document_id: str,
        *,
        force: bool = False,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._json(
                "DELETE",
                with_query(f"/v1/documents/{document_id}", force=str(force).lower()),
                None,
                timeout=timeout,
                idempotency_key=idempotency_key,
            ),
        )

    def restore_document(
        self,
        document_id: str,
        *,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> DocumentDetail:
        return DocumentDetail.model_validate(
            self._json(
                "POST",
                f"/v1/documents/{document_id}/restore",
                {},
                timeout=timeout,
                idempotency_key=idempotency_key,
            )
        )

    def upload_document(
        self,
        path: str | Path,
        *,
        session_id: str,
        return_html: bool = True,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> UploadResult:
        file_path = Path(path)
        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        call_timeout = timeout or self.timeout
        if len(content) <= SMALL_UPLOAD_LIMIT:
            response = request_with_retries(
                self.transport,
                "POST",
                "/v1/documents/upload",
                files={"file": (file_path.name, content, content_type)},
                data={"session_id": session_id},
                headers=mutation_headers(
                    "POST", idempotency_key, self.idempotency_key_factory
                ),
                timeout=call_timeout,
                retries=self.retries,
            )
            payload = response.json() or {}
            return UploadResult.model_validate({"filename": file_path.name, **payload})

        requested = self._json(
            "POST",
            "/v1/uploads",
            {
                "filename": file_path.name,
                "content_type": content_type,
                "size_bytes": len(content),
                "purpose": "document",
            },
            timeout=timeout,
            idempotency_key=idempotency_key,
        )
        upload_id = str(requested["upload_id"])
        upload_url = requested.get("upload_url") or requested.get("signed_url") or requested.get("url")
        if not upload_url:
            raise ValueError("SuperDocs upload response did not include upload_url.")
        put_headers = {"Content-Type": content_type, **requested.get("upload_headers", {})}
        ensure_success(
            self.transport.put_bytes(
                str(upload_url), content, headers=put_headers, timeout=call_timeout
            )
        )
        processed = self._json(
            "POST",
            f"/v1/uploads/{upload_id}/process",
            {
                "filename": file_path.name,
                "session_id": session_id,
                "parse_mode": "document",
                "return_html": return_html,
            },
            timeout=timeout,
            idempotency_key=idempotency_key,
        )
        return UploadResult.model_validate(
            {"filename": file_path.name, "upload_id": upload_id, **processed}
        )

    def export_document(
        self,
        *,
        session_id: str | None = None,
        html: str | None = None,
        upload_id: str | None = None,
        format: ExportFormat = "docx",
        filename: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> DocumentExport:
        payload = export_body(
            session_id=session_id,
            html=html,
            upload_id=upload_id,
            format=format,
            filename=filename,
            options=options,
        )
        response = request_with_retries(
            self.transport,
            "POST",
            "/v1/documents/export",
            json_body=payload,
            headers=mutation_headers("POST", idempotency_key, self.idempotency_key_factory),
            timeout=timeout or self.timeout,
            retries=self.retries,
        )
        return DocumentExport(
            content=response.body,
            content_type=response.headers.get("content-type"),
            warnings=response.headers.get("x-export-warnings"),
        )

    def _json(
        self,
        method: str,
        path: str,
        body: Any | None,
        *,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        response = request_with_retries(
            self.transport,
            method,
            path,
            json_body=body,
            headers=mutation_headers(method, idempotency_key, self.idempotency_key_factory),
            timeout=timeout or self.timeout,
            retries=self.retries,
        )
        return response.json()
