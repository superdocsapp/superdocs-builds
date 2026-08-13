"""BUGS #5, reproduced against the real service instead of only described.

Every other live behaviour this project claims has a free path to re-check it
-- `verify` reads published documents back by durable id, at no cost. This one
does not: proving a real session really only holds one turn at a time means
actually parking a turn on it and actually sending a second one into the
collision, and parking a turn is a billable operation.

So this file is opt-in twice over, on top of every other test in this suite:
`SUPERDOCS_API_KEY` gets you in the door, and `SUPERDOCS_LIVE_REENTRY_TESTS=1`
is the separate switch that says spending one real operation to prove this is
worth it right now. `./selftest` never flips it on its own; it only says the
switch exists. Plain `./mb test` skips this file and reports why.

    SUPERDOCS_LIVE_REENTRY_TESTS=1 .venv/bin/python -m pytest tests/test_live_reentry.py -v

One operation, once: the probe instruction that parks the first batch. The
second turn is refused before anything is billed for it, and denying a parked
batch costs nothing -- both are stated outright in the FAQ this project was
built against, not assumed here.
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPERDOCS_LIVE_REENTRY_TESTS") != "1",
    reason=(
        "set SUPERDOCS_LIVE_REENTRY_TESTS=1 (with a real SUPERDOCS_API_KEY) to run "
        "this against api.superdocs.app -- it spends about one real operation"
    ),
)


def _until_free(client, session_id: str, budget: float = 10.0, poll: float = 0.5) -> list:
    """Poll `active_jobs` until it is empty or the budget runs out.

    Found the hard way (BUGS #20): `POST /v1/chat/{id}/approve` can return
    `200` before `GET /v1/sessions/{id}/jobs` agrees the job it just resolved
    is no longer active, even though `GET /v1/jobs/{id}` already does. Three
    clean reproductions closed the gap in under two seconds; the run that
    first found it took longer than that. A single read right after `approve`
    is exactly the wrong-endpoint version of the mistake item 10 already
    describes for export, so this polls a free endpoint instead of trusting
    the first answer.
    """
    deadline = time.monotonic() + budget
    active = client.active_jobs(session_id)
    while active and time.monotonic() < deadline:
        time.sleep(poll)
        active = client.active_jobs(session_id)
    return active


def test_a_real_409_is_caught_and_the_batch_blocking_it_is_really_cleared():
    from manualbuilder.superdocs import SuperDocs, SuperDocsError, load_dotenv

    load_dotenv()
    with SuperDocs() as client:
        session_id = client.init_session()
        document_id = client.upload(
            "reentry-probe.html",
            "<p>The maximum speed is 10 mph.</p>",
            session_id=session_id,
            open_mode="new_focused",
        )

        # The one billed call in this file: a turn concrete enough that the
        # model reliably proposes something, so there is a real batch to
        # collide with rather than a turn that completes with nothing parked.
        first_job = client.chat_async(
            "Change 10 mph to 12 mph. Change nothing else.",
            session_id,
            document_id=document_id,
        )
        job = client.wait_for_job(first_job)
        assert job["status"] == "awaiting_approval", (
            f"the probe instruction did not park a batch on the session -- got "
            f"status {job.get('status')!r}, so there was nothing for a second "
            f"turn to collide with"
        )

        # The second turn is refused before it is billed -- this is the real
        # 409 `session_busy` from BUGS #5, not a mocked shape of one.
        with pytest.raises(SuperDocsError, match="409"):
            client.chat_async("say hello", session_id, document_id=document_id)

        active = client.active_jobs(session_id)
        assert any(
            job_row.get("job_id") == first_job or job_row.get("id") == first_job
            for job_row in active
        ), "the parked job should be visible as what is holding the session"

        # Free: denying a parked batch costs no quota.
        changes = client.pending_changes(job)
        client.approve(
            session_id,
            first_job,
            {change.change_id: False for change in changes},
            approved_by_default=False,
        )

        still_active = _until_free(client, session_id)
        assert still_active == [], (
            f"denying the batch that was blocking the session should leave it free "
            f"within 10s; still listed active: {still_active}"
        )
