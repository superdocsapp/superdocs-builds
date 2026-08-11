"""Tests for the SuperDocs client, driven over real HTTP against the fake service.

These prove the client's own behaviour - request construction, retry policy, response parsing and
the approval semantics - not that a mock returns what it was told to return.
"""

from __future__ import annotations

import pytest

from docs_lint.superdocs.client import RetryPolicy, SuperDocsClient
from docs_lint.superdocs.errors import (
    SuperDocsAuthError,
    SuperDocsBadRequest,
    SuperDocsJobTimeout,
    SuperDocsRateLimited,
    SuperDocsSessionBusy,
    SuperDocsUnavailable,
)
from docs_lint.superdocs.models import (
    AttachmentStatus,
    DocumentUpload,
    Job,
    JobStatus,
    JobUsage,
    Usage,
    decode_maybe_json_string,
    extract_chunk_ids,
)
from tests.conftest import SAMPLE_DOC, cassette
from tests.fake_superdocs.server import DEFAULT_API_KEY

# -- parsing recorded live responses ------------------------------------------------
#
# These pin the models against bodies captured from the real service. If SuperDocs changes a
# shape, these fail and say so, rather than the fake and the client agreeing with each other
# while both drift away from reality.


def test_usage_parses_the_recorded_live_whoami_response():
    usage = Usage.from_payload(cassette("whoami_before")["body"])
    assert usage.operations_used == 0
    assert usage.operations_remaining == 500
    assert usage.monthly_limit == 500
    assert usage.plan == "free"


def test_whoami_hides_the_promo_bucket_that_the_job_usage_reveals():
    """Documents BUGS.md #1 as an executable fact, not just prose.

    whoami says 500 operations remain. The same account's completed job says the promo bucket
    holds 9,999. A budget built on whoami would throttle twenty times too hard.
    """
    whoami = Usage.from_payload(cassette("whoami_before")["body"])
    job = Job.from_payload(cassette("job_after_approve")["body"])

    assert whoami.operations_remaining == 500
    assert job.usage is not None
    assert job.usage.bucket_used == "promo"
    # Recorded after two chat turns, so the promo bucket has spent two of its 10,000.
    assert job.usage.promo_remaining == 9998
    assert job.usage.total_remaining == 500 + 9998


def test_pending_changes_parse_from_the_recorded_awaiting_approval_job():
    job = Job.from_payload(cassette("job_awaiting_approval")["body"])

    assert job.status is JobStatus.AWAITING_APPROVAL
    assert len(job.pending_changes) == 2
    first = job.pending_changes[0]
    assert first.old_html is not None and "utilise" in first.old_html
    assert first.new_html is not None and "We use the API to fetch results." in first.new_html
    assert first.target_chunk_id  # anchors to a real chunk


def test_document_upload_parses_the_recorded_chunk_manifest():
    body = cassette("document_upload")["body"]
    upload = DocumentUpload.from_payload(body, session_id="s")

    assert upload.chunks_count == 4
    assert len(upload.chunk_ids) == 4
    assert all("-" in cid for cid in upload.chunk_ids), "live chunk ids are UUIDs"


def test_attachment_status_parses_the_recorded_two_array_shape():
    status = AttachmentStatus.from_payload(cassette("attachment_status")["body"], session_id="s")

    assert len(status.ready) == 1
    assert status.ready[0].filename == "styleguide.md"
    assert status.find_ready(filename="styleguide.md") is not None


def test_job_usage_records_a_turn_that_was_billed_for_producing_nothing():
    """BUGS.md #2, pinned. was_billable is true and ops_charged is 1 on a no-action turn."""
    usage = JobUsage.from_payload(cassette("job_after_approve")["body"]["result"]["usage"])
    assert usage is not None
    assert usage.was_billable is True
    assert usage.ops_charged == 1


def test_usage_from_fake_matches_the_same_shape(client):
    usage = client.usage()
    assert usage.monthly_limit == 500
    assert usage.operations_remaining == 500


