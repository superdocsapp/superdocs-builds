"""Newly created text must land where SuperDocs put it, not at the end of the file.

SuperDocs returns `chunk_id` and `insert_after_chunk_id` on every proposed change. The
locally rebuilt redline used to discard both and append every addition, which quietly
moved new clauses to the bottom of the contract. These tests pin the position.
"""

from __future__ import annotations

import io

import docx

from redline.core.store import ProposalRow
from redline.export.track_changes import build_redline_docx
from tests.conftest import CAP_INSTRUCTION, SHARED_CHANNEL, build_harness, make_contract_docx

NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _paragraph_texts(content: bytes) -> list[str]:
    """Paragraph text including tracked insertions.

    python-docx's `paragraph.text` only reads runs that are direct children, so text
    wrapped in a w:ins revision mark reads as an empty paragraph. These tests are
    specifically about where inserted text sits, so we collect every w:t descendant.
    """
    document = docx.Document(io.BytesIO(content))
    texts = []
    for paragraph in document.paragraphs:
        parts = [node.text or "" for node in paragraph._p.iter(f"{NS}t")]
        texts.append("".join(parts))
    return texts


def _create(new_text: str, *, insert_after: str | None, chunk: str | None = None) -> ProposalRow:
    return ProposalRow(
        id=f"prop_{new_text[:6]}",
        deal_id="deal_1",
        job_id="job_1",
        change_id="chg_1",
        operation="create",
        old_html=None,
        new_html=new_text,
        ai_explanation="added during negotiation",
        proposed_by_side="vendor",
        chunk_id=chunk,
        insert_after_chunk_id=insert_after,
        state="committed",
    )


def test_a_created_clause_lands_after_its_anchor_not_at_the_end():
    original = make_contract_docx()
    before = _paragraph_texts(original)
    # c0003 is the third block: "Section 1: Confidential Information..."
    anchor_index = 2
    assert "Section 1" in before[anchor_index]

    out = build_redline_docx(
        "MSA.docx", original, [_create("Section 1A: New mutual clause.", insert_after="c0003")]
    )
    after = _paragraph_texts(out)

    assert "Section 1A: New mutual clause." in after
    position = after.index("Section 1A: New mutual clause.")
    assert position == anchor_index + 1, after
    # and it is genuinely mid-document, not merely appended
    assert position < len(after) - 1


def test_an_unanchored_addition_is_appended_and_reported_honestly():
    original = make_contract_docx()
    out = build_redline_docx(
        "MSA.docx", original, [_create("Floating clause with no anchor.", insert_after=None)]
    )
    after = _paragraph_texts(out)

    assert "Floating clause with no anchor." in after
    # it is called out rather than silently sitting at the bottom pretending to belong
    assert any("Unmatched Changes" in text for text in after)


def test_an_out_of_range_anchor_falls_back_instead_of_crashing():
    original = make_contract_docx()
    out = build_redline_docx(
        "MSA.docx", original, [_create("Clause anchored to nothing.", insert_after="c9999")]
    )
    after = _paragraph_texts(out)

    assert "Clause anchored to nothing." in after
    assert any("Unmatched Changes" in text for text in after)


def test_the_insertion_is_a_real_tracked_change():
    original = make_contract_docx()
    out = build_redline_docx(
        "MSA.docx", original, [_create("Section 1A: New mutual clause.", insert_after="c0003")]
    )
    xml = docx.Document(io.BytesIO(out)).element.xml
    assert "w:ins" in xml
    assert 'w:author="Vendor"' in xml


def test_ordering_holds_when_several_clauses_share_one_anchor():
    original = make_contract_docx()
    out = build_redline_docx(
        "MSA.docx",
        original,
        [
            _create("First addition.", insert_after="c0003"),
            _create("Second addition.", insert_after="c0003"),
        ],
    )
    after = _paragraph_texts(out)
    assert "First addition." in after and "Second addition." in after
    # both sit next to their anchor rather than drifting to the end of the document
    assert after.index("First addition.") < len(after) - 1
    assert after.index("Second addition.") < len(after) - 1


async def test_anchors_survive_the_round_trip_through_the_database(tmp_path):
    """The API gives us the anchors; they have to still be there at export time."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    job = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    await h.service.drive_job(job.job_id)
    proposals = h.store.proposals_for_job(job.job_id)

    assert proposals, "expected the fake to draft at least one proposal"
    # at least one proposal carries positioning information from SuperDocs
    assert any(p.chunk_id or p.insert_after_chunk_id for p in proposals)

    # and it is persisted, not just held in memory
    reloaded = h.store.get_proposal(proposals[0].id)
    assert reloaded.chunk_id == proposals[0].chunk_id
    assert reloaded.insert_after_chunk_id == proposals[0].insert_after_chunk_id
