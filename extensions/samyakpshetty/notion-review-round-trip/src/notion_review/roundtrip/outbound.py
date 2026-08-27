"""Outbound: send a Notion page out for review as a styled Word document.

Steps: fetch the page's block tree → render it to HTML with a reversible block map → upload to
SuperDocs → reconcile SuperDocs' chunk ids back onto the block map → export a styled .docx for
the reviewer → record the durable review round and link it on the Notion page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from lxml import html as lxml_html
from lxml.html import HtmlElement

from notion_review.domain import BlockMapEntry, ReviewRound, RoundStatus
from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient
from notion_review.notion.html import blocks_to_html
from notion_review.notion.models import RichText
from notion_review.notion.tree import fetch_block_tree
from notion_review.roundtrip.notion_gate import ensure_queue
from notion_review.store import Store
from notion_review.superdocs.base import SuperDocsClient
from notion_review.superdocs.models import ExportResult

_log = get_logger("notion_review.outbound")


@dataclass
class ReviewPacket:
    """What a send produces: the persisted round and the reviewer's Word file."""

    round: ReviewRound
    docx: ExportResult


def reconcile_chunks(returned_html: str, block_map: list[BlockMapEntry]) -> int:
    """Fill each block-map entry's ``chunk_id`` from SuperDocs' returned HTML.

    This is best-effort provenance, not a correctness requirement: an edit is proposed by
    content, and SuperDocs returns the chunk id we approve with. We match first on our
    ``data-nr-id`` marker (the fake preserves it) and then, because the live service strips
    unknown attributes and re-chunks its own way, fall back to matching by block text.
    Returns the number of entries matched.
    """
    root = lxml_html.fromstring(f"<div>{returned_html}</div>")
    chunks: list[tuple[str, str | None, str]] = []  # (chunk_id, marker, normalized_text)
    for el in root.iter():
        chunk_id = el.get("data-chunk-id")
        if chunk_id:
            text = " ".join(str(cast(HtmlElement, el).text_content()).split())
            chunks.append((chunk_id, el.get("data-nr-id"), text))

    by_marker = {marker: cid for cid, marker, _ in chunks if marker}
    used: set[str] = set()
    matched = 0

    for entry in block_map:  # 1. exact marker match
        chunk_id = by_marker.get(entry.notion_block_id)
        if chunk_id:
            entry.chunk_id = chunk_id
            used.add(chunk_id)
            matched += 1

    for entry in block_map:  # 2. text match for the rest (marker-stripping / re-chunking)
        if entry.chunk_id:
            continue
        target = " ".join(entry.original_text.split())
        if not target:
            continue
        for chunk_id, _, text in chunks:
            if chunk_id not in used and (target == text or target in text):
                entry.chunk_id = chunk_id
                used.add(chunk_id)
                matched += 1
                break
    return matched


def send_for_review(
    *,
    notion: NotionClient,
    superdocs: SuperDocsClient,
    store: Store,
    page_id: str,
) -> ReviewPacket:
    """Send a single Notion page out for formal review; returns the round and the Word file."""
    return send_packet_for_review(
        notion=notion, superdocs=superdocs, store=store, page_ids=[page_id]
    )


def send_packet_for_review(
    *,
    notion: NotionClient,
    superdocs: SuperDocsClient,
    store: Store,
    page_ids: list[str],
) -> ReviewPacket:
    """Send one or more Notion pages out as a single review document.

    Each page's blocks are rendered in turn into one styled Word file, and every block-map entry
    is tagged with the page it came from, so an approved change fans back to the exact block on
    the exact originating page — never the wrong one, even when two pages share a heading.
    """
    if not page_ids:
        raise ValueError("send_packet_for_review needs at least one page id")

    pages = []
    html_parts: list[str] = []
    block_map: list[BlockMapEntry] = []
    for page_id in page_ids:
        page = notion.retrieve_page(page_id)
        pages.append(page)
        html, page_map = blocks_to_html(fetch_block_tree(notion, page_id))
        for entry in page_map:
            entry.notion_page_id = page_id
        block_map.extend(page_map)
        html_parts.append(html)

    round_ = ReviewRound(notion_page_id=page_ids[0], block_map=block_map)
    _log.info(
        "review_round_created",
        extra={"round_id": round_.id, "pages": len(pages), "blocks": len(block_map)},
    )

    upload = superdocs.upload_document(
        document_html="".join(html_parts), session_id=round_.session_id
    )
    matched = reconcile_chunks(upload.html, round_.block_map)
    round_.sent_version_id = upload.version_id
    if matched < len(block_map):
        # Say *which* blocks, because the usual answer is a known structural loss rather than a
        # fault: SuperDocs drops a toggle's summary text on upload, so a toggle title has no chunk
        # to reconcile against. A bare count reads like a failure and tells an operator nothing.
        missing = [entry for entry in block_map if not entry.chunk_id]
        _log.warning(
            "unmapped_blocks",
            extra={
                "round_id": round_.id,
                "matched": matched,
                "total": len(block_map),
                "unmapped": [
                    {"type": entry.block_type, "text": entry.original_text[:60]}
                    for entry in missing[:5]
                ],
            },
        )

    docx = superdocs.export(session_id=round_.session_id, fmt="docx")

    round_.status = RoundStatus.SENT
    # Create the round's record now, while the document is going out, so the page carries a link
    # to the review round from the moment it leaves — not only once the markup comes back.
    ensure_queue(round_, notion)
    store.save(round_)

    for page in pages:
        notion.create_comment(
            page_id=page.id,
            rich_text=[
                RichText(text="Sent for external review · "),
                RichText(text=f"round {round_.id}", href=round_.review_url or None),
                RichText(
                    text=". Approved changes will be applied to this page and recorded there."
                ),
            ],
        )
    _log.info(
        "review_round_sent",
        extra={
            "round_id": round_.id,
            "chunks": upload.chunks_count,
            "docx_bytes": len(docx.content),
        },
    )
    return ReviewPacket(round=round_, docx=docx)
