from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest
from slack_bolt.request.async_request import AsyncBoltRequest

from redline.slack.bolt_app import create_bolt_app
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx

pytestmark = pytest.mark.anyio


def _bolt_app(tmp_path):
    """A real Bolt app with our real listeners, wired to an in-memory service.

    The rest of the suite calls `handlers.*` directly, which skips Bolt's listener
    layer entirely -- so a listener registered with a malformed matcher passes every
    other test and only explodes when a human clicks a button. These tests exercise
    that layer.
    """
    h = build_harness(tmp_path)
    h.settings.slack_bot_token = "xoxb-not-a-real-token"
    h.settings.slack_signing_secret = "not-a-real-secret"
    return create_bolt_app(h.service, h.settings), h


def _block_action_request(action_id: str) -> AsyncBoltRequest:
    payload = {
        "type": "block_actions",
        "user": {"id": "U_VENDOR", "team_id": "T_VENDOR"},
        "team": {"id": "T_VENDOR"},
        "channel": {"id": "C_SHARED"},
        "actions": [{"action_id": action_id, "type": "button", "value": "x"}],
        "response_url": "https://slack.example/respond",
    }
    return AsyncBoltRequest(
        body=urlencode({"payload": json.dumps(payload)}),
        headers={"content-type": ["application/x-www-form-urlencoded"]},
        mode="socket_mode",
    )


async def _matching_listeners(app, request) -> list:
    """Run Bolt's own matchers, exactly as it does when a request arrives."""
    matched = []
    for listener in app._async_listeners:
        for matcher in listener.matchers:
            if not await matcher.async_matches(request, None):
                break
        else:
            matched.append(listener)
    return matched


async def test_decision_buttons_actually_match_their_listener(tmp_path):
    """Regression: the matcher was a hand-made dict, which Bolt rejects at click time.

    Bolt's matcher accepts only a literal str or a compiled re.Pattern; anything else
    raises BoltError from deep inside middleware, so the click 500s and the decision is
    silently lost. Running the real matcher is what proves the fix -- a malformed
    constraint raises here rather than in front of a user.
    """
    app, _ = _bolt_app(tmp_path)
    request = _block_action_request("redline:decide:p_123:vendor:approve")

    matched = await _matching_listeners(app, request)
    assert len(matched) == 1, "exactly one listener should claim a decision button"


async def test_unrelated_actions_do_not_match_the_decision_listener(tmp_path):
    """The prefix pattern must not swallow buttons belonging to something else."""
    app, _ = _bolt_app(tmp_path)

    matched = await _matching_listeners(app, _block_action_request("other_app:button"))
    assert matched == []


async def test_a_wrong_side_click_warns_without_destroying_the_card(tmp_path):
    """Regression: the wrong-side warning deleted the card it was complaining about.

    Slack's default for a response_url reply to a button click is to REPLACE the message
    carrying that button. So refusing a forged click overwrote the proposal card, in
    channel, for both parties -- taking the buttons with it and stranding a deal whose
    stored state was still perfectly fine. An error report must never be able to damage
    the thing it reports on.
    """
    app, h = _bolt_app(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    job = await h.sim.run_command("vendor", f"propose {deal['deal_id']} {CAP_INSTRUCTION}")
    proposal = h.store.proposals_for_job(job["job_id"])[0]
    shared = h.service.messenger.channels[h.settings.shared_channel]
    card_before = [(m.ts, m.text) for m in shared]

    sent: list[dict] = []

    async def respond(**kwargs):
        sent.append(kwargs)

    async def ack():
        pass

    # the customer clicks the *vendor* Approve button
    action_id = f"redline:decide:{proposal.id}:vendor:approve"
    listener = (await _matching_listeners(app, _block_action_request(action_id)))[0]
    await listener.ack_function(
        ack=ack,
        action={"action_id": action_id},
        body={"user": {"id": "U_CUSTOMER"}, "team": {"id": h.settings.customer_team_id}},
        respond=respond,
    )

    assert sent, "the user must still be told why their click was refused"
    assert "on behalf of" in sent[0]["text"]
    assert sent[0]["replace_original"] is False, (
        "replace_original must be explicitly False; Slack otherwise replaces the "
        "original message, deleting the proposal card and its buttons"
    )
    card_after = [(m.ts, m.text) for m in h.service.messenger.channels[h.settings.shared_channel]]
    assert card_after == card_before, "a refused click must not touch the shared channel"
    assert h.store.get_proposal(proposal.id).vendor_decision is None
    assert h.store.get_proposal(proposal.id).state == "pending"
