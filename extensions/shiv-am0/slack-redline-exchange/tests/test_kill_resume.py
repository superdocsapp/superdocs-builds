from __future__ import annotations

from redline.core.negotiation import NegotiationService
from redline.core.store import Store
from redline.slack.simulator import InMemoryMessenger
from redline.superdocs.client import SuperDocsClient
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx


def _restart(
    settings, fake, messenger: InMemoryMessenger
) -> tuple[Store, NegotiationService, InMemoryMessenger]:
    """Simulate our process crashing and restarting: a brand new Store handle on the
    same database file (the only state that actually lived in our process), while
    SuperDocs and Slack -- both external, durable services -- persist across the crash
    exactly as they would in production, so the same fake/messenger instances carry
    forward unchanged."""
    store = Store(settings.database_path)
    client = SuperDocsClient(fake)
    service = NegotiationService(settings, store, client, messenger)
    return store, service, messenger


async def test_kill_before_driving_resumes_exactly_once(tmp_path):
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    cards_before = len(h.messenger.channels.get(h.settings.shared_channel, []))
    job = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=h.settings.shared_channel
    )
    assert job.state == "running"
    # process "dies" here -- drive_job was never called

    store2, service2, messenger2 = _restart(h.settings, h.fake, h.messenger)
    await service2.recover_pending()
    proposals_after_first_recovery = store2.proposals_for_job(job.job_id)
    assert len(proposals_after_first_recovery) >= 1
    cards_after_first_recovery = len(messenger2.channels.get(h.settings.shared_channel, []))
    assert cards_after_first_recovery - cards_before == len(proposals_after_first_recovery)

    # recovering again must not duplicate anything
    await service2.recover_pending()
    assert len(store2.proposals_for_job(job.job_id)) == len(proposals_after_first_recovery)
    assert len(messenger2.channels.get(h.settings.shared_channel, [])) == cards_after_first_recovery


async def test_kill_after_cards_posted_then_decide_completes_exactly_once(tmp_path):
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    job = await h.service.propose(
        deal_id, "vendor", "U_VENDOR", CAP_INSTRUCTION, source_channel_id=h.settings.shared_channel
    )
    await h.service.drive_job(job.job_id)
    proposal = h.store.proposals_for_job(job.job_id)[0]
    assert proposal.card_ts is not None
    cards_before_crash = len(h.messenger.channels.get(h.settings.shared_channel, []))
    # process "dies" here -- awaiting_review, cards already posted, nobody has decided yet

    store2, service2, messenger2 = _restart(h.settings, h.fake, h.messenger)
    await service2.recover_pending()
    # nothing needed reposting -- the DB already recorded the card_ts
    assert len(messenger2.channels.get(h.settings.shared_channel, [])) == cards_before_crash
    assert len(store2.proposals_for_job(job.job_id)) == 1

    await service2.decide(deal_id, proposal.id, "vendor", "U_VENDOR", True)
    # process "dies" again -- one side has decided, the other has not
    store3, service3, messenger3 = _restart(h.settings, h.fake, h.messenger)
    await service3.recover_pending()

    resolved = await service3.decide(deal_id, proposal.id, "customer", "U_CUSTOMER", True)
    assert resolved.state == "committed"

    history = store3.history(deal_id)
    completions = [entry for entry in history if entry.action == "job_completed"]
    assert len(completions) == 1, "the job must complete exactly once, not be re-finalized"
    drafts = [entry for entry in history if entry.action == "proposals_drafted"]
    assert len(drafts) == 1, "recovery must not re-draft proposals that already exist"
