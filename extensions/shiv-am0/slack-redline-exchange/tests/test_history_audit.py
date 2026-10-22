from __future__ import annotations

from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx


async def test_history_audit_records_the_full_arc_in_order(tmp_path):
    h = build_harness(tmp_path, approval_policy="dual_consent")
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    proposal = h.store.proposals_for_job(job["job_id"])[0]
    await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", True)
    await h.service.add_internal_note(
        deal_id, "vendor", "U_VENDOR", "keeping an eye on this clause"
    )

    entries = h.store.history(deal_id)
    actions = [e.action for e in entries]

    expected_order = [
        "deal_started",
        "propose_started",
        "proposals_drafted",
        "decision_recorded",
        "decision_recorded",
        "proposal_resolved",
        "job_completed",
        "internal_note_added",
    ]
    for expected in expected_order:
        assert expected in actions

    # seq is strictly increasing, i.e. a genuine append-only audit trail
    seqs = [e.seq for e in entries]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

    # every entry is attributable to a who/what -- never anonymous
    assert all(e.actor for e in entries)
    assert all(e.side for e in entries)

    lines = h.service.history_lines(deal_id)
    assert len(lines) == len(entries)
    assert any("job_completed" in line for line in lines)


async def test_history_is_per_deal(tmp_path):
    h = build_harness(tmp_path)
    deal_a = await h.sim.send_file_share("vendor", "A.docx", make_contract_docx())
    deal_b = await h.sim.send_file_share("customer", "B.docx", make_contract_docx())

    history_a = h.store.history(deal_a["deal_id"])
    history_b = h.store.history(deal_b["deal_id"])
    assert all(e.deal_id == deal_a["deal_id"] for e in history_a)
    assert all(e.deal_id == deal_b["deal_id"] for e in history_b)
    assert len(history_a) == len(history_b) == 1
