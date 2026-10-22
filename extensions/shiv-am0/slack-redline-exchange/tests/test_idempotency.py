"""Proposing is what costs money, so proposing twice must not pay twice.

`start_edit` is the call that consumes a SuperDocs operation. These tests count the
calls that actually reach the API rather than trusting the job rows, because the whole
point is that the second request never gets that far.
"""

from __future__ import annotations

import pytest

from redline.core import boundary
from tests.conftest import CAP_INSTRUCTION, SHARED_CHANNEL, build_harness, make_contract_docx


def _edit_calls(harness) -> int:
    return len([r for r in harness.fake.records if r[1] == "/v1/chat/async"])


async def _open_deal(harness) -> str:
    deal = await harness.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    return deal["deal_id"]


async def test_the_same_instruction_twice_starts_one_job(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _open_deal(h)

    before = _edit_calls(h)
    first = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    second = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )

    assert first.job_id == second.job_id
    # exactly one billable edit reached SuperDocs, not two
    assert _edit_calls(h) - before == 1
    assert len([j for j in h.store.jobs_in_states("running", "awaiting_review") ]) == 1


async def test_deduplication_survives_whitespace_and_case(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _open_deal(h)

    first = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    retyped = f"  {CAP_INSTRUCTION.upper()}   "
    second = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", retyped, source_channel_id=SHARED_CHANNEL
    )
    assert first.job_id == second.job_id


async def test_a_different_instruction_is_never_swallowed(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _open_deal(h)

    first = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    second = await h.service.propose(
        deal_id,
        "vendor",
        "U_VENDOR",
        "Shorten the term to one year",
        source_channel_id=SHARED_CHANNEL,
    )
    assert first.job_id != second.job_id


async def test_a_caller_supplied_key_defines_sameness(tmp_path):
    """Two different instructions under one key collapse; the caller owns the boundary."""
    h = build_harness(tmp_path)
    deal_id = await _open_deal(h)

    first = await h.service.propose(
        deal_id,
        "vendor",
        "U_VENDOR",
        CAP_INSTRUCTION,
        source_channel_id=SHARED_CHANNEL,
        idempotency_key="retry-42",
    )
    second = await h.service.propose(
        deal_id,
        "vendor",
        "U_VENDOR",
        "Something else entirely",
        source_channel_id=SHARED_CHANNEL,
        idempotency_key="retry-42",
    )
    assert first.job_id == second.job_id


async def test_the_fold_is_recorded_rather_than_hidden(tmp_path):
    h = build_harness(tmp_path)
    deal_id = await _open_deal(h)

    await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )

    actions = [e.action for e in h.store.history(deal_id)]
    assert "propose_deduplicated" in actions


async def test_a_stale_key_outside_the_window_starts_fresh_work(tmp_path):
    """A finished job stops shielding an identical instruction once the window passes.

    Re-proposing the same clause later in a negotiation is legitimate, so the guard is
    deliberately narrow: it protects double-clicks and retries, not the whole deal.
    """
    h = build_harness(tmp_path, idempotency_window_seconds=0.0)
    deal_id = await _open_deal(h)

    first = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    # drive it to a terminal state so it is no longer "in flight"
    h.store.set_job_state(first.job_id, "completed")

    second = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    assert first.job_id != second.job_id


async def test_an_in_flight_job_dedupes_regardless_of_age(tmp_path):
    """Age must not matter while humans still owe a decision on the identical change."""
    h = build_harness(tmp_path, idempotency_window_seconds=0.0)
    deal_id = await _open_deal(h)

    first = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    h.store.set_job_state(first.job_id, "awaiting_review")

    second = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    assert first.job_id == second.job_id


async def test_deduplication_never_bypasses_the_boundary(tmp_path):
    """The cheap path must not become a way around the provenance rule."""
    h = build_harness(tmp_path)
    deal_id = await _open_deal(h)

    await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=SHARED_CHANNEL
    )
    with pytest.raises(boundary.BoundaryViolation):
        await h.service.propose(
            deal_id,
            "vendor",
            "U_VENDOR",
            CAP_INSTRUCTION,
            source_channel_id=h.settings.vendor_internal_channel,
        )
