"""HTTP SuperDocs client. Domain code should depend on SuperDocsClientProtocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence
from urllib.parse import urljoin

import httpx

from job_architecture.superdocs.config import load_settings
from job_architecture.superdocs.errors import (
    AmbiguousOutcomeError,
    ApprovalError,
    AuthenticationError,
    ExportError,
    MalformedResponseError,
    RateLimitError,
    SuperDocsError,
    TransientHttpError,
)
from job_architecture.superdocs.models import (
    ApprovalResult,
    AsyncJobHandle,
    DocumentRef,
    DOCUMENTED_EXPORT_BODY_KEYS,
    ExportRequest,
    ExportResult,
    JobSnapshot,
    ReviewDecision,
    SavedDocument,
    SearchAccepted,
    SessionRoster,
    SuperDocsSettings,
    TemplateRef,
    UploadResult,
)
from job_architecture.superdocs.parsing import (
    decode_json_object,
    extract_pending_changes_from_job,
    map_job_status,
    redact_secrets,
)
from job_architecture.superdocs.polling import wait_for_job as poll_until

SAFE_GET_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class SuperDocsClient:
    """REST adapter for the SuperDocs surfaces this project needs.

    Retry policy (not exactly-once):
    - GET of job/document/roster: bounded retry on 429 and 5xx.
    - POST upload/edit/approve/export: no retry after timeout or ambiguous 5xx.
    - operation_key: if a prior call with the same key completed, return that result.
    """

    def __init__(
        self,
        settings: SuperDocsSettings,
        *,
        http: httpx.Client | None = None,
        max_get_retries: int = 2,
    ) -> None:
        self.settings = settings
        self._max_get_retries = max_get_retries
        timeout = httpx.Timeout(
            settings.timeout_seconds,
            connect=min(10.0, settings.timeout_seconds),
            read=settings.timeout_seconds,
        )
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=True)
        self._completed: dict[str, Any] = {}

    @classmethod
    def from_env(cls, **kwargs) -> SuperDocsClient:
        """Public constructor from environment settings. The live CLI loads settings explicitly."""
        return cls(load_settings(), **kwargs)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> SuperDocsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"SuperDocsClient(base_url={self.settings.base_url!r})"

    def _url(self, path: str) -> str:
        return urljoin(self.settings.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    def _cached(self, operation_key: str | None) -> Any | None:
        if operation_key and operation_key in self._completed:
            return self._completed[operation_key]
        return None

    def _store(self, operation_key: str | None, value: Any) -> Any:
        if operation_key:
            self._completed[operation_key] = value
        return value

    def _raise_http(self, response: httpx.Response, *, mutating: bool) -> None:
        status = response.status_code
        detail = _safe_detail(response, self.settings.api_key)
        if status in (401, 403):
            raise AuthenticationError(
                "SuperDocs rejected the API key or the caller is forbidden",
                status_code=status,
                cause=detail,
            )
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            seconds = None
            if retry_after:
                try:
                    seconds = float(retry_after)
                except ValueError:
                    seconds = None
            raise RateLimitError(
                "SuperDocs rate-limited the request",
                retry_after_seconds=seconds,
                status_code=status,
                cause=detail,
            )
        if status >= 500:
            raise TransientHttpError(
                "SuperDocs returned a server error",
                status_code=status,
                cause=detail,
            )
        if mutating and status >= 400:
            raise SuperDocsError(
                f"SuperDocs request failed with HTTP {status}",
                status_code=status,
                cause=detail,
            )
        raise SuperDocsError(
            f"SuperDocs request failed with HTTP {status}",
            status_code=status,
            cause=detail,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Any = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        mutating: bool | None = None,
    ) -> httpx.Response:
        is_mutating = method.upper() in MUTATING if mutating is None else mutating
        merged = dict(self._auth_headers())
        if headers:
            merged.update(headers)
        url = self._url(path)
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    method,
                    url,
                    json=json_body,
                    data=data,
                    files=files,
                    params=params,
                    headers=merged,
                )
            except httpx.TimeoutException as exc:
                if is_mutating:
                    raise AmbiguousOutcomeError(
                        "SuperDocs mutating request timed out; do not retry blindly. "
                        "Inspect jobs or document roster before sending again.",
                        cause=type(exc).__name__,
                    ) from exc
                if attempt >= self._max_get_retries:
                    raise TransientHttpError("SuperDocs GET timed out") from exc
                attempt += 1
                continue
            except httpx.HTTPError as exc:
                if is_mutating:
                    raise AmbiguousOutcomeError(
                        "SuperDocs mutating request failed in transit; do not retry blindly.",
                        cause=type(exc).__name__,
                    ) from exc
                if attempt >= self._max_get_retries:
                    raise TransientHttpError("SuperDocs GET failed in transit") from exc
                attempt += 1
                continue

            if response.status_code < 400:
                return response
            if (
                not is_mutating
                and response.status_code in SAFE_GET_RETRY_STATUSES
                and attempt < self._max_get_retries
            ):
                attempt += 1
                continue
            self._raise_http(response, mutating=is_mutating)

    def _read_json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise MalformedResponseError("SuperDocs returned non-JSON") from exc

    def upload_document(
        self,
        filename: str,
        content: bytes,
        *,
        session_id: str,
        open_mode: str = "new_focused",
        operation_key: str | None = None,
    ) -> UploadResult:
        cached = self._cached(operation_key)
        if isinstance(cached, UploadResult):
            return cached
        files = {"file": (filename, content)}
        data = {"session_id": session_id, "open_mode": open_mode}
        response = self._request("POST", "/v1/documents/upload", data=data, files=files)
        payload = self._read_json(response)
        roster = _roster_from_payload(session_id, payload)
        document = _uploaded_document(roster, payload, session_id)
        result = UploadResult(
            session_id=roster.session_id,
            document=document,
            roster=roster,
            filename=payload.get("filename") or filename,
            html=payload.get("html"),
            operation_key=operation_key,
        )
        return self._store(operation_key, result)

    def upload_template(
        self,
        filename: str,
        content: bytes,
        *,
        operation_key: str | None = None,
    ) -> TemplateRef:
        cached = self._cached(operation_key)
        if isinstance(cached, TemplateRef):
            return cached
        body = {
            "filename": filename,
            "file_base64": _b64(content),
        }
        response = self._request("POST", "/v1/templates/upload-base64", json_body=body)
        payload = self._read_json(response)
        template_id = (
            payload.get("template_id")
            or payload.get("id")
            or payload.get("document_id")
        )
        if not template_id:
            raise MalformedResponseError("Template upload response missing template_id")
        result = TemplateRef(
            template_id=str(template_id),
            name=payload.get("name") or payload.get("title"),
            filename=payload.get("filename") or filename,
        )
        return self._store(operation_key, result)

    def list_session_documents(self, session_id: str) -> SessionRoster:
        response = self._request("GET", f"/v1/sessions/{session_id}/documents")
        return _roster_from_payload(session_id, self._read_json(response))

    def list_saved_documents(self, *, limit: int = 50, offset: int = 0) -> tuple[SavedDocument, ...]:
        response = self._request(
            "GET",
            "/v1/documents",
            params={"limit": limit, "offset": offset},
        )
        payload = self._read_json(response)
        rows = payload.get("documents") if isinstance(payload, dict) else payload
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise MalformedResponseError("Saved-document list is not a list")
        documents: list[SavedDocument] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            doc_id = item.get("id") or item.get("document_id")
            if not doc_id:
                continue
            documents.append(
                SavedDocument(
                    document_id=str(doc_id),
                    title=item.get("title") or item.get("name"),
                    session_count=item.get("session_count"),
                    updated_at=item.get("updated_at"),
                    preview_html=item.get("preview_html"),
                )
            )
        return tuple(documents)

    def open_saved_documents(self, session_id: str, document_ids: Sequence[str]) -> SessionRoster:
        response = self._request(
            "POST",
            f"/v1/sessions/{session_id}/documents/open",
            json_body={"document_ids": list(document_ids)},
        )
        return _roster_from_payload(session_id, self._read_json(response))

    def start_reviewed_edit(
        self,
        session_id: str,
        message: str,
        *,
        document_id: str | None = None,
        document_html: str | None = None,
        operation_key: str | None = None,
    ) -> AsyncJobHandle:
        cached = self._cached(operation_key)
        if isinstance(cached, AsyncJobHandle):
            return cached
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
            "async_mode": True,
        }
        if document_id:
            body["document_id"] = document_id
        if document_html is not None:
            body["document_html"] = document_html
        response = self._request("POST", "/v1/chat/async", json_body=body)
        payload = self._read_json(response)
        handle = _handle_from_payload(payload, session_id, operation_key)
        return self._store(operation_key, handle)

    def get_job(self, job_id: str) -> JobSnapshot:
        response = self._request("GET", f"/v1/jobs/{job_id}")
        payload = self._read_json(response)
        if not isinstance(payload, dict):
            raise MalformedResponseError("Job response is not an object")
        raw_status = str(payload.get("status") or "pending")
        metadata = payload.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = decode_json_object(metadata, what="job metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        parsed = extract_pending_changes_from_job(payload)
        pending = parsed if parsed is not None else ()
        return JobSnapshot(
            job_id=str(payload.get("job_id") or job_id),
            session_id=str(payload.get("session_id") or ""),
            raw_status=raw_status,
            status=map_job_status(raw_status),
            progress=int(payload.get("progress") or 0),
            error=payload.get("error"),
            pending_changes=pending,
            awaiting_kind=metadata.get("awaiting_kind"),
            result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
            metadata=metadata,
            raw=payload,
        )

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float | None = None,
        max_wait_seconds: float | None = None,
        stop_on_review: bool = True,
        sleep=None,
        clock=None,
    ) -> JobSnapshot:
        return poll_until(
            lambda: self.get_job(job_id),
            poll_interval_seconds=poll_interval_seconds or self.settings.poll_interval_seconds,
            max_wait_seconds=max_wait_seconds or self.settings.poll_max_wait_seconds,
            stop_on_review=stop_on_review,
            sleep=sleep,
            clock=clock,
        )

    def submit_review(
        self,
        session_id: str,
        job_id: str,
        decisions: Sequence[ReviewDecision],
        *,
        operation_key: str | None = None,
    ) -> ApprovalResult:
        cached = self._cached(operation_key)
        if isinstance(cached, ApprovalResult):
            return cached
        if not decisions:
            raise ApprovalError("Review submission requires explicit per-change decisions")
        decided = tuple(decisions)
        if len(decided) == 1:
            body: dict[str, Any] = {
                "job_id": job_id,
                "change_id": decided[0].change_id,
                "approved": decided[0].approved,
            }
            if decided[0].feedback:
                body["feedback"] = decided[0].feedback
        else:
            # Top-level approved is required by SuperDocs even when every item
            # carries its own flag. It is the default only for items that omit
            # approved; we always send per-item approved and use all() so a
            # mixed batch cannot default-approve a missing flag.
            body = {
                "job_id": job_id,
                "approved": all(item.approved for item in decided),
                "changes": [
                    {
                        "change_id": item.change_id,
                        "approved": item.approved,
                        **({"feedback": item.feedback} if item.feedback else {}),
                    }
                    for item in decided
                ],
            }
        try:
            response = self._request("POST", f"/v1/chat/{session_id}/approve", json_body=body)
        except AmbiguousOutcomeError:
            raise
        except SuperDocsError as exc:
            raise ApprovalError(str(exc), status_code=exc.status_code, cause=exc.cause) from exc
        payload = self._read_json(response) if response.content else {}
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        result = ApprovalResult(
            job_id=job_id,
            session_id=session_id,
            decided=decided,
            raw=payload,
        )
        return self._store(operation_key, result)

    def continue_large_edit(
        self,
        session_id: str,
        job_id: str,
        *,
        resume: bool,
        operation_key: str | None = None,
    ) -> JobSnapshot:
        """Resume or stop a continue_prompt pause. This is not HITL change review."""
        cached = self._cached(operation_key)
        if isinstance(cached, JobSnapshot):
            return cached
        self._request(
            "POST",
            f"/v1/chat/{session_id}/continue",
            json_body={"job_id": job_id, "continue": resume},
        )
        snapshot = self.get_job(job_id)
        return self._store(operation_key, snapshot)

    def list_templates(self) -> tuple[TemplateRef, ...]:
        response = self._request("GET", "/v1/templates")
        payload = self._read_json(response)
        rows = payload.get("templates") if isinstance(payload, dict) else payload
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise MalformedResponseError("Template list is not a list")
        templates: list[TemplateRef] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            template_id = item.get("template_id") or item.get("id")
            if not template_id:
                continue
            templates.append(
                TemplateRef(
                    template_id=str(template_id),
                    name=item.get("name") or item.get("title"),
                    filename=item.get("filename"),
                )
            )
        return tuple(templates)

    def search_documents(
        self,
        query: str,
        *,
        session_id: str,
        document_id: str | None = None,
        cross_session: bool = True,
        operation_key: str | None = None,
    ) -> SearchAccepted:
        cached = self._cached(operation_key)
        if isinstance(cached, SearchAccepted):
            return cached
        body: dict[str, Any] = {
            "message": query,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
            "async_mode": True,
            "cross_session_search": cross_session,
        }
        if document_id:
            body["document_id"] = document_id
        response = self._request("POST", "/v1/chat/async", json_body=body)
        handle = _handle_from_payload(self._read_json(response), session_id, operation_key)
        accepted = SearchAccepted(handle=handle, query=query)
        return self._store(operation_key, accepted)

    def export_document(
        self,
        destination: Path | BinaryIO,
        request: ExportRequest,
        *,
        operation_key: str | None = None,
    ) -> ExportResult:
        cached = self._cached(operation_key)
        if isinstance(cached, ExportResult):
            return cached
        body = request.json_body()
        extra = set(body) - DOCUMENTED_EXPORT_BODY_KEYS
        if extra:
            raise ExportError(f"Refusing undocumented export fields: {sorted(extra)}")
        if "document_id" in body or "durable_document_id" in body:
            raise ExportError(
                "Export must not send document_id or durable_document_id; "
                "current SuperDocs docs do not support id targeting on export"
            )
        html = str(body.get("html") or "").strip()
        if not html:
            raise ExportError("Export HTML is empty; refusing SuperDocs call")
        if not body.get("session_id"):
            raise ExportError("Export requires session_id")
        url = self._url("/v1/documents/export")
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        try:
            with self._http.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code >= 400:
                    response.read()
                    try:
                        self._raise_http(response, mutating=True)
                    except SuperDocsError as exc:
                        raise ExportError(
                            str(exc),
                            status_code=exc.status_code,
                            cause=exc.cause,
                        ) from exc
                content_type = response.headers.get("content-type")
                media = (content_type or "").split(";")[0].strip().lower()
                if media == "application/json":
                    payload = response.read()
                    text = payload.decode("utf-8", errors="replace")[:500]
                    raise ExportError(
                        "Export returned JSON instead of a file; not treating as success",
                        cause=redact_secrets(text, self.settings.api_key),
                    )
                target_name = request.filename or f"export.{request.format}"
                received = 0
                if isinstance(destination, (str, Path)):
                    path = Path(destination)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            if chunk:
                                handle.write(chunk)
                                received += len(chunk)
                    dest_label = str(path)
                else:
                    for chunk in response.iter_bytes():
                        if chunk:
                            destination.write(chunk)
                            received += len(chunk)
                    dest_label = None
        except httpx.TimeoutException as exc:
            raise AmbiguousOutcomeError(
                "SuperDocs export timed out; do not retry blindly until the destination is checked.",
                operation_key=operation_key,
                cause=type(exc).__name__,
            ) from exc
        except httpx.HTTPError as exc:
            raise AmbiguousOutcomeError(
                "SuperDocs export failed in transit; do not retry blindly.",
                operation_key=operation_key,
                cause=type(exc).__name__,
            ) from exc
        if received <= 0:
            raise ExportError("Export returned no bytes; not treating as success")
        result = ExportResult(
            filename=target_name,
            content_type=content_type,
            byte_count=received,
            destination=dest_label,
            operation_key=operation_key,
        )
        return self._store(operation_key, result)


def _b64(content: bytes) -> str:
    import base64

    return base64.b64encode(content).decode("ascii")


def _safe_detail(response: httpx.Response, api_key: str) -> str | None:
    try:
        payload = response.json()
    except Exception:
        text = response.text[:300] if response.text else None
        return redact_secrets(text, api_key) if text else None
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    if detail is None:
        return None
    if isinstance(detail, (dict, list)):
        text = json.dumps(detail)[:500]
    else:
        text = str(detail)[:500]
    return redact_secrets(text, api_key)


def _handle_from_payload(payload: Any, session_id: str, operation_key: str | None) -> AsyncJobHandle:
    if not isinstance(payload, dict) or not payload.get("job_id"):
        raise MalformedResponseError("Async chat response missing job_id")
    raw_status = str(payload.get("status") or "pending")
    return AsyncJobHandle(
        job_id=str(payload["job_id"]),
        session_id=str(payload.get("session_id") or session_id),
        status=raw_status,
        normalized_status=map_job_status(raw_status),
        message=payload.get("message"),
        operation_key=operation_key,
    )


def _uploaded_document(roster: SessionRoster, payload: Mapping[str, Any], session_id: str) -> DocumentRef:
    target = payload.get("focused_document_id") or payload.get("document_id") or roster.focused_document_id
    if target:
        try:
            return roster.document(str(target))
        except KeyError:
            pass
    for item in roster.documents:
        if item.focused:
            return item
    if roster.documents:
        return roster.documents[-1]
    return _document_from_upload(payload, session_id)


def _document_from_upload(payload: Mapping[str, Any], session_id: str) -> DocumentRef:
    document_id = (
        payload.get("document_id")
        or payload.get("id")
        or payload.get("focused_document_id")
        or "doc_primary"
    )
    return DocumentRef(
        document_id=str(document_id),
        durable_document_id=_optional_id(payload.get("durable_document_id")),
        title=payload.get("title") or payload.get("filename"),
        focused=True,
        chunks_count=payload.get("chunks_count"),
        version_id=payload.get("version_id"),
        session_id=session_id,
    )


def _optional_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _roster_from_payload(session_id: str, payload: Any) -> SessionRoster:
    if not isinstance(payload, dict):
        raise MalformedResponseError("Document roster is not an object")
    rows = payload.get("documents")
    if rows is None and payload.get("document_id"):
        rows = [payload]
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise MalformedResponseError("Document roster documents field is not a list")
    documents: list[DocumentRef] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("document_id") or item.get("id")
        if not doc_id:
            continue
        documents.append(
            DocumentRef(
                document_id=str(doc_id),
                durable_document_id=_optional_id(item.get("durable_document_id")),
                title=item.get("title") or item.get("filename") or item.get("name"),
                focused=bool(item.get("focused")),
                chunks_count=item.get("chunks_count") or item.get("chunk_count"),
                version_id=item.get("version_id") or (str(item["version"]) if item.get("version") else None),
                session_id=session_id,
            )
        )
    focused = payload.get("focused_document_id")
    if not focused:
        for item in documents:
            if item.focused:
                focused = item.document_id
                break
    if not documents:
        documents.append(_document_from_upload(payload, session_id))
        focused = documents[0].document_id
    return SessionRoster(
        session_id=str(payload.get("session_id") or session_id),
        documents=tuple(documents),
        focused_document_id=str(focused) if focused else None,
    )
