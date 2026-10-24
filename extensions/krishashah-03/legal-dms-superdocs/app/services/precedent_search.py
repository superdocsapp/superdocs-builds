"""
The "precedent shelf": search across prior documents, scoped so a user only
ever sees results from matters they're entitled to see.

Access control lives entirely in this module, before SuperDocs (or an AI
summarizer) ever sees a byte of a candidate document. SuperDocs has no
concept of a "matter" or "ethical wall" - deliberately - so it is never
asked to do the filtering. See app/dms/store.py::DMSStore.all_documents_visible_to
for the enforcement point this search calls into.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.dms.store import DMSStore
from app.superdocs.client import SuperDocsClient

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


@dataclass
class PrecedentHit:
    document_id: str
    matter_id: str
    title: str
    version: int
    score: float
    snippet: str


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _keyword_score(query_tokens: set[str], doc_tokens: list[str]) -> float:
    if not doc_tokens:
        return 0.0
    doc_token_set = set(doc_tokens)
    overlap = query_tokens & doc_token_set
    if not overlap:
        return 0.0
    # Simple normalized overlap - fine for a precedent-shelf search where the
    # hard requirement is correct ACCESS filtering, not ranking sophistication.
    # See README "What I cut" for why this isn't embeddings-based.
    return len(overlap) / len(query_tokens)


def _snippet(html: str, query_tokens: set[str], width: int = 160) -> str:
    text = " ".join(_strip_html(html).split())
    lowered = text.lower()
    for token in query_tokens:
        idx = lowered.find(token)
        if idx != -1:
            start = max(0, idx - width // 2)
            return text[start : start + width].strip()
    return text[:width].strip()


def search_precedents(
    dms: DMSStore,
    user_id: str,
    query: str,
    exclude_document_id: str | None = None,
    limit: int = 5,
) -> list[PrecedentHit]:
    """
    Searches document titles + text across every matter `user_id` can see.
    A document in a matter the user is walled off from is never a candidate -
    it is filtered out by all_documents_visible_to() before scoring, so it
    can never appear in results regardless of how well it would have matched.
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    hits: list[PrecedentHit] = []
    for doc in dms.all_documents_visible_to(user_id):
        if doc.document_id == exclude_document_id:
            continue
        version = doc.current_version
        doc_text = f"{doc.title} {_strip_html(version.html)}"
        doc_tokens = _tokenize(doc_text)
        score = _keyword_score(query_tokens, doc_tokens)
        if score <= 0:
            continue
        hits.append(
            PrecedentHit(
                document_id=doc.document_id,
                matter_id=doc.matter_id,
                title=doc.title,
                version=version.version_number,
                score=score,
                snippet=_snippet(version.html, query_tokens),
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def summarize_hits_with_ai(
    superdocs: SuperDocsClient,
    hits: list[PrecedentHit],
    query: str,
    scratch_session_prefix: str = "precedent-summary",
) -> str | None:
    """
    Optional enrichment: hand the (already access-filtered) top hits to
    SuperDocs as read-only attachments in a throwaway session, and ask it to
    summarize what they say relevant to the query. If this is skipped or
    fails, callers should fall back to the plain keyword hits - this is
    depth, not the access-control guarantee, which is already complete by
    the time this function is ever called.
    """
    if not hits:
        return None
    import base64
    import uuid

    session_id = f"{scratch_session_prefix}-{uuid.uuid4().hex[:8]}"
    for hit in hits:
        content = f"Precedent: {hit.title} (v{hit.version})\n\n{hit.snippet}"
        file_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        superdocs.upload_attachment_base64(
            filename=f"{hit.document_id}.txt",
            file_base64=file_b64,
            session_id=session_id,
        )
    # Note: a real deployment would poll attachment status, then send a chat
    # message asking for a synthesis and return the AI's reply text. Wiring
    # the full round-trip needs a live API key to test end-to-end, so this
    # function stops at "attachments loaded" and is exercised in tests via a
    # mock - see tests/test_precedent_search.py::test_ai_summary_never_sees_walled_docs.
    return (
        f"Loaded {len(hits)} access-checked precedent(s) as AI context for query "
        f"'{query}'. Ask the AI in session {session_id} to synthesize them."
    )
