"""The SuperDocs operation ledger.

Every call the close pack makes to the SuperDocs adapter is recorded against the close
that caused it, in both mock and live mode, whether it succeeded or failed. The ledger
is what lets a reviewer confirm the app actually drives the contract

    upload_document -> send_edit_instruction -> approve_changes -> export_document

rather than merely claiming to. It is persisted with the close, surfaced by
`GET /closes/{id}/superdocs`, and shipped inside the exported pack.

Nothing secret is recorded. Entries hold operation names, document ids, change ids and
error text; the API key never reaches this module, and `redact` is applied to every
response envelope before it is stored.
"""

import asyncio
import time
from typing import Any, Awaitable, Callable

from ..db import store
from ..integrations.superdocs.client import CONTRACT_OPERATIONS, SuperDocsResponseError, current_mode
from .clock import now_iso
from .closes import new_id

# Response fields that are large or sensitive and must never be persisted verbatim.
_DROPPED_ENVELOPE_FIELDS = {"content_base64", "content", "api_key", "authorization", "token", "secret"}

# Belt and braces: if a key ever leaks into a response body, it must not reach the
# ledger, the manifest or the UI.
_REDACTED = "[redacted]"


def redact(envelope: Any) -> Any:
    """Strip bulk content and anything credential-shaped out of a SuperDocs response."""
    if isinstance(envelope, dict):
        cleaned: dict[str, Any] = {}
        for key, value in envelope.items():
            lowered = str(key).lower()
            if lowered in _DROPPED_ENVELOPE_FIELDS:
                cleaned[key] = _REDACTED if lowered != "content_base64" else f"{_REDACTED} (bytes stored separately)"
                continue
            cleaned[key] = redact(value)
        return cleaned
    if isinstance(envelope, list):
        return [redact(item) for item in envelope]
    return envelope


def _entry(
    operation: str,
    *,
    mode: str,
    status: str,
    started_at: str,
    duration_ms: int,
    document_id: str | None,
    change_ids: list[str] | None,
    request_id: str | None,
    detail: str,
    error: str | None,
) -> dict[str, Any]:
    return {
        "id": new_id("op"),
        "operation": operation,
        "mode": mode,
        "status": status,
        "document_id": document_id,
        "change_ids": change_ids or [],
        "request_id": request_id,
        "detail": detail,
        "error": error,
        "started_at": started_at,
        "completed_at": now_iso(),
        "duration_ms": duration_ms,
    }


def record(close: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Append to the ledger held on an already-loaded close (inside a mutator)."""
    close.setdefault("superdocs_operations", []).append(entry)
    return entry


def _persist(close_id: str, entry: dict[str, Any]) -> None:
    def mutator(close: dict[str, Any]) -> None:
        record(close, entry)

    try:
        store.mutate_close(close_id, mutator)
    except KeyError:
        # The close was deleted mid-flight; losing one ledger row is not worth failing
        # the caller's operation over.
        pass


async def call(
    close_id: str,
    operation: str,
    action: Callable[[], Awaitable[Any]],
    *,
    document_id: str | None = None,
    change_ids: list[str] | None = None,
    detail: str = "",
    persist: bool = True,
) -> Any:
    """Run one SuperDocs adapter call and record it, then re-raise any failure.

    `persist=False` is for callers that are already inside a `mutate_close` transaction
    and will append the returned entry themselves; a nested write would deadlock on the
    BEGIN IMMEDIATE held by the outer transaction.
    """
    mode = current_mode()
    started_at = now_iso()
    began = time.perf_counter()

    try:
        result = await action()
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        entry = _entry(
            operation,
            mode=mode,
            status="FAILED",
            started_at=started_at,
            duration_ms=int((time.perf_counter() - began) * 1000),
            document_id=document_id,
            change_ids=change_ids,
            request_id=None,
            detail=detail,
            error=str(exc) or exc.__class__.__name__,
        )
        if persist:
            await asyncio.to_thread(_persist, close_id, entry)
        raise SuperDocsCallFailed(operation, entry, exc) from exc

    envelope = result if isinstance(result, dict) else None
    entry = _entry(
        operation,
        mode=mode,
        status="SUCCEEDED",
        started_at=started_at,
        duration_ms=int((time.perf_counter() - began) * 1000),
        document_id=(envelope or {}).get("document_id") or document_id,
        change_ids=change_ids,
        request_id=(envelope or {}).get("request_id") or (envelope or {}).get("export_id"),
        detail=detail,
        error=None,
    )
    if persist:
        await asyncio.to_thread(_persist, close_id, entry)
    return result, entry


class SuperDocsCallFailed(SuperDocsResponseError):
    """A recorded SuperDocs failure, carrying the ledger entry it produced."""

    def __init__(self, operation: str, entry: dict[str, Any], cause: Exception) -> None:
        super().__init__(str(cause) or cause.__class__.__name__)
        self.operation = operation
        self.entry = entry
        self.cause = cause


def contract_coverage(close: dict[str, Any]) -> dict[str, Any]:
    """Which of the four contract operations this close has actually exercised."""
    operations = close.get("superdocs_operations") or []
    succeeded = {entry["operation"] for entry in operations if entry.get("status") == "SUCCEEDED"}
    return {
        "operations": [
            {
                "operation": name,
                "exercised": name in succeeded,
                "count": sum(1 for entry in operations if entry["operation"] == name),
                "failures": sum(
                    1 for entry in operations if entry["operation"] == name and entry.get("status") == "FAILED"
                ),
            }
            for name in CONTRACT_OPERATIONS
        ],
        "complete": all(name in succeeded for name in CONTRACT_OPERATIONS),
    }
