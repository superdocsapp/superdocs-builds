from __future__ import annotations

from redline.superdocs.client import SuperDocsClient, wait_for_turnpoint
from redline.superdocs.fake import FakeSuperDocs
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx


class SlowFake(FakeSuperDocs):
    """A SuperDocs that sits in `in_progress` for a few polls before drafting changes.

    This is what a large document or a deep model tier looks like from our side: the job
    is alive and healthy, it just has not reached a turnpoint yet.
    """

    def __init__(self, stall_polls: int = 3):
        super().__init__()
        self._stall_polls = stall_polls
        self._polls = 0

    def _advance(self, job):
        if job.status == "in_progress":
            self._polls += 1
            if self._polls <= self._stall_polls:
                return
        super()._advance(job)


async def test_slow_job_posts_progress_pings_and_still_completes(tmp_path):
    h = build_harness(tmp_path, warn_after_seconds=0.0, poll_interval_seconds=0.0)
    h.service.client = SuperDocsClient(SlowFake(stall_polls=3))
    h.fake = h.service.client._t

    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")

    progress = [m for m in h.sim.shared_messages() if "Still working" in m.text]
    assert progress, "a slow job must tell the channel it is still processing"
    assert "not a failure" in progress[0].text

    # and it still reaches review normally afterwards
    assert h.store.get_job(job["job_id"]).state == "awaiting_review"
    assert h.store.proposals_for_job(job["job_id"])


async def test_progress_callback_fires_from_wait_for_turnpoint(tmp_path):
    fake = SlowFake(stall_polls=2)
    client = SuperDocsClient(fake)
    await client.upload_document("MSA.docx", make_contract_docx(), session_id="s1")
    job_id = await client.start_edit("s1", CAP_INSTRUCTION, approval_mode="ask_every_time")

    seen: list[tuple[float, str]] = []

    async def on_progress(elapsed, snapshot):
        seen.append((elapsed, snapshot.status))

    snapshot = await wait_for_turnpoint(
        client,
        job_id,
        interval_seconds=0.0,
        warn_after_seconds=0.0,
        on_progress=on_progress,
    )
    assert seen, "on_progress should fire while the job is still in progress"
    assert all(status == "in_progress" for _elapsed, status in seen)
    assert snapshot.is_change_review


async def test_progress_ping_failure_never_breaks_the_job(tmp_path):
    h = build_harness(tmp_path, warn_after_seconds=0.0, poll_interval_seconds=0.0)
    h.service.client = SuperDocsClient(SlowFake(stall_polls=2))

    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    original_post = h.messenger.post_message
    calls = {"n": 0}

    async def flaky_post(channel, blocks, text, thread_ts=None):
        if "Still working" in text:
            calls["n"] += 1
            raise RuntimeError("slack is down")
        return await original_post(channel, blocks, text, thread_ts=thread_ts)

    h.messenger.post_message = flaky_post

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")

    assert calls["n"] > 0, "the progress ping should have been attempted"
    assert h.store.get_job(job["job_id"]).state == "awaiting_review", (
        "a failed progress ping must not abort an otherwise healthy job"
    )
    failures = [e for e in h.store.history(deal_id) if e.action == "progress_ping_failed"]
    assert failures, "the failure should be recorded in the audit trail, not swallowed"
