"""Parsers for SuperDocs payloads, including the double-encoded proposed-change trap."""

from __future__ import annotations

import json
from typing import Any, Mapping

from job_architecture.superdocs.errors import MalformedResponseError, ProposedChangeParseError
from job_architecture.superdocs.models import ProposedChange

_SECRET_HEADER_NAMES = frozenset({"authorization", "cookie", "set-cookie", "x-api-key"})


def redact_secrets(value: str, secret: str | None) -> str:
    if not value:
        return value
    redacted = value
    if secret:
        redacted = redacted.replace(secret, "[redacted]")
        if len(secret) > 8:
            redacted = redacted.replace(secret[:8], "[redacted]")
    return redacted


def header_safe_for_log(name: str, value: str) -> str:
    if name.lower() in _SECRET_HEADER_NAMES:
        return "[redacted]"
    return value


def decode_json_object(payload: Any, *, what: str) -> Any:
    if isinstance(payload, (dict, list)):
        return payload
    if payload is None:
        raise MalformedResponseError(f"{what} is missing")
    if not isinstance(payload, str):
        raise MalformedResponseError(f"{what} has unexpected type {type(payload).__name__}")
    text = payload.strip()
    if not text:
        raise MalformedResponseError(f"{what} is an empty string")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedResponseError(f"{what} is not valid JSON") from exc


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _change_from_mapping(item: Mapping[str, Any]) -> ProposedChange:
    change_id = item.get("change_id") or item.get("id")
    operation = item.get("operation")
    if not change_id or not operation:
        raise ProposedChangeParseError(
            "Proposed change is missing required identifier or operation"
        )
    return ProposedChange(
        change_id=str(change_id),
        operation=str(operation),
        chunk_id=_as_optional_str(item.get("chunk_id")),
        document_id=_as_optional_str(item.get("document_id")),
        old_html=_as_optional_str(item.get("old_html")),
        new_html=_as_optional_str(item.get("new_html")),
        reason=_as_optional_str(item.get("ai_explanation") or item.get("reason") or item.get("explanation")),
        raw=dict(item),
    )


def parse_pending_changes(raw: Any) -> tuple[ProposedChange, ...]:
    """Parse proposed changes from a job metadata field.

    Handles:
    - already-decoded list/dict
    - JSON-encoded string (including a second nested JSON string)
    - explicit empty list
    - malformed JSON / missing required fields as errors, never a fake empty list
    """
    if raw is None:
        raise ProposedChangeParseError("Proposed-change payload is missing")

    payload: Any = raw
    # SuperDocs SSE and some job metadata fields wrap content as a JSON string.
    for _ in range(2):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ProposedChangeParseError(
                    "Proposed-change payload is a JSON-encoded string that does not parse"
                ) from exc
        else:
            break

    if isinstance(payload, dict):
        if "changes" in payload:
            payload = payload["changes"]
        elif "pending_changes" in payload:
            payload = payload["pending_changes"]
        elif "change_id" in payload or "operation" in payload:
            payload = [payload]
        else:
            raise ProposedChangeParseError(
                "Proposed-change object has no changes list or change identifier"
            )

    if not isinstance(payload, list):
        raise ProposedChangeParseError(
            f"Proposed-change payload must be a list, got {type(payload).__name__}"
        )

    parsed: list[ProposedChange] = []
    for index, item in enumerate(payload):
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError as exc:
                raise ProposedChangeParseError(
                    f"Proposed change at index {index} is malformed JSON"
                ) from exc
        if not isinstance(item, Mapping):
            raise ProposedChangeParseError(f"Proposed change at index {index} is not an object")
        parsed.append(_change_from_mapping(item))
    return tuple(parsed)


def extract_pending_changes_from_job(job: Mapping[str, Any]) -> tuple[ProposedChange, ...] | None:
    """Return parsed changes, None if the job is not a HITL review pause.

    Distinguishes continue_prompt (no pending changes) from a missing/malformed
    HITL payload (error).
    """
    metadata = job.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = decode_json_object(metadata, what="job metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    awaiting_kind = metadata.get("awaiting_kind")
    if awaiting_kind == "continue_prompt":
        return None
    if job.get("status") != "awaiting_approval":
        raw = metadata.get("pending_changes")
        if raw in (None, []):
            nested = (job.get("result") or {}).get("document_changes") or {}
            if isinstance(nested, Mapping):
                raw = nested.get("pending_changes")
        if raw in (None, []):
            return tuple()
        return parse_pending_changes(raw)

    raw = metadata.get("pending_changes")
    if raw is None:
        nested = (job.get("result") or {}).get("document_changes") or {}
        if isinstance(nested, Mapping):
            raw = nested.get("pending_changes")
    if raw is None:
        raise ProposedChangeParseError(
            "Job is awaiting_approval for change review but pending_changes is missing"
        )
    return parse_pending_changes(raw)


def map_job_status(raw: str | None) -> str:
    """Map SuperDocs job status onto the application's polling vocabulary."""
    if not raw:
        return "queued"
    value = raw.strip().lower()
    mapping = {
        "pending": "queued",
        "queued": "queued",
        "in_progress": "processing",
        "processing": "processing",
        "awaiting_approval": "awaiting_approval",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    return mapping.get(value, value)
