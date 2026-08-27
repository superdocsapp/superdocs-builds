"""Keyless. No network. These prove the card's claims, not the fake's."""

import pytest

from quota_aware_agent import QuotaAwareAgent, Step, SuperDocsClient, parse_proposed_changes
from quota_aware_agent.client import QuotaExhausted
from quota_aware_agent.policy import Policy
from tests.fake import FakeSuperDocs

DOC = b"a document"


def agent(fake, **kw):
    return QuotaAwareAgent(SuperDocsClient(fake, sleep=lambda s: None),
                           policy=Policy(**kw))


def steps(n, sections=1, severity="medium"):
    return [Step(f"s{i}", f"edit {i}", sections, severity) for i in range(1, n + 1)]


def test_reads_allowance_before_it_plans_or_uploads():
    """The card's actual requirement: allowance first, then planning."""
    fake = FakeSuperDocs(remaining=500)
    agent(fake).run("sess", "d.html", DOC, steps(1))
    paths = [p for _, p in fake.calls]
    assert paths[0] == "/v1/agents/whoami"
    assert paths.index("/v1/agents/whoami") < paths.index("/v1/documents/upload")


def test_never_starts_work_it_cannot_finish():
    """One operation left, all of it reserved. Nothing is uploaded at all --
    the point is that no half-applied state exists, not that it fails politely."""
    fake = FakeSuperDocs(remaining=1)
    report = agent(fake, reserve=1).run("sess", "d.html", DOC, steps(3))
    assert report.completed == []
    assert "/v1/documents/upload" not in [p for _, p in fake.calls]
    assert "did not start" in report.plain_language().lower()
    assert report.stopped_because


def test_degrades_by_severity_and_says_what_it_left_out():
    """Two operations of room, four operations of work. Critical work survives,
    low-severity work is named as deferred in plain language."""
    fake = FakeSuperDocs(remaining=3)
    work = [
        Step("critical", "fix the numbers", 25, "critical"),
        Step("low", "tidy the footer", 25, "low"),
        Step("high", "fix the dates", 25, "high"),
    ]
    report = agent(fake, reserve=1).run("sess", "d.html", DOC, work)
    assert "critical" in report.planned
    assert "low" in report.deferred
    text = report.plain_language()
    assert "Left undone" in text and "low" in text
    assert "operations" in text


def test_the_four_calls_happen_in_order():
    fake = FakeSuperDocs(remaining=500)
    agent(fake).run("sess", "d.html", DOC, steps(1))
    paths = [p for _, p in fake.calls]
    assert paths.index("/v1/documents/upload") < paths.index("/v1/chat/async")
    assert paths.index("/v1/chat/async") < [i for i, p in enumerate(paths) if p.endswith("/approve")][0]
    assert paths.index("/v1/documents/export") == len(paths) - 1


def test_trap_1_the_double_parse():
    """A batch whose content is a JSON string must survive the second parse."""
    import json
    envelope = {"content": json.dumps({"changes": [{"change_id": "ch_9"}]})}
    assert parse_proposed_changes(envelope) == [{"change_id": "ch_9"}]


def test_trap_1_end_to_end_the_change_is_actually_approved():
    """The regression the docs warn about is silent: undefined fields, nothing
    approved, no error. So assert the change id arrived, not just that it ran."""
    fake = FakeSuperDocs(remaining=500)
    agent(fake).run("sess", "d.html", DOC, steps(1))
    assert fake.approved == [{"change_id": "ch_1", "approved": True}]


def test_trap_2_a_long_silence_is_not_a_crash():
    fake = FakeSuperDocs(remaining=500, slow_polls=5)
    report = agent(fake).run("sess", "d.html", DOC, steps(1))
    assert report.completed == ["s1"]


def test_trap_2_a_deadline_says_it_is_our_deadline_not_a_platform_failure():
    fake = FakeSuperDocs(remaining=500, slow_polls=10_000)
    client = SuperDocsClient(fake, sleep=lambda s: None)
    client.edit("sess", "go")
    with pytest.raises(TimeoutError) as e:
        client.poll_job("job-1", deadline_s=4, interval_s=2)
    assert "not a platform failure" in str(e.value)


def test_trap_3_small_sample_mode_bounds_the_loop():
    fake = FakeSuperDocs(remaining=500)
    report = agent(fake, max_steps=2).run("sess", "d.html", DOC, steps(10))
    assert len(report.completed) == 2
    assert "Small-sample mode" in report.plain_language()


def test_the_platform_signal_stops_it_even_with_budget_left():
    """quota_exhausted is authoritative. Our own arithmetic is not."""
    fake = FakeSuperDocs(remaining=500, exhaust_after=1)
    report = agent(fake).run("sess", "d.html", DOC, steps(3))
    assert "exhausted" in report.stopped_because
    assert len(report.completed) < 3


