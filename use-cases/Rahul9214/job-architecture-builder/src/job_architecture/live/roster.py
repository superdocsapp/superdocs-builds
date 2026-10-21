"""Reconcile persisted live documents from an authoritative SuperDocs roster."""

from __future__ import annotations

from typing import Any

from job_architecture.live.state import LiveState
from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import DocumentRef, SessionRoster


def stable_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def reconcile_documents_from_roster(state: LiveState, roster: SessionRoster) -> None:
    """Copy durable ids from the session roster onto matching persisted documents.

    Matching is by document_id only. A known durable id is never replaced with
    null. Conflicting non-null durable ids fail instead of overwriting.
    """
    by_id = _roster_by_document_id(roster)
    for record in state.documents:
        document_id = stable_id(record.get("document_id"))
        if document_id is None:
            continue
        ref = by_id.get(document_id)
        if ref is None:
            continue
        _merge_durable_id(record, ref.durable_document_id)


def _roster_by_document_id(roster: SessionRoster) -> dict[str, DocumentRef]:
    by_id: dict[str, DocumentRef] = {}
    for item in roster.documents:
        document_id = stable_id(item.document_id)
        if document_id is None:
            continue
        previous = by_id.get(document_id)
        if previous is None:
            by_id[document_id] = item
            continue
        previous_durable = stable_id(previous.durable_document_id)
        incoming_durable = stable_id(item.durable_document_id)
        if previous_durable and incoming_durable and previous_durable != incoming_durable:
            raise SuperDocsError(
                "Session roster has conflicting durable_document_id values "
                f"for document_id={document_id}"
            )
        if incoming_durable and not previous_durable:
            by_id[document_id] = item
    return by_id


def _merge_durable_id(record: dict[str, Any], roster_durable: str | None) -> None:
    known = stable_id(record.get("durable_document_id"))
    incoming = stable_id(roster_durable)
    if known and incoming and known != incoming:
        raise SuperDocsError(
            "Conflicting durable_document_id for "
            f"document_id={record.get('document_id')}: persisted state and roster disagree"
        )
    if known:
        record["durable_document_id"] = known
        return
    record["durable_document_id"] = incoming
