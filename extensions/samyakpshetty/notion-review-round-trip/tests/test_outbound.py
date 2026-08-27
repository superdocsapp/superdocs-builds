from __future__ import annotations

from io import BytesIO

from docx import Document

from notion_review.domain import RoundStatus
from notion_review.notion import FakeNotionClient
from notion_review.roundtrip import send_for_review
from notion_review.store import SQLiteStore
from notion_review.superdocs import FakeSuperDocsClient

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _send() -> tuple[FakeNotionClient, FakeSuperDocsClient, SQLiteStore, str, object]:
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    packet = send_for_review(notion=notion, superdocs=superdocs, store=store, page_id=page_id)
    return notion, superdocs, store, page_id, packet


def test_send_maps_every_block_to_a_chunk() -> None:
    _, _, _, _, packet = _send()
    round_ = packet.round  # type: ignore[attr-defined]
    assert round_.status == RoundStatus.SENT
    assert round_.block_map, "expected a non-empty block map"
    # The whole point of the outbound leg: every editable block is tied to a SuperDocs chunk.
    assert all(entry.chunk_id is not None for entry in round_.block_map)
    assert round_.sent_version_id is not None


def test_send_produces_a_real_docx_for_the_reviewer() -> None:
    _, _, _, _, packet = _send()
    assert packet.docx.content_type == _DOCX_MIME  # type: ignore[attr-defined]
    doc = Document(BytesIO(packet.docx.content))  # type: ignore[attr-defined]
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Overview" in text
    assert "Aurora ships in Q3" in text


def test_send_persists_the_round_and_links_it_on_the_page() -> None:
    notion, _, store, page_id, packet = _send()
    round_ = packet.round  # type: ignore[attr-defined]

    reloaded = store.get(round_.id)
    assert reloaded is not None
    assert reloaded.status == RoundStatus.SENT

    # On sending, the page records which round it went out in; the clickable link to that round
    # appears once the round has a queue to point at (see test_notion_gate).
    comments = notion.comments_for(page_id)
    assert len(comments) == 1
    assert round_.id in comments[0].plain()