# -- the double-encoding trap -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"<p>hello</p>"', "<p>hello</p>"),  # JSON-encoded string: needs the second parse
        ("<p>hello</p>", "<p>hello</p>"),  # already plain: must survive untouched
        ("just prose, not JSON", "just prose, not JSON"),
        ('{"broken', '{"broken'),  # looks like JSON, is not: returned unchanged
        (None, None),
    ],
)
def test_decode_maybe_json_string_handles_both_encodings(raw, expected):
    assert decode_maybe_json_string(raw) == expected


def test_proposal_content_is_decoded_not_left_as_a_quoted_string(client):
    """Missing the second parse is what produces diff cards full of `undefined`."""
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    job = client.poll_job(job_id, poll_interval=0)

    assert job.status is JobStatus.AWAITING_APPROVAL
    assert job.pending_changes
    for change in job.pending_changes:
        assert change.new_html is not None
        assert change.new_html.startswith("<"), f"still encoded: {change.new_html!r}"


# -- chunk manifest -----------------------------------------------------------------


def test_upload_returns_a_chunk_manifest(client):
    upload = client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    assert upload.chunks_count == len(upload.chunk_ids) > 0


def test_extract_chunk_ids_preserves_order_and_dedupes():
    html = '<h1 data-chunk-id="c1">A</h1><p data-chunk-id="c2">B</p><p data-chunk-id="c1">A</p>'
    assert extract_chunk_ids(html) == ["c1", "c2"]


# -- attachments (the style guide) --------------------------------------------------


def test_upload_reference_returns_a_job_id_not_an_attachment_id(client):
    """BUGS.md #5. The type refuses to let you mistake one for the other."""
    upload = client.upload_reference("styleguide.md", b"# Style", session_id="s1")
    assert upload.job_id
    assert not hasattr(upload, "attachment_id")


def test_wait_for_attachment_resolves_the_real_id_once_processing_completes(client, set_fault):
    set_fault(attachment_polls_until_ready=3)
    upload = client.upload_reference("styleguide.md", b"# Style\nUse plain words.", session_id="s1")

    ready = client.wait_for_attachment(upload, poll_interval=0)
    assert ready.attachment_id
    assert ready.attachment_id != upload.job_id, "the attachment id is not the upload job id"
    assert ready.filename == "styleguide.md"


def test_wait_for_attachment_times_out_rather_than_hanging(client, set_fault):
    set_fault(attachment_polls_until_ready=9999)
    upload = client.upload_reference("styleguide.md", b"# Style", session_id="s1")
    with pytest.raises(SuperDocsJobTimeout):
        client.wait_for_attachment(upload, timeout=0.05, poll_interval=0)


# -- the gate -----------------------------------------------------------------------


def test_job_pauses_for_approval_and_does_not_apply_anything_first(client):
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    job = client.poll_job(job_id, poll_interval=0)

    assert job.status is JobStatus.AWAITING_APPROVAL
    assert job.awaiting_kind == "approval"
    # Nothing has landed: the document still reads exactly as uploaded.
    assert client.export(session_id="s1") == SAMPLE_DOC


def test_rejecting_one_change_keeps_the_others_and_leaves_its_text_untouched(client):
    """The behaviour the brief names explicitly: reject one, the rest survive."""
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    job = client.poll_job(job_id, poll_interval=0)
    assert len(job.pending_changes) >= 2

    first, *rest = job.pending_changes
    client.approve(
        session_id="s1",
        job_id=job_id,
        decisions=[(first.change_id, False)] + [(c.change_id, True) for c in rest],
    )

    exported = client.export(session_id="s1")
    # The rejected paragraph is byte-identical to what was uploaded.
    assert "We utilise the API in order to fetch results." in exported
    # The approved ones landed.
    assert "You can use the client for batch work." in exported
    # And the paragraph nobody proposed anything for is untouched.
    assert "This paragraph is already fine and must not change." in exported


def test_approve_defaults_to_rejecting_anything_not_listed(client):
    """An unlisted change must not sneak in on the batch default."""
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    job = client.poll_job(job_id, poll_interval=0)

    only_one = job.pending_changes[0]
    client.approve(session_id="s1", job_id=job_id, decisions=[(only_one.change_id, True)])

    exported = client.export(session_id="s1")
    assert "You can leverage the client for batch work." in exported, "unlisted change was applied"


