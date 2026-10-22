from __future__ import annotations

from redline.core.store import Store
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx


async def test_authoritative_version_is_identical_for_both_sides_and_monotonic(tmp_path):
    h = build_harness(tmp_path, approval_policy="dual_consent")
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    v0 = h.store.get_deal(deal_id).current_version
    assert v0 == "v1"

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    proposal = h.store.proposals_for_job(job["job_id"])[0]
    await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", True)

    v1 = h.store.get_deal(deal_id).current_version
    assert v1 != v0

    # a second, independent Store handle reading the same database sees the exact same
    # version a "customer-side" reader would see -- there is only ever one authoritative row
    reader_store = Store(h.settings.database_path)
    assert reader_store.get_deal(deal_id).current_version == v1
    vendor_view = h.service.status(deal_id)
    customer_view = h.service.status(deal_id)
    assert vendor_view["current_version"] == customer_view["current_version"] == v1

    job2 = await h.sim.run_command(
        "customer", f"propose {deal_id} Delete the section on Term", in_shared_channel=True
    )
    for p in h.store.proposals_for_job(job2["job_id"]):
        await h.service.decide(deal_id, p.id, "vendor", "U_VENDOR", True)
        await h.service.decide(deal_id, p.id, "customer", "U_CUSTOMER", True)
    v2 = h.store.get_deal(deal_id).current_version
    assert v2 != v1


async def test_version_unchanged_when_nothing_is_applied(tmp_path):
    h = build_harness(tmp_path, approval_policy="dual_consent")
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    v0 = h.store.get_deal(deal_id).current_version

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    proposal = h.store.proposals_for_job(job["job_id"])[0]
    await h.service.decide(deal_id, proposal.id, "vendor", "U_VENDOR", False)
    await h.service.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", False)

    assert h.store.get_deal(deal_id).current_version == v0
