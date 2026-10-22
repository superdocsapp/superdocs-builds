from __future__ import annotations

import pytest

from redline.superdocs.transport import SuperDocsAPIError
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx

pytestmark = pytest.mark.anyio


async def _proposal_awaiting_decision(h):
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    return deal_id, h.store.proposals_for_job(job["job_id"])[0]


async def test_a_decision_is_announced_with_what_changed(tmp_path):
    """The card is the control surface; the notice is how people learn it moved.

    Restating the substance matters -- a bare "vendor approved" forces the reader back
    to the card, which is the thing this exists to avoid.
    """
    h = build_harness(tmp_path)
    deal_id, proposal = await _proposal_awaiting_decision(h)
    before = len(h.sim.shared_messages())

    await h.sim.click("vendor", proposal.id, "approve")

    new_messages = h.sim.shared_messages()[before:]
    assert new_messages, "approving must announce something in the shared channel"
    notice = new_messages[0].text
    assert "Vendor" in notice and "approved" in notice
    assert "Waiting on" in notice and "Customer" in notice


async def test_the_notice_names_who_is_still_blocking(tmp_path):
    """Under dual consent the second decision is the one that unblocks the batch."""
    h = build_harness(tmp_path)
    deal_id, proposal = await _proposal_awaiting_decision(h)

    await h.sim.click("customer", proposal.id, "approve")
    before = len(h.sim.shared_messages())
    await h.sim.click("vendor", proposal.id, "approve")

    texts = [m.text for m in h.sim.shared_messages()[before:]]
    assert any("Both sides have decided" in t for t in texts)


async def test_the_outcome_reaches_both_internal_channels(tmp_path):
    """Neither side should have to be watching the shared channel to learn the result."""
    h = build_harness(tmp_path)
    deal_id, proposal = await _proposal_awaiting_decision(h)

    await h.sim.click("vendor", proposal.id, "approve")
    await h.sim.click("customer", proposal.id, "approve")

    for side in ("vendor", "customer"):
        texts = [m.text for m in h.sim.internal_messages(side)]
        assert any("updated to" in t for t in texts), f"{side} was never told the outcome"


async def test_the_outcome_is_not_buried_in_a_thread(tmp_path):
    """The result of the whole exchange should be visible without opening a thread."""
    h = build_harness(tmp_path)
    deal_id, proposal = await _proposal_awaiting_decision(h)

    await h.sim.click("vendor", proposal.id, "approve")
    await h.sim.click("customer", proposal.id, "approve")

    outcomes = [m for m in h.sim.shared_messages() if "updated to" in m.text]
    assert outcomes, "no outcome message was posted"
    assert outcomes[-1].thread_ts is None, "the outcome must be a top-level message"


async def test_an_expired_superdocs_job_is_reported_not_silently_swallowed(tmp_path):
    """Regression: a 404 from SuperDocs crashed after both sides had already approved.

    The decisions were real and recorded, the card read "approved", and the document was
    never touched -- with only a traceback in the server log to say so. Both sides must
    be told, and the proposal must not be left claiming to be pending forever.
    """
    h = build_harness(tmp_path)
    deal_id, proposal = await _proposal_awaiting_decision(h)

    async def expired(*_args, **_kwargs):
        raise SuperDocsAPIError(404, "not_found", "Job not found")

    h.service.client.submit_decisions = expired

    await h.sim.click("vendor", proposal.id, "approve")
    await h.sim.click("customer", proposal.id, "approve")

    assert h.store.get_proposal(proposal.id).state == "expired", (
        "an unappliable proposal must not stay pending, nor claim to be committed"
    )
    shared = [m.text for m in h.sim.shared_messages()]
    assert any("could no longer apply" in t for t in shared)
    for side in ("vendor", "customer"):
        texts = [m.text for m in h.sim.internal_messages(side)]
        assert any("could no longer apply" in t for t in texts)


async def test_a_failed_notification_never_undoes_a_decision(tmp_path):
    """Slack is not allowed to veto something the store already recorded."""
    h = build_harness(tmp_path)
    deal_id, proposal = await _proposal_awaiting_decision(h)

    original = h.service.messenger.post_message

    async def flaky(channel, blocks, text, thread_ts=None):
        if "approved" in text:
            raise RuntimeError("slack is down")
        return await original(channel, blocks, text, thread_ts)

    h.service.messenger.post_message = flaky

    await h.sim.click("vendor", proposal.id, "approve")

    assert h.store.get_proposal(proposal.id).vendor_decision == "approved"