def test_approve_refuses_an_empty_decision_set(client):
    with pytest.raises(ValueError):
        client.approve(session_id="s1", job_id="j", decisions=[])


def test_continue_prompt_is_distinguished_from_an_approval_pause(client, set_fault):
    set_fault(continue_prompt_first=True)
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")

    job = client.poll_job(job_id, poll_interval=0)
    assert job.is_continue_prompt, "a large-edit pause must not be mistaken for a review"

    client.continue_chat(session_id="s1", job_id=job_id, proceed=True)
    resumed = client.poll_job(job_id, poll_interval=0)
    assert resumed.status is JobStatus.AWAITING_APPROVAL
    assert not resumed.is_continue_prompt


def test_a_clean_document_completes_with_no_proposals(client):
    """An honest report of no findings, not an invented one."""
    clean = b"# Title\n\nThis prose is perfectly fine.\n"
    client.upload_document("clean.md", clean, session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    job = client.poll_job(job_id, poll_interval=0)

    assert job.status is JobStatus.COMPLETED
    assert job.pending_changes == ()


# -- one active job per session, the constraint that shaped the architecture ---------


def test_a_second_job_in_a_busy_session_is_refused_with_a_typed_retryable_error(client):
    """BUGS.md #8. A job parked awaiting approval holds its session against all comers."""
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    parked = client.poll_job(job_id, poll_interval=0)
    assert parked.status is JobStatus.AWAITING_APPROVAL

    with pytest.raises(SuperDocsSessionBusy) as raised:
        client.start_async_chat(session_id="s1", message="lint again")
    assert raised.value.active_jobs == 1
    assert raised.value.retryable, "transient conflict, not a permanent client error"


def test_each_document_gets_its_own_session_so_a_parked_review_blocks_nobody(client):
    """Why docs-lint uses one session per document rather than one per run."""
    for session in ("doc-a", "doc-b"):
        client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id=session)

    first = client.start_async_chat(session_id="doc-a", message="lint")
    client.poll_job(first, poll_interval=0)  # parked awaiting approval

    # A different document is entirely unaffected.
    second = client.start_async_chat(session_id="doc-b", message="lint")
    assert client.poll_job(second, poll_interval=0).status is JobStatus.AWAITING_APPROVAL


def test_cancelling_a_parked_job_frees_its_session(client):
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    client.poll_job(job_id, poll_interval=0)

    client.cancel_job(job_id)
    assert client.start_async_chat(session_id="s1", message="lint again")


def test_list_jobs_finds_work_a_killed_run_left_behind(client):
    """The rediscovery path for a resumed run: the proposals are still there, already paid for."""
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    client.poll_job(job_id, poll_interval=0)

    found = client.list_jobs(session_id="s1")
    assert [j.job_id for j in found] == [job_id]
    assert found[0].status is JobStatus.AWAITING_APPROVAL


# -- honesty ------------------------------------------------------------------------


def test_a_refused_turn_is_visible_as_producing_nothing_despite_completing(client, set_fault):
    """BUGS.md #2 and #3: billed, status completed, no findings, no edit.

    The run must not read this as a clean document.
    """
    set_fault(refuse_to_act=True)
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="please consider proposing")
    job = client.poll_job(job_id, poll_interval=0)

    assert job.status is JobStatus.COMPLETED
    assert job.produced_nothing
    assert job.response_text is not None
    assert "wasn't able to determine an action" in job.response_text
    assert job.usage is not None and job.usage.ops_charged == 1


# -- retries and failure ------------------------------------------------------------


def test_transient_failures_are_retried_then_succeed(client, set_fault):
    set_fault(fail_next=2, fail_status=503)
    usage = client.usage()
    assert usage.monthly_limit == 500
    assert client.log.retries == 2


def test_retries_are_bounded_and_then_give_up(client, set_fault):
    set_fault(fail_next=99, fail_status=503)
    with pytest.raises(SuperDocsUnavailable):
        client.usage()
    assert client.log.retries == 3  # max_attempts=4 means three retries


