from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass

from .boundary import AUDIENCE_INTERNAL, AUDIENCE_SHARED
from .store import Store

KIND_DOCUMENT = "document"
KIND_PROPOSAL = "proposal"
KIND_DECISION = "decision"
KIND_INTERNAL_NOTE = "internal_note"

SNIPPET_RADIUS = 60


@dataclass(frozen=True)
class SearchHit:
    kind: str
    label: str
    snippet: str
    audience: str
    proposal_id: str | None = None
    document_filename: str | None = None


def _plain(html_text: str | None) -> str:
    if not html_text:
        return ""
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", html_text)).strip()


def _snippet(haystack: str, needle: str) -> str:
    lowered = haystack.lower()
    index = lowered.find(needle.lower())
    if index == -1:
        return haystack[: SNIPPET_RADIUS * 2].strip()
    start = max(0, index - SNIPPET_RADIUS)
    end = min(len(haystack), index + len(needle) + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(haystack) else ""
    return f"{prefix}{haystack[start:end].strip()}{suffix}"


def _matches(haystack: str, query: str) -> bool:
    return query.lower() in (haystack or "").lower()


def search_deal(
    store: Store,
    deal_id: str,
    query: str,
    *,
    requester_audience: str,
    requester_side: str | None = None,
    document_text_by_filename: dict[str, str] | None = None,
    limit: int = 10,
) -> list[SearchHit]:
    """Search one deal's corpus, filtered by who is asking and from where.

    The audience rule is the same one that governs every other outbound path: a search
    issued from the shared channel may only ever surface shared material. Internal notes
    are searchable *only* from an internal channel, and then only the requesting side's
    own notes -- one side can never search the other side's internal commentary.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("search query is empty; try `/redline search <deal_id> liability`")

    hits: list[SearchHit] = []

    for document in store.documents_for_deal(deal_id):
        text = (document_text_by_filename or {}).get(document.filename, "")
        if text and _matches(text, query):
            hits.append(
                SearchHit(
                    kind=KIND_DOCUMENT,
                    label=f"{document.filename} ({document.role})",
                    snippet=_snippet(text, query),
                    audience=AUDIENCE_SHARED,
                    document_filename=document.filename,
                )
            )

    for proposal in store.proposals_for_deal(deal_id):
        haystack = " ".join(
            filter(
                None,
                [
                    _plain(proposal.old_html),
                    _plain(proposal.new_html),
                    proposal.ai_explanation,
                ],
            )
        )
        if _matches(haystack, query):
            hits.append(
                SearchHit(
                    kind=KIND_PROPOSAL,
                    label=(
                        f"{proposal.operation} by {proposal.proposed_by_side} "
                        f"[{proposal.state}]"
                    ),
                    snippet=_snippet(haystack, query),
                    audience=AUDIENCE_SHARED,
                    proposal_id=proposal.id,
                )
            )

    for entry in store.history(deal_id):
        detail = " ".join(f"{k}={v}" for k, v in entry.detail.items())
        haystack = f"{entry.action} {entry.actor} {entry.side} {detail}"
        if _matches(haystack, query):
            hits.append(
                SearchHit(
                    kind=KIND_DECISION,
                    label=f"{entry.ts} {entry.side}/{entry.actor}",
                    snippet=_snippet(haystack, query),
                    audience=AUDIENCE_SHARED,
                    proposal_id=entry.proposal_id,
                )
            )

    if requester_audience == AUDIENCE_INTERNAL and requester_side:
        for note in store.internal_notes(deal_id, side=requester_side):
            if _matches(note["body"], query):
                hits.append(
                    SearchHit(
                        kind=KIND_INTERNAL_NOTE,
                        label=f"internal note by {note['author']}",
                        snippet=_snippet(note["body"], query),
                        audience=AUDIENCE_INTERNAL,
                    )
                )

    visible = [
        hit
        for hit in hits
        if requester_audience == AUDIENCE_INTERNAL or hit.audience == AUDIENCE_SHARED
    ]
    return visible[:limit]
