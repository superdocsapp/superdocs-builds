from __future__ import annotations

import pytest

from redline.core.search import KIND_DOCUMENT, KIND_INTERNAL_NOTE, KIND_PROPOSAL
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx

SECRET_NOTE = "our confidential walkaway position is two hundred fifty thousand dollars"


async def _deal_with_history(h):
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    await h.service.add_internal_note(deal_id, "vendor", "vendor-lawyer", SECRET_NOTE)
    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    proposal = h.store.proposals_for_job(job["job_id"])[0]
    await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", True)
    return deal_id


async def test_search_finds_document_text_and_proposals(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    hits = h.service.search(
        deal_id, "liability", source_channel_id=h.settings.shared_channel, side="vendor"
    )
    kinds = {hit.kind for hit in hits}
    assert KIND_DOCUMENT in kinds, "should find the clause inside the source .docx"
    assert KIND_PROPOSAL in kinds, "should find the proposal that changed it"
    assert all("liability" in hit.snippet.lower() for hit in hits if hit.kind == KIND_DOCUMENT)


async def test_search_from_shared_channel_never_returns_internal_notes(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    hits = h.service.search(
        deal_id, "walkaway", source_channel_id=h.settings.shared_channel, side="vendor"
    )
    assert all(hit.kind != KIND_INTERNAL_NOTE for hit in hits)
    assert all(SECRET_NOTE not in hit.snippet.lower() for hit in hits)


async def test_search_from_internal_channel_returns_own_notes(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    hits = h.service.search(
        deal_id,
        "walkaway",
        source_channel_id=h.settings.vendor_internal_channel,
        side="vendor",
    )
    assert any(hit.kind == KIND_INTERNAL_NOTE for hit in hits)


async def test_one_side_cannot_search_the_other_sides_internal_notes(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    # the note belongs to vendor; customer searches from their OWN internal channel
    hits = h.service.search(
        deal_id,
        "walkaway",
        source_channel_id=h.settings.customer_internal_channel,
        side="customer",
    )
    assert all(hit.kind != KIND_INTERNAL_NOTE for hit in hits)
    assert all(SECRET_NOTE not in hit.snippet.lower() for hit in hits)


async def test_search_reports_no_matches_honestly(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    hits = h.service.search(
        deal_id,
        "cryptocurrency mining rights",
        source_channel_id=h.settings.shared_channel,
        side="vendor",
    )
    assert hits == []


async def test_empty_query_is_refused_with_guidance(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    with pytest.raises(ValueError) as excinfo:
        h.service.search(
            deal_id, "   ", source_channel_id=h.settings.shared_channel, side="vendor"
        )
    assert "search" in str(excinfo.value).lower()


async def test_search_via_slash_command_posts_results_to_the_calling_channel(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _deal_with_history(h)

    await h.sim.run_command("vendor", f"search {deal_id} liability")
    shared = h.sim.shared_messages()
    assert "match(es) for" in shared[-1].text

    # a leaked internal note must never reach the shared channel via search either
    await h.sim.run_command("vendor", f"search {deal_id} walkaway")
    assert all(SECRET_NOTE not in m.text.lower() for m in h.sim.shared_messages())
