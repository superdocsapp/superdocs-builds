"""Response parsing kept separate from HTTP and framework bindings."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import InvalidResponseError
from .models import Job, JobStatus, ProposedChange, UploadResult


def require_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidResponseError(f"Response field '{key}' must be a non-empty string")
    return value


def parse_json_encoded(value: Any) -> Any:
    """Perform the documented second parse only when content is JSON encoded."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in '[{"':
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _pending_changes(data: Mapping[str, Any]) -> tuple[ProposedChange, ...]:
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise InvalidResponseError("Job metadata must be an object")
    pending = metadata.get("pending_changes") or []
    pending = parse_json_encoded(pending)
    if not isinstance(pending, list):
        raise InvalidResponseError("metadata.pending_changes must be a list")

    changes: list[ProposedChange] = []
    for item in pending:
        item = parse_json_encoded(item)
        if not isinstance(item, Mapping):
            raise InvalidResponseError("Each proposed change must be an object")
        change_id = require_string(item, "change_id")
        content = item.get("content", item.get("proposed_content"))
        changes.append(
            ProposedChange(
                change_id=change_id,
                chunk_id=item.get("chunk_id") if isinstance(item.get("chunk_id"), str) else None,
                content=parse_json_encoded(content),
                raw=dict(item),
            )
        )
    return tuple(changes)


def parse_upload(data: Mapping[str, Any], requested_session_id: str) -> UploadResult:
    session_id = data.get("session_id", requested_session_id)
    if not isinstance(session_id, str) or not session_id:
        raise InvalidResponseError("Upload response did not contain a valid session_id")

    document_id = data.get("document_id") or data.get("focused_document_id")
    if document_id is not None and not isinstance(document_id, str):
        raise InvalidResponseError("Upload document_id must be a string")
    title = data.get("title")
    return UploadResult(
        session_id=session_id,
        document_id=document_id,
        title=title if isinstance(title, str) else None,
        raw=dict(data),
    )


def parse_job(data: Mapping[str, Any]) -> Job:
    try:
        status = JobStatus(require_string(data, "status"))
    except ValueError as exc:
        raise InvalidResponseError(f"Unknown job status: {data.get('status')!r}") from exc
    result = data.get("result")
    if result is not None and not isinstance(result, Mapping):
        raise InvalidResponseError("Job result must be an object")
    return Job(
        job_id=require_string(data, "job_id"),
        session_id=require_string(data, "session_id"),
        status=status,
        progress=int(data.get("progress", 0)),
        proposed_changes=_pending_changes(data),
        result=dict(result) if result is not None else None,
        error=data.get("error") if isinstance(data.get("error"), str) else None,
        raw=dict(data),
    )
