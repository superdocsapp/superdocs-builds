"""The shape of the in-Notion review queue: a database the page owner approves changes in.

The owner's source of truth is Notion, so the approval belongs there too — not in a separate app
they have to learn and log into. Each proposed change becomes a row carrying everything needed to
decide: who asked for it, the text before and after, whether SuperDocs' AI authored it, and any
link it would introduce. The owner sets **Status** to Approved or Rejected; the integration reads
those decisions and writes the approved ones onto the blocks, then records the outcome on the row.

These helpers build and read Notion's property payloads so the client stays a thin mapping and the
fake and the live service agree on one format.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from notion_review.domain import ChangeSource, ProposalStatus, ProposedChange

STATUS_PENDING = "Pending"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"

_KIND = {
    ChangeSource.TRACKED_CHANGE: "Reviewer edit",
    ChangeSource.COMMENT_INTENT: "AI-authored",
    ChangeSource.COMMENT: "Comment",
}
_PROP_LIMIT = 1900  # Notion caps a rich-text property value at 2000 characters


def queue_properties() -> dict[str, Any]:
    """The database schema: what a reviewer-change row looks like in Notion."""
    return {
        "Change": {"title": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": STATUS_PENDING, "color": "yellow"},
                    {"name": STATUS_APPROVED, "color": "green"},
                    {"name": STATUS_REJECTED, "color": "red"},
                ]
            }
        },
        "Reviewer": {"rich_text": {}},
        "Kind": {
            "select": {
                "options": [
                    {"name": "Reviewer edit", "color": "blue"},
                    {"name": "AI-authored", "color": "purple"},
                    {"name": "Comment", "color": "gray"},
                ]
            }
        },
        "Before": {"rich_text": {}},
        "After": {"rich_text": {}},
        "Notes": {"rich_text": {}},
        "Outcome": {"rich_text": {}},
    }


def changed_span(before: str, after: str) -> tuple[str, str]:
    """The part of a change that actually differs, with the shared context trimmed away.

    A reviewer usually edits a few words inside a long sentence. Showing the whole sentence twice
    makes a change unreadable at a glance — the eye has to diff it. This returns just the two sides
    that differ, so a row or a comment can say ``"operations teams" → "revenue operations teams"``.
    """
    if before == after:
        return "", ""
    shortest = min(len(before), len(after))
    head = 0
    while head < shortest and before[head] == after[head]:
        head += 1
    tail = 0
    while tail < shortest - head and before[-1 - tail] == after[-1 - tail]:
        tail += 1
    return before[head : len(before) - tail], after[head : len(after) - tail]


def summarize(before: str, after: str, *, width: int = 45) -> str:
    """A one-line, readable rendering of a change — an insertion, a deletion, or a replacement."""
    was, becomes = changed_span(before, after)
    if not was and not becomes:
        return before[:width]

    def show(value: str) -> str:
        value = value.strip()
        return value if len(value) <= width else value[: width - 1] + "…"

    if not was.strip():
        return f"add “{show(becomes)}”"
    if not becomes.strip():
        return f"remove “{show(was)}”"
    return f"“{show(was)}” → “{show(becomes)}”"


def _text(value: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": value[:_PROP_LIMIT]}}]}


def _title(value: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": value[:_PROP_LIMIT]}}]}


def _select(value: str) -> dict[str, Any]:
    return {"select": {"name": value}}


def competing_note(rivals: Sequence[str]) -> str:
    """Warn that other reviewers rewrote this same line, naming them.

    Several reviewers mark up their own copies, so two of them can change one line in different
    ways. Only one rewrite can land — whichever is applied first makes the block no longer read
    as it did when it went out, and the drift guard then refuses the others rather than
    overwriting a colleague's change. The owner should know that before deciding, not after.
    """
    if not rivals:
        return ""
    who = ", ".join(rivals)
    subject = "Another reviewer" if len(rivals) == 1 else f"{len(rivals)} other reviewers"
    return f"⚠ {subject} rewrote this line ({who}) — approve one; the rest are skipped as conflicts"


def _notes_for(proposal: ProposedChange, rivals: Sequence[str] = ()) -> str:
    """Everything the owner should read before deciding, in one line."""
    notes: list[str] = []
    if proposal.source == ChangeSource.COMMENT_INTENT and proposal.reviewer_comment:
        notes.append(f"Requested: {proposal.reviewer_comment}")
    if proposal.ai_explanation:
        notes.append(f"SuperDocs: {proposal.ai_explanation}")
    if proposal.source == ChangeSource.COMMENT and proposal.reviewer_comment:
        notes.append(proposal.reviewer_comment)
    if proposal.links:
        notes.append("⚠ links: " + ", ".join(proposal.links))
    contest = competing_note(rivals)
    if contest:
        notes.append(contest)
    return " · ".join(notes)


def row_properties(
    proposal: ProposedChange, *, before: str, after: str, rivals: Sequence[str] = ()
) -> dict[str, Any]:
    """One pending change, rendered as a row the owner can decide on at a glance."""
    # The title is what the owner scans in the table, so it shows the change itself, not the
    # whole sentence twice.
    summary = summarize(before, after) if after else (proposal.reviewer_comment or "Comment")
    return {
        "Change": _title(summary),
        "Status": _select(STATUS_PENDING),
        "Reviewer": _text(proposal.reviewer_name),
        "Kind": _select(_KIND.get(proposal.source, "Comment")),
        "Before": _text(before),
        "After": _text(after),
        "Notes": _text(_notes_for(proposal, rivals)),
    }


def notes_properties(proposal: ProposedChange, rivals: Sequence[str]) -> dict[str, Any]:
    """Just the Notes, for a row already published when a competing change turned up.

    Deliberately narrow: rewriting the whole row would reset **Status** and discard a decision
    the owner may already have made.
    """
    return {"Notes": _text(_notes_for(proposal, rivals))}


def outcome_properties(proposal: ProposedChange) -> dict[str, Any]:
    """What became of a decided change, written back onto its row."""
    outcome = {
        ProposalStatus.APPLIED: "✓ Applied to the page",
        ProposalStatus.REJECTED: "✗ Rejected — not applied",
        ProposalStatus.CONFLICT: "⚠ Skipped — the block changed since review",
        ProposalStatus.FAILED: "! Failed",
    }.get(proposal.status, proposal.status.value)
    if proposal.error:
        outcome = f"{outcome}: {proposal.error}"
    return {"Outcome": _text(outcome)}


def decision_from_status(status: str) -> bool | None:
    """Map a row's Status to a decision. ``None`` means the owner has not decided yet."""
    if status == STATUS_APPROVED:
        return True
    if status == STATUS_REJECTED:
        return False
    return None
