from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from .models import ApprovalDecision, ApprovalMode, Page, ProgressEvent, ProposedChangeBatch


def mutation_headers(
    method: str,
    supplied_key: str | None,
    key_factory: Callable[[], str] | None,
) -> dict[str, str]:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return {}
    key = supplied_key or (key_factory or (lambda: str(uuid.uuid4())))()
    return {"Idempotency-Key": key}


def chat_body(
    *,
    session_id: str,
    message: str,
    document_html: str | None,
    approval_mode: ApprovalMode | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {"session_id": session_id, "message": message, **extra}
    if document_html is not None:
        body["document_html"] = document_html
    if approval_mode is not None:
        body["approval_mode"] = approval_mode
    return body


def approval_body(
    *, job_id: str, approved: bool, changes: list[ApprovalDecision] | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"job_id": job_id, "approved": approved}
    if changes is not None:
        payload["changes"] = [change.model_dump(exclude_none=True) for change in changes]
    return payload


def export_body(
    *,
    session_id: str | None,
    html: str | None,
    upload_id: str | None,
    format: str,
    filename: str | None,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    supplied = sum(value is not None for value in (session_id, html, upload_id))
    if supplied != 1:
        raise ValueError("Exactly one of session_id, html, or upload_id is required.")
    payload: dict[str, Any] = {"format": format}
    if session_id is not None:
        payload["session_id"] = session_id
    if html is not None:
        payload["html"] = html
    if upload_id is not None:
        payload["upload_id"] = upload_id
    merged_options = dict(options or {})
    if filename is not None:
        merged_options["filename"] = filename
    if merged_options:
        payload["options"] = merged_options
    return payload


def page_from_payload(payload: Any, model: type[Any]) -> Page[Any]:
    if isinstance(payload, list):
        raw_items, cursor = payload, None
    elif isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("sessions") or payload.get("documents") or []
        cursor = payload.get("next_cursor") or payload.get("cursor")
    else:
        raw_items, cursor = [], None
    return Page[Any](items=[model.model_validate(item) for item in raw_items], next_cursor=cursor)


def progress_event(payload: dict[str, Any]) -> ProgressEvent:
    return ProgressEvent.model_validate({"raw": payload, **payload})


def parse_change_batch(event: ProgressEvent) -> ProposedChangeBatch:
    if event.type != "proposed_change_batch":
        raise ValueError(f"Expected proposed_change_batch, got {event.type}")
    payload = event.content
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ProposedChangeBatch.model_validate(payload)