def test_it_still_exports_after_stopping_early():
    """Exports are free, so stopping early must never cost the user the work
    already done."""
    fake = FakeSuperDocs(remaining=500, exhaust_after=1)
    agent(fake).run("sess", "d.html", DOC, steps(3))
    assert "/v1/documents/export" in [p for _, p in fake.calls]


def test_export_warnings_are_surfaced_not_swallowed():
    fake = FakeSuperDocs(remaining=500)
    report = agent(fake).run("sess", "d.html", DOC, steps(1))
    assert report.export_warnings
    assert "non-fatal" in report.plain_language()


def test_a_balance_between_calls_is_never_presented_as_a_live_read():
    """BUG-003: the usage endpoints reject API keys, so the number is only
    authoritative at whoami and after each response."""
    from quota_aware_agent import BudgetGuard
    g = BudgetGuard()
    g.seed_from_whoami(500)
    assert g.remaining().authoritative
    g.reconcile(ops_charged=1, monthly_remaining=None, quota_exhausted=False)
    assert not g.remaining().authoritative
    assert "estimated" in str(g.remaining())


def test_an_unknown_allowance_is_planned_as_zero_never_guessed():
    class NoQuota(FakeSuperDocs):
        def request(self, method, path, **kw):
            if path == "/v1/agents/whoami":
                return __import__("quota_aware_agent.client", fromlist=["Response"]).Response(200, {})
            return super().request(method, path, **kw)

    fake = NoQuota(remaining=500)
    report = agent(fake).run("sess", "d.html", DOC, steps(2))
    assert report.completed == []
    assert report.balance_at_start.ops == 0


# -- gaps found by running the contract against the live API, 2026-08-19 -----

def test_the_transport_actually_encodes_multipart():
    """The four-call contract passed for weeks against a fake that accepted any
    kwargs, while `HttpTransport` dropped `files=` entirely and the real
    endpoint answered 422. A fake that accepts anything proves nothing."""
    from quota_aware_agent.client import _encode_multipart

    body, ctype = _encode_multipart(
        {"file": ("memo.docx", b"CONTENT-BYTES")}, {"session_id": "s1"}
    )
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=")[1]
    assert b'name="file"; filename="memo.docx"' in body
    assert b"CONTENT-BYTES" in body
    assert b'name="session_id"' in body and b"s1" in body
    assert body.rstrip().endswith(f"--{boundary}--".encode())


def test_an_upload_without_a_file_part_is_refused_by_the_fake_too():
    """Pins the contract the live API enforces, so the transport cannot
    regress to sending nothing."""
    fake = FakeSuperDocs(remaining=500)
    from quota_aware_agent.client import SuperDocsError

    with pytest.raises(SuperDocsError) as e:
        SuperDocsClient(fake, sleep=lambda s: None)._check(
            fake.request("POST", "/v1/documents/upload", json={"session_id": "s"})
        )
    assert e.value.status == 422


def test_it_waits_for_the_job_to_settle_before_exporting():
    """Approval is asynchronous. The approve call returns ok and the job keeps
    running; exporting before it completes returns the document unchanged with
    a 200 and a valid file, so the loss is silent. Verified live."""
    fake = FakeSuperDocs(remaining=500, settle_polls=2)
    agent(fake).run("sess", "d.html", DOC, steps(1))

    paths = [p for _, p in fake.calls]
    approve_at = next(i for i, p in enumerate(paths) if p.endswith("/approve"))
    export_at = paths.index("/v1/documents/export")
    polls_between = [p for p in paths[approve_at:export_at] if p.startswith("/v1/jobs/")]
    assert polls_between, "exported without waiting for the job to settle after approving"


def test_pending_changes_as_a_plain_list_is_handled():
    """GET /v1/jobs/{id} returns `pending_changes` as a list, not the
    double-parsed envelope the SSE stream delivers. Both shapes must work."""
    for envelope in (False, True):
        fake = FakeSuperDocs(remaining=500, envelope_pending=envelope)
        agent(fake).run("sess", "d.html", DOC, steps(1))
        assert fake.approved == [{"change_id": "ch_1", "approved": True}], \
            f"envelope={envelope} failed to approve the change"


def test_a_billable_call_with_no_usage_block_stops_claiming_confirmed():
    """The docs say usage rides on every chat response. The async endpoints
    return none, so the agent kept printing the seeded whoami number as
    "confirmed" while the true balance had already moved — 499 confirmed
    against a real 498. A guess must announce itself as a guess."""
    class NoUsage(FakeSuperDocs):
        def request(self, method, path, **kw):
            r = super().request(method, path, **kw)
            if isinstance(r.body, dict):
                r.body.pop("usage", None)
            return r

    fake = NoUsage(remaining=500)
    report = agent(fake).run("sess", "d.html", DOC, steps(1))

    assert report.balance_at_start.authoritative      # whoami is real
    assert not report.balance_at_end.authoritative    # everything after is not
    assert "estimated" in str(report.balance_at_end)
    assert report.balance_at_end.ops < report.balance_at_start.ops