def test_auth_failure_is_not_retried(base_url):
    with SuperDocsClient(
        api_key="sk_wrong",
        base_url=base_url,
        retry=RetryPolicy(max_attempts=4, base_delay=0.0, jitter=False),
        sleep=lambda _s: None,
    ) as wrong:
        with pytest.raises(SuperDocsAuthError):
            wrong.usage()
        assert wrong.log.retries == 0, "a bad key will still be bad on the fourth try"


def test_rate_limit_is_retryable_and_reads_retry_after(client, set_fault):
    slept: list[float] = []
    client._sleep = slept.append
    set_fault(fail_next=1, fail_status=429, retry_after=1.5)

    client.usage()
    assert slept == [1.5]


def test_rate_limit_exhaustion_raises_the_typed_error(client, set_fault):
    set_fault(fail_next=99, fail_status=429)
    with pytest.raises(SuperDocsRateLimited):
        client.usage()


def test_client_errors_are_not_retried(client, set_fault):
    set_fault(fail_next=99, fail_status=400)
    with pytest.raises(SuperDocsBadRequest):
        client.usage()
    assert client.log.retries == 0


def test_poll_job_times_out_carrying_the_job_id_so_work_can_be_resumed(client, set_fault):
    set_fault(job_polls_until_proposals=9999)
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")

    with pytest.raises(SuperDocsJobTimeout) as raised:
        client.poll_job(job_id, timeout=0.05, poll_interval=0)
    assert raised.value.job_id == job_id, "without the id the run would have to pay again"


# -- secrets ------------------------------------------------------------------------


def test_the_api_key_never_appears_in_repr_or_redacted_text(base_url):
    with SuperDocsClient(api_key=DEFAULT_API_KEY, base_url=base_url) as instance:
        assert DEFAULT_API_KEY not in repr(instance)
        leaky = f"request failed with key {DEFAULT_API_KEY} attached"
        assert DEFAULT_API_KEY not in instance.redact(leaky)
        assert "sk_***" in instance.redact(leaky)


def test_a_missing_key_fails_immediately_with_a_useful_message(monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    with pytest.raises(SuperDocsAuthError, match="SUPERDOCS_API_KEY"):
        SuperDocsClient()


# -- cost accounting ----------------------------------------------------------------


def test_run_cost_comes_from_the_job_not_from_a_whoami_delta(client, fake_state):
    """Cost must be read off `result.usage.ops_charged`.

    Sampling whoami either side of a run - the obvious approach, and the one this project
    originally planned - measures nothing, because whoami reports only the free-tier counter
    while the work is billed against a promo bucket it never mentions (BUGS.md #1).
    """
    before = client.usage()
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    job_id = client.start_async_chat(session_id="s1", message="lint")
    job = client.poll_job(job_id, poll_interval=0)
    client.approve(
        session_id="s1",
        job_id=job_id,
        decisions=[(c.change_id, True) for c in job.pending_changes],
    )
    completed = client.get_job(job_id)
    client.export(session_id="s1")
    after = client.usage()

    # The whoami delta is zero even though an operation was certainly spent.
    assert (before.operations_remaining or 0) - (after.operations_remaining or 0) == 0
    # The job tells the truth.
    assert completed.usage is not None
    assert completed.usage.ops_charged == 1
    assert fake_state()["operations_used"] == 1

    # And the client's own log accounts for where the requests went.
    assert client.log.by_endpoint["/v1/chat/async"] == 1
    assert client.log.requests > 0


def test_export_does_not_cost_an_operation(client, fake_state):
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    before = fake_state()["operations_used"]
    client.export(session_id="s1")
    client.export(session_id="s1", fmt="markdown")
    assert fake_state()["operations_used"] == before


def test_export_handles_a_raw_body_rather_than_json(client):
    """BUGS.md #7: export returns the file itself, not the documented JSON object."""
    client.upload_document("doc.md", SAMPLE_DOC.encode(), session_id="s1")
    exported = client.export(session_id="s1", fmt="markdown")
    assert exported.startswith("# Getting Started")
