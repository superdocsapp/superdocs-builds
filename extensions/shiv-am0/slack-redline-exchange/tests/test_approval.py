from __future__ import annotations

from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx


async def _start_and_propose(h, instruction: str = CAP_INSTRUCTION):
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    job = await h.sim.run_command("vendor", f"propose {deal_id} {instruction}")
    proposals = h.store.proposals_for_job(job["job_id"])
    assert proposals, "expected at least one proposal"
    return deal_id, proposals


async def test_dual_consent_requires_both_sides_to_commit(tmp_path):
    h = build_harness(tmp_path, approval_policy="dual_consent")
    deal_id, proposals = await _start_and_propose(h)
    proposal = proposals[0]

    only_vendor = await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    assert only_vendor.state == "pending", "must not resolve until both sides decide"

    resolved = await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", True)
    assert resolved.state == "committed"
    assert h.store.get_deal(deal_id).current_version != "v1"


async def test_dual_consent_any_rejection_sends_change_back_with_feedback(tmp_path):
    h = build_harness(tmp_path, approval_policy="dual_consent")
    deal_id, proposals = await _start_and_propose(h)
    proposal = proposals[0]

    await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    await h.service.decide(
        deal_id, proposal.id, "customer", "U_CUSTOMER", False, feedback="Make it $75k instead"
    )

    original = h.store.get_proposal(proposal.id)
    assert original.state == "revised"
    assert original.customer_feedback == "Make it $75k instead"

    job = h.store.get_job(proposal.job_id)
    new_round = [p for p in h.store.proposals_for_job(job.job_id) if p.id != proposal.id]
    assert new_round, "a revision round should have produced new proposal(s)"
    assert all("[revised" in p.ai_explanation for p in new_round)

    # both sides approve the revised proposal -> it commits
    for p in new_round:
        await h.service.decide(deal_id, p.id, "vendor", "U_VENDOR", True)
        resolved = await h.service.decide(deal_id, p.id, "customer", "U_CUSTOMER", True)
        assert resolved.state == "committed"


async def test_dual_consent_full_rejection_without_feedback_just_rejects(tmp_path):
    h = build_harness(tmp_path, approval_policy="dual_consent")
    deal_id, proposals = await _start_and_propose(h)
    proposal = proposals[0]
    version_before = h.store.get_deal(deal_id).current_version

    await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", False)
    resolved = await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", False)

    assert resolved.state == "rejected"
    assert h.store.get_deal(deal_id).current_version == version_before


async def test_proposer_only_gates_on_proposer_alone(tmp_path):
    h = build_harness(tmp_path, approval_policy="proposer_only")
    deal_id, proposals = await _start_and_propose(h)
    proposal = proposals[0]
    assert proposal.proposed_by_side == "vendor"

    # vendor (the proposer) approving alone is enough to commit, no customer decision needed
    resolved = await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    assert resolved.state == "committed"
    assert resolved.customer_decision is None


async def test_proposer_only_counterparty_decision_is_informational(tmp_path):
    h = build_harness(tmp_path, approval_policy="proposer_only")
    deal_id, proposals = await _start_and_propose(h)
    proposal = proposals[0]

    # the counterparty rejecting does not block or flip the outcome under proposer_only
    await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", False)
    still_pending = h.store.get_proposal(proposal.id)
    assert still_pending.state == "pending"

    resolved = await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    assert resolved.state == "committed"
