"""Readable proposed-change display for the manual live CLI."""

from __future__ import annotations

import re

from job_architecture.superdocs.models import JobSnapshot, ProposedChange

_TAG = re.compile(r"<[^>]+>")


def plain_text(value: str | None, *, limit: int = 800) -> str:
    if not value:
        return "(empty)"
    text = " ".join(_TAG.sub(" ", value).split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def format_change(change: ProposedChange, *, document_name: str | None = None) -> str:
    name = document_name or change.document_id or "(unknown document)"
    return "\n".join(
        [
            f"change id:     {change.change_id}",
            f"document id:   {change.document_id or '(none)'}",
            f"document name: {name}",
            f"operation:     {change.operation}",
            f"before:        {plain_text(change.before)}",
            f"after:         {plain_text(change.after)}",
            f"reason:        {plain_text(change.reason)}",
        ]
    )


def format_pending(snapshot: JobSnapshot, *, document_name: str | None = None) -> str:
    header = (
        f"job {snapshot.job_id} status={snapshot.status} "
        f"awaiting_kind={snapshot.awaiting_kind or '-'} "
        f"proposed_changes={len(snapshot.pending_changes)}"
    )
    if snapshot.awaiting_kind == "continue_prompt":
        header += (
            "\nLarge-edit continue_prompt is waiting. "
            "Do not POST /approve. Use the continue command after review."
        )
    if not snapshot.pending_changes:
        return header + "\nNo proposed changes to display."
    blocks = [format_change(item, document_name=document_name) for item in snapshot.pending_changes]
    return header + "\n\n" + "\n\n".join(blocks)
