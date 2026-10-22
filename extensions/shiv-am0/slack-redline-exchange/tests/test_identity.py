from __future__ import annotations

import pytest

from redline.config import (
    AmbiguousSideOverrideError,
    UnknownSideError,
    UnknownTeamError,
)
from redline.slack import handlers
from tests.conftest import build_harness, make_contract_docx, make_settings


def test_side_comes_from_the_workspace_by_default(tmp_path):
    settings = make_settings(tmp_path)
    assert settings.side_for("T_VENDOR", "U_ANYONE") == "vendor"
    assert settings.side_for("T_CUSTOMER", "U_ANYONE") == "customer"


def test_unknown_workspace_is_rejected_with_a_clear_message(tmp_path):
    settings = make_settings(tmp_path)
    with pytest.raises(UnknownTeamError) as excinfo:
        settings.side_for("T_STRANGER", "U_ANYONE")
    message = str(excinfo.value)
    assert "T_STRANGER" in message
    assert "T_VENDOR" in message and "T_CUSTOMER" in message


def test_user_override_pins_a_side_for_single_workspace_testing(tmp_path):
    settings = make_settings(
        tmp_path,
        vendor_team_id="T_ONE",
        customer_team_id="T_ONE",
        side_override_users="U_ALICE:vendor,U_BOB:customer",
    )
    assert settings.side_for("T_ONE", "U_ALICE") == "vendor"
    assert settings.side_for("T_ONE", "U_BOB") == "customer"
    # anyone without an override still falls back to the workspace mapping
    assert settings.side_for("T_ONE", "U_CAROL") == "vendor"


def test_malformed_override_is_rejected_loudly(tmp_path):
    settings = make_settings(tmp_path, side_override_users="U_ALICE:landlord")
    with pytest.raises(UnknownSideError):
        settings.side_for("T_VENDOR", "U_ALICE")


async def test_a_user_cannot_decide_on_behalf_of_the_other_side(tmp_path):
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    job = await h.sim.run_command(
        "vendor", f"propose {deal_id} Cap liability at $50k in the liability section"
    )
    proposal = h.store.proposals_for_job(job["job_id"])[0]

    # a vendor user forges a button click claiming to be the customer
    with pytest.raises(ValueError) as excinfo:
        await handlers.handle_block_action(
            h.service,
            h.settings,
            action_id=f"redline:decide:{proposal.id}:customer:approve",
            user_id="U_VENDOR",
            team_id=h.settings.vendor_team_id,
        )
    assert "on behalf of" in str(excinfo.value)

    fresh = h.store.get_proposal(proposal.id)
    assert fresh.customer_decision is None, "the forged decision must not be recorded"
    assert fresh.state == "pending"


def test_one_user_cannot_be_mapped_to_both_sides(tmp_path):
    """Config-time guard for the mistake that silently half-worked before.

    A duplicate key used to just overwrite, so the user looked like both sides but the
    anti-forgery check still rejected half their clicks -- a confusing failure a long
    way from its cause.
    """
    settings = make_settings(
        tmp_path, side_override_users="U_ALICE:vendor,U_ALICE:customer"
    )
    with pytest.raises(AmbiguousSideOverrideError) as excinfo:
        settings.side_for("T_VENDOR", "U_ALICE")
    assert "U_ALICE" in str(excinfo.value)


def test_repeating_the_same_mapping_is_harmless(tmp_path):
    """Only a *conflicting* duplicate is an error; an idempotent repeat is not."""
    settings = make_settings(
        tmp_path, side_override_users="U_ALICE:vendor,U_ALICE:vendor"
    )
    assert settings.side_for("T_VENDOR", "U_ALICE") == "vendor"
