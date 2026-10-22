from __future__ import annotations

import pytest

from redline.core.negotiation import NegotiationError
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx
from tests.test_multidocument import make_amendment_docx

pytestmark = pytest.mark.anyio


async def test_a_second_document_joins_the_open_deal(tmp_path):
    """The existing behaviour, pinned: while a deal is open, files are context for it."""
    h = build_harness(tmp_path)
    first = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())

    assert h.service.latest_open_deal(h.settings.shared_channel).id == first["deal_id"]


async def test_closing_frees_the_channel_for_the_next_contract(tmp_path):
    """Without this there is no way to negotiate a second contract in one channel.

    A file shared into a channel joins whatever deal is open there. Only a human knows
    when a negotiation is finished, so closing has to be an explicit act.
    """
    h = build_harness(tmp_path)
    first = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())

    await h.service.close_deal(first["deal_id"], "vendor", "U_VENDOR")
    assert h.service.latest_open_deal(h.settings.shared_channel) is None

    second = await h.sim.send_file_share("customer", "Amendment_1.docx", make_amendment_docx())
    assert second["deal_id"] != first["deal_id"], "a closed deal must not swallow the next file"

    documents = h.service.list_documents(second["deal_id"])
    assert [d.role for d in documents] == ["contract"], "the new deal owns its own contract"


async def test_a_closed_deal_keeps_its_history(tmp_path):
    """Closing ends the negotiation; it does not erase the record of it."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    await h.service.close_deal(deal_id, "vendor", "U_VENDOR")

    assert h.store.get_deal(deal_id).status == "closed"
    assert h.service.history_lines(deal_id), "history must survive closing"
    assert any(e.action == "deal_closed" for e in h.store.history(deal_id))


async def test_closing_is_refused_while_decisions_are_outstanding(tmp_path):
    """Otherwise the trail would end with changes nobody ever resolved."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")

    with pytest.raises(NegotiationError) as excinfo:
        await h.service.close_deal(deal_id, "vendor", "U_VENDOR")
    assert "awaiting a decision" in str(excinfo.value)
    assert h.store.get_deal(deal_id).status == "active"


async def test_closing_twice_is_refused(tmp_path):
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    await h.service.close_deal(deal["deal_id"], "vendor", "U_VENDOR")

    with pytest.raises(NegotiationError):
        await h.service.close_deal(deal["deal_id"], "customer", "U_CUSTOMER")


async def test_promoting_swaps_which_document_is_authoritative(tmp_path):
    """A supporting document can turn out to be the thing actually being negotiated."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    await h.sim.send_file_share(
        "customer", "Amendment_1.docx", make_amendment_docx(), attach_to_deal_id=deal_id
    )

    await h.service.promote_document(deal_id, "Amendment_1", "customer", "U_CUSTOMER")

    roles = {d.filename: d.role for d in h.service.list_documents(deal_id)}
    assert roles == {"MSA.docx": "supporting", "Amendment_1.docx": "contract"}


async def test_an_untargeted_edit_follows_the_promoted_contract(tmp_path):
    """Promotion has to actually redirect edits, not just relabel a row."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    await h.sim.send_file_share(
        "customer", "Amendment_1.docx", make_amendment_docx(), attach_to_deal_id=deal_id
    )
    await h.service.promote_document(deal_id, "Amendment_1", "customer", "U_CUSTOMER")
    amendment = next(
        d for d in h.service.list_documents(deal_id) if d.filename == "Amendment_1.docx"
    )

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    proposals = h.store.proposals_for_job(job["job_id"])
    assert proposals
    assert all(p.document_id == amendment.id for p in proposals)


async def test_promoting_the_current_contract_is_refused(tmp_path):
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())

    with pytest.raises(NegotiationError) as excinfo:
        await h.service.promote_document(deal["deal_id"], "MSA", "vendor", "U_VENDOR")
    assert "already the contract" in str(excinfo.value)


async def test_promotion_is_recorded_in_the_trail(tmp_path):
    """Which document was authoritative, and when, is part of the negotiation record."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    await h.sim.send_file_share(
        "customer", "Amendment_1.docx", make_amendment_docx(), attach_to_deal_id=deal_id
    )

    await h.service.promote_document(deal_id, "Amendment_1", "customer", "U_CUSTOMER")

    entry = next(e for e in h.store.history(deal_id) if e.action == "contract_replaced")
    assert entry.detail["document"] == "Amendment_1.docx"
    assert entry.detail["previous"] == "MSA.docx"
