import base64
import binascii
import hashlib
import json
import logging
import re
import time
from typing import Any, NoReturn, cast
from urllib.parse import quote

import httpx
from pydantic import JsonValue, SecretStr, ValidationError

from docrelay.domain.enums import ProposalOperation, SuperDocsJobStatus
from docrelay.integrations.superdocs.contracts import (
    ChangeReviewDecision,
    ContinueReceipt,
    ExportArtifact,
    FocusedDocument,
    IngestedDocument,
    JobReference,
    JobSnapshot,
    PendingChange,
    ReviewReceipt,
    SessionDocument,
    SessionDocumentIdentity,
)

SUPERDOCS_API_BASE = "https://api.superdocs.app/v1"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SESSION_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")
_SAFE_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ALLOWED_OPEN_MODES = frozenset({"replace", "new_focused", "background"})
_ALLOWED_MODEL_TIERS = frozenset({"core", "turbo", "pro", "max"})
_ALLOWED_THINKING_DEPTHS = frozenset({"fast", "balanced", "deep"})

logger = logging.getLogger(__name__)


class SuperDocsError(RuntimeError):
    """Safe integration error whose message never contains provider bodies or credentials."""


class SuperDocsInvalidResponse(SuperDocsError):
    pass


class SuperDocsRequestError(SuperDocsError):
    def __init__(
        self,
        safe_message: str,
        *,
        outcome_unknown: bool,
        status_code: int | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        timed_out: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.outcome_unknown = outcome_unknown
        self.status_code = status_code
        self.request_id = request_id
        self.retryable = retryable
        self.timed_out = timed_out


class SuperDocsHTTPClient:
    """Narrow production REST adapter for the live Gate 1 lifecycle."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        api_key: SecretStr,
        api_base: str = SUPERDOCS_API_BASE,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    async def upload_docx(
        self,
        *,
        docx_bytes: bytes,
        filename: str,
        session_id: str,
        open_mode: str = "replace",
    ) -> IngestedDocument:
        _require_session_id(session_id)
        if not docx_bytes:
            raise ValueError("DOCX upload bytes must not be empty")
        if not filename or filename != filename.strip() or "/" in filename or "\\" in filename:
            raise ValueError("filename must be a non-empty basename")
        if open_mode not in _ALLOWED_OPEN_MODES:
            raise ValueError("unsupported SuperDocs open_mode")
        response = await self._request(
            "POST",
            "/documents/upload",
            operation="documents.upload",
            outcome_sensitive=True,
            files={"file": (filename, docx_bytes, DOCX_MIME)},
            data={"session_id": session_id, "open_mode": open_mode},
        )
        payload = _json_object(response)
        returned_session = _required_string(payload, "session_id")
        if returned_session != session_id:
            raise SuperDocsInvalidResponse("SuperDocs upload returned an unexpected session")
        document_id = _required_string(payload, "document_id")
        version_id = _required_string(payload, "version_id")
        html = _required_string(payload, "html", allow_empty=True)
        chunks_count = _nonnegative_int(payload.get("chunks_count"), "chunks_count")
        return IngestedDocument(
            identity=SessionDocumentIdentity(
                session_id=session_id,
                session_document_id=document_id,
            ),
            upload_version_id=version_id,
            baseline_html_sha256=_sha256_bytes(html.encode("utf-8")),
            chunks_count=chunks_count,
            safe_evidence={
                "persisted": bool(payload.get("persisted", False)),
                "provider_request_id": _safe_request_id(response),
                "returned_filename_present": isinstance(payload.get("filename"), str),
            },
        )

    async def list_session_documents(
        self,
        session_id: str,
        *,
        include_html: bool = False,
    ) -> tuple[SessionDocument, ...]:
        _require_session_id(session_id)
        response = await self._request(
            "GET",
            f"/sessions/{quote(session_id, safe='')}/documents",
            operation="sessions.documents.list",
            params={"include_html": str(include_html).lower()},
        )
        payload: Any = _json_value(response)
        values = payload.get("documents") if isinstance(payload, dict) else payload
        if not isinstance(values, list):
            raise SuperDocsInvalidResponse("SuperDocs document roster was not a list")
        documents: list[SessionDocument] = []
        for value in values:
            if not isinstance(value, dict):
                raise SuperDocsInvalidResponse(
                    "SuperDocs document roster contained an invalid item"
                )
            document_id = _required_string(value, "document_id")
            durable_id = _optional_string(value.get("durable_document_id"))
            html = value.get("html")
            if html is not None and not isinstance(html, str):
                raise SuperDocsInvalidResponse("SuperDocs roster HTML had an invalid shape")
            chunks_value = value.get("chunks_count", value.get("sections_count"))
            chunks_count = (
                _nonnegative_int(chunks_value, "chunks_count") if chunks_value is not None else None
            )
            documents.append(
                SessionDocument(
                    identity=SessionDocumentIdentity(
                        session_id=session_id,
                        session_document_id=document_id,
                        durable_document_id=durable_id,
                    ),
                    title=_optional_string(value.get("title")),
                    focused=bool(value.get("focused", False)),
                    chunks_count=chunks_count,
                    version_id=_optional_string(value.get("version_id")),
                    html_sha256=(
                        _sha256_bytes(html.encode("utf-8")) if isinstance(html, str) else None
                    ),
                    safe_evidence={"provider_request_id": _safe_request_id(response)},
                )
            )
        return tuple(documents)

    async def start_edit(
        self,
        *,
        target: SessionDocumentIdentity,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> JobReference:
        if approval_mode != "ask_every_time":
            raise ValueError("production review runs require approval_mode=ask_every_time")
        return await self.start_edit_raw(
            session_id=target.session_id,
            document_id=target.session_document_id,
            instruction=instruction,
            model_tier=model_tier,
            thinking_depth=thinking_depth,
        )

    async def start_edit_raw(
        self,
        *,
        session_id: str,
        document_id: str,
        instruction: str,
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> JobReference:
        _require_session_id(session_id)
        if not document_id:
            raise ValueError("an explicit SuperDocs document target is required")
        if not instruction or not instruction.strip():
            raise ValueError("edit instruction must not be empty")
        if model_tier is not None and model_tier not in _ALLOWED_MODEL_TIERS:
            raise ValueError("unsupported SuperDocs model tier")
        if thinking_depth is not None and thinking_depth not in _ALLOWED_THINKING_DEPTHS:
            raise ValueError("unsupported SuperDocs thinking depth")
        payload: dict[str, JsonValue] = {
            "message": instruction,
            "session_id": session_id,
            "document_id": document_id,
            "approval_mode": "ask_every_time",
            "response_mode": "full",
        }
        if model_tier is not None:
            payload["model_tier"] = model_tier
        if thinking_depth is not None:
            payload["thinking_depth"] = thinking_depth
        response = await self._request(
            "POST",
            "/chat/async",
            operation="chat.async.start",
            outcome_sensitive=True,
            json=payload,
        )
        return _parse_job_reference(_json_object(response), expected_session_id=session_id)

    async def get_job(self, job_id: str) -> JobSnapshot:
        if not job_id:
            raise ValueError("job_id must not be empty")
        response = await self._request(
            "GET",
            f"/jobs/{quote(job_id, safe='')}",
            operation="jobs.get",
        )
        return _parse_job_snapshot(_json_object(response), request_id=_safe_request_id(response))

    async def recover_session_jobs(self, session_id: str) -> tuple[JobSnapshot, ...]:
        _require_session_id(session_id)
        response = await self._request(
            "GET",
            f"/sessions/{quote(session_id, safe='')}/jobs",
            operation="sessions.jobs.list",
            params={"limit": "20", "compact": "false"},
        )
        payload = _json_object(response)
        values = payload.get("jobs")
        if not isinstance(values, list):
            raise SuperDocsInvalidResponse("SuperDocs session jobs response was not a list")
        request_id = _safe_request_id(response)
        jobs = tuple(
            _parse_job_snapshot(_object(value, "job"), request_id=request_id) for value in values
        )
        if any(job.reference.session_id != session_id for job in jobs):
            raise SuperDocsInvalidResponse("SuperDocs returned a job from another session")
        return jobs

    async def submit_decisions(
        self,
        *,
        session_id: str,
        job_id: str,
        decisions: tuple[ChangeReviewDecision, ...],
    ) -> ReviewReceipt:
        _require_session_id(session_id)
        if not decisions:
            raise ValueError("at least one explicit review decision is required")
        change_ids = [decision.change_id for decision in decisions]
        if len(change_ids) != len(set(change_ids)):
            raise ValueError("review decisions contain duplicate change IDs")
        changes: list[dict[str, JsonValue]] = []
        for decision in decisions:
            item: dict[str, JsonValue] = {
                "change_id": decision.change_id,
                "approved": decision.approved,
            }
            if decision.feedback is not None:
                item["feedback"] = decision.feedback
            changes.append(item)
        response = await self._request(
            "POST",
            f"/chat/{quote(session_id, safe='')}/approve",
            operation="chat.review.submit",
            outcome_sensitive=True,
            json={"job_id": job_id, "approved": True, "changes": changes},
        )
        payload = _json_object(response)
        return ReviewReceipt(
            status=_required_string(payload, "status"),
            batch_complete=bool(payload.get("batch_complete", False)),
            safe_evidence={
                "provider_request_id": _safe_request_id(response),
                "message_present": isinstance(payload.get("message"), str),
            },
        )

    async def submit_continue(
        self,
        *,
        session_id: str,
        job_id: str,
        should_continue: bool,
    ) -> ContinueReceipt:
        _require_session_id(session_id)
        response = await self._request(
            "POST",
            f"/chat/{quote(session_id, safe='')}/continue",
            operation="chat.continue.submit",
            outcome_sensitive=True,
            json={"job_id": job_id, "continue": should_continue},
        )
        payload = _json_object(response)
        return ContinueReceipt(
            status=_required_string(payload, "status"),
            safe_evidence={"provider_request_id": _safe_request_id(response)},
        )

    async def focus_document(self, target: SessionDocumentIdentity) -> FocusedDocument:
        _require_session_id(target.session_id)
        response = await self._request(
            "POST",
            (
                f"/sessions/{quote(target.session_id, safe='')}/documents/"
                f"{quote(target.session_document_id, safe='')}/focus"
            ),
            operation="sessions.documents.focus",
            outcome_sensitive=True,
            params={"include_html": "false"},
        )
        payload = _json_object(response)
        nested = payload.get("document")
        if isinstance(nested, dict):
            payload = nested
        returned_id_value = payload.get("document_id", payload.get("focused_document_id"))
        if not isinstance(returned_id_value, str) or not returned_id_value:
            raise SuperDocsInvalidResponse("SuperDocs focus response omitted the target identity")
        returned_id = returned_id_value
        if returned_id != target.session_document_id:
            raise SuperDocsInvalidResponse("SuperDocs focused an unexpected document")
        durable_id = _optional_string(payload.get("durable_document_id"))
        if (
            target.durable_document_id is not None
            and durable_id is not None
            and durable_id != target.durable_document_id
        ):
            raise SuperDocsInvalidResponse(
                "SuperDocs focus returned an unexpected durable identity"
            )
        return FocusedDocument(
            identity=SessionDocumentIdentity(
                session_id=target.session_id,
                session_document_id=target.session_document_id,
                durable_document_id=durable_id or target.durable_document_id,
            ),
            focused=bool(payload.get("focused", True)),
            version_id=_optional_string(payload.get("version_id")),
            safe_evidence={"provider_request_id": _safe_request_id(response)},
        )

    async def export_docx(
        self,
        *,
        target: SessionDocumentIdentity,
        filename: str,
    ) -> ExportArtifact:
        _require_session_id(target.session_id)
        response = await self._request(
            "POST",
            "/documents/export",
            operation="documents.export",
            outcome_sensitive=False,
            json={
                "session_id": target.session_id,
                "format": "docx",
                "options": {"filename": filename, "fidelity": "strict"},
            },
        )
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != DOCX_MIME or not response.content:
            raise SuperDocsInvalidResponse("SuperDocs export did not return a non-empty DOCX")
        warnings_raw = response.headers.get("X-Export-Warnings")
        warnings = _decode_export_warnings(warnings_raw)
        content = response.content
        return ExportArtifact(
            docx_bytes=content,
            sha256=_sha256_bytes(content),
            size_bytes=len(content),
            content_type=content_type,
            content_disposition=response.headers.get("Content-Disposition"),
            warnings_raw=warnings_raw,
            warnings=warnings,
            safe_evidence={"provider_request_id": _safe_request_id(response)},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        outcome_sensitive: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        started = time.monotonic()
        outcome = "succeeded"
        response: httpx.Response | None = None
        try:
            response = await self._http.request(
                method,
                f"{self._api_base}{path}",
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                **kwargs,
            )
            if not response.is_success:
                outcome = f"http_{response.status_code}"
                self._raise_response_error(response, outcome_sensitive=outcome_sensitive)
            return response
        except httpx.TimeoutException as exc:
            outcome = "timeout"
            raise SuperDocsRequestError(
                "SuperDocs request timed out",
                outcome_unknown=outcome_sensitive,
                retryable=not outcome_sensitive,
                timed_out=True,
            ) from exc
        except httpx.HTTPError as exc:
            outcome = "transport_error"
            raise SuperDocsRequestError(
                "SuperDocs is unavailable",
                outcome_unknown=outcome_sensitive,
                retryable=not outcome_sensitive,
            ) from exc
        finally:
            logger.info(
                "superdocs_operation",
                extra={
                    "safe_metadata": {
                        "operation": operation,
                        "method": method,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                        "outcome": outcome,
                        "provider_request_id": (
                            _safe_request_id(response) if response is not None else None
                        ),
                    }
                },
            )

    @staticmethod
    def _raise_response_error(response: httpx.Response, *, outcome_sensitive: bool) -> NoReturn:
        status = response.status_code
        request_id = _safe_request_id(response)
        if status in {401, 403}:
            message = "SuperDocs rejected the configured server credential"
        elif status == 404:
            message = "SuperDocs resource was not found"
        elif status == 409:
            message = "SuperDocs rejected the operation for the current job state"
        elif status == 429:
            message = "SuperDocs rate limit was reached"
        elif status >= 500:
            message = "SuperDocs is unavailable"
        else:
            message = "SuperDocs rejected the request"
        raise SuperDocsRequestError(
            message,
            outcome_unknown=outcome_sensitive and status >= 500,
            status_code=status,
            request_id=request_id,
            retryable=status == 429 or status >= 500,
        )


def _parse_job_reference(
    payload: dict[str, Any], *, expected_session_id: str | None = None
) -> JobReference:
    try:
        reference = JobReference(
            job_id=_required_string(payload, "job_id"),
            session_id=_required_string(payload, "session_id"),
            status=SuperDocsJobStatus(_required_string(payload, "status")),
        )
    except (ValueError, ValidationError) as exc:
        raise SuperDocsInvalidResponse("SuperDocs returned an unknown job state") from exc
    if expected_session_id is not None and reference.session_id != expected_session_id:
        raise SuperDocsInvalidResponse("SuperDocs returned a job from another session")
    return reference


def _parse_job_snapshot(payload: dict[str, Any], *, request_id: str | None) -> JobSnapshot:
    reference = _parse_job_reference(payload)
    metadata_value = payload.get("metadata")
    if metadata_value is None:
        metadata: dict[str, Any] = {}
    elif isinstance(metadata_value, dict):
        metadata = metadata_value
    else:
        raise SuperDocsInvalidResponse("SuperDocs job metadata had an invalid shape")
    awaiting_kind = _optional_string(metadata.get("awaiting_kind"))
    pending_value = metadata.get("pending_changes", [])
    if pending_value is None:
        pending_value = []
    if not isinstance(pending_value, list):
        raise SuperDocsInvalidResponse("SuperDocs pending_changes was not a list")
    pending = tuple(_parse_pending_change(value) for value in pending_value)
    decided_value = metadata.get("pending_batch_decisions", {})
    if not isinstance(decided_value, dict):
        raise SuperDocsInvalidResponse("SuperDocs pending_batch_decisions was not an object")
    pending_batch_decisions = cast(dict[str, JsonValue], decided_value)

    result_value = payload.get("result")
    result = result_value if isinstance(result_value, dict) else {}
    document_changes_value = result.get("document_changes")
    document_changes = document_changes_value if isinstance(document_changes_value, dict) else {}
    updated_html = document_changes.get("updated_html")
    if updated_html is not None and not isinstance(updated_html, str):
        raise SuperDocsInvalidResponse("SuperDocs final HTML had an invalid shape")
    final_version_id = _optional_string(
        document_changes.get("version_id", result.get("version_id"))
    )
    statuses: dict[str, str] = {}
    final_changes = document_changes.get("changes", [])
    if final_changes is not None:
        if not isinstance(final_changes, list):
            raise SuperDocsInvalidResponse("SuperDocs final change history had an invalid shape")
        for item in final_changes:
            if not isinstance(item, dict):
                continue
            change_id = item.get("change_id")
            status = item.get("status")
            if isinstance(change_id, str) and change_id and isinstance(status, str) and status:
                statuses[change_id] = status
    usage_value = result.get("usage", {})
    usage = _safe_scalar_object(usage_value)
    progress_value = payload.get("progress")
    progress = _nonnegative_int(progress_value, "progress") if progress_value is not None else None
    if progress is not None and progress > 100:
        raise SuperDocsInvalidResponse("SuperDocs job progress exceeded 100")
    error_value = payload.get("error")
    error_code = None
    if isinstance(error_value, dict):
        error_code = _optional_string(error_value.get("code", error_value.get("type")))
    safe_metadata: dict[str, JsonValue] = {
        "provider_request_id": request_id,
        "job_type": _optional_string(payload.get("job_type")),
        "created_at": _optional_string(payload.get("created_at")),
        "updated_at": _optional_string(payload.get("updated_at")),
        "pending_change_count": len(pending),
    }
    cumulative_tokens = metadata.get("cumulative_tokens")
    if isinstance(cumulative_tokens, int) and not isinstance(cumulative_tokens, bool):
        safe_metadata["cumulative_tokens"] = cumulative_tokens
    return JobSnapshot(
        reference=reference,
        progress=progress,
        awaiting_kind=awaiting_kind,
        pending_changes=pending,
        pending_batch_decisions=pending_batch_decisions,
        final_version_id=final_version_id,
        updated_html_sha256=(
            _sha256_bytes(updated_html.encode("utf-8")) if isinstance(updated_html, str) else None
        ),
        final_change_statuses=statuses,
        usage=usage,
        error_code=error_code,
        safe_metadata=safe_metadata,
    )


def _parse_pending_change(value: Any) -> PendingChange:
    payload = _object(value, "pending change")
    try:
        operation = ProposalOperation(_required_string(payload, "operation"))
        return PendingChange(
            change_id=_required_string(payload, "change_id"),
            operation=operation,
            document_id=_required_string(payload, "document_id"),
            chunk_id=_optional_string(payload.get("chunk_id")),
            old_html=_optional_string(payload.get("old_html"), allow_empty=True),
            new_html=_optional_string(payload.get("new_html"), allow_empty=True),
            ai_explanation=_optional_string(payload.get("ai_explanation"), allow_empty=True),
            insert_after_chunk_id=_optional_string(payload.get("insert_after_chunk_id")),
            safe_evidence={
                key: cast(JsonValue, payload[key])
                for key in ("batch_id", "batch_total")
                if isinstance(payload.get(key), (str, int, float, bool))
            },
        )
    except (ValueError, ValidationError) as exc:
        raise SuperDocsInvalidResponse("SuperDocs pending change had an invalid shape") from exc


def _decode_export_warnings(raw: str | None) -> tuple[dict[str, JsonValue], ...]:
    if raw is None or raw == "":
        return ()
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise SuperDocsInvalidResponse("SuperDocs export warnings could not be decoded") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise SuperDocsInvalidResponse("SuperDocs export warnings had an invalid shape")
    return tuple(cast(dict[str, JsonValue], item) for item in payload)


def _json_value(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise SuperDocsInvalidResponse("SuperDocs returned invalid JSON") from exc


def _json_object(response: httpx.Response) -> dict[str, Any]:
    payload = _json_value(response)
    if not isinstance(payload, dict):
        raise SuperDocsInvalidResponse("SuperDocs returned an invalid response shape")
    return payload


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SuperDocsInvalidResponse(f"SuperDocs {label} had an invalid shape")
    return value


def _required_string(payload: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise SuperDocsInvalidResponse(f"SuperDocs response omitted required {key}")
    return value


def _optional_string(value: Any, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or (not allow_empty and not value):
        raise SuperDocsInvalidResponse("SuperDocs response contained an invalid string field")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SuperDocsInvalidResponse(f"SuperDocs {label} was not a non-negative integer")
    return value


def _safe_scalar_object(value: Any) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): cast(JsonValue, item)
        for key, item in value.items()
        if isinstance(item, (str, int, float, bool)) or item is None
    }


def _safe_request_id(response: httpx.Response | None) -> str | None:
    if response is None:
        return None
    value = cast(
        str | None,
        response.headers.get("X-Request-ID") or response.headers.get("Request-ID"),
    )
    if value is None or _SAFE_REQUEST_ID_PATTERN.fullmatch(value) is None:
        return None
    return value


def _require_session_id(session_id: str) -> None:
    if len(session_id) > 256 or _SESSION_PATTERN.fullmatch(session_id) is None:
        raise ValueError("session_id is not valid for SuperDocs")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
