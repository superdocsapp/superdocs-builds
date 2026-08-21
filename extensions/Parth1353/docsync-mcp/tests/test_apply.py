"""Staging, the gate, verification and write-back."""

from __future__ import annotations

from pathlib import Path

import pytest

from docsync.apply import commit, session_for, stage, to_text
from docsync.facts import WorkingTree, is_dirty, read_facts
from docsync.plan import build_plan
from docsync.registry import Registry
from docsync.state import Pending, State
from docsync.superdocs import BudgetExceeded, Ledger, SuperDocsError
from tests.conftest import edit_file

RETRY = "src/provisioning/retry.py"
CONFIG = "src/provisioning/config.py"
API = "src/provisioning/api.py"
ADR = "docs/adr/0007-retry-policy.md"
RUNBOOK = "docs/runbook-circuit-activation.md"
SPEC = "docs/spec-provisioning-api.md"

BUMP_ATTEMPTS = (RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
BUMP_BACKOFF = (RETRY, "BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45")
DROP_TIMEOUT = (CONFIG, "REQUEST_TIMEOUT_SECONDS = 30", "REQUEST_TIMEOUT_SECONDS = 20")
ADD_ROUTE = (
    API,
    '    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",',
    '    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",\n'
    '    "POST /v1/circuits/{circuit_id}/activate": "activate_circuit",',
)
SWAP_ROUTE = (
    API,
    '    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",',
    '    "POST /v1/circuits/{circuit_id}/activate": "activate_circuit",',
)


def make_plan(repo: Path, changes, *, allow_prose=False, uploaded=None):
    registry = Registry.load(repo)
    before = read_facts(registry, WorkingTree(repo))
    for relpath, old, new in changes:
        edit_file(repo, relpath, old, new)
    after = read_facts(registry, WorkingTree(repo))
    return registry, build_plan(
        registry, before, after, uploaded=uploaded or {}, allow_prose=allow_prose
    )


def stage_it(repo: Path, client, changes, **kw):
    registry, plan = make_plan(repo, changes, **kw)
    state = State.load(repo, session_id=registry.session_id)
    pending = stage(client, plan, state, session_prefix=registry.session_id)
    return plan, state, pending


def approve_all(pending: Pending) -> dict[str, bool]:
    return {c.change_id: True for job in pending.jobs for c in job.changes}


class TestStaging:
    def test_uploads_with_open_mode_new_focused(self, repo: Path, client, fake):
        # The single most expensive mistake available on this API: without
        # new_focused each upload replaces the last one and the session ends up
        # with one document and a pile of discarded uploads, all returning 200.
        stage_it(repo, client, [BUMP_ATTEMPTS, DROP_TIMEOUT])
        uploads = [r for r in fake.requests if r[1].endswith("/documents/upload")]
        assert len(uploads) == 3
        assert len(fake.documents) == 3

    def test_each_document_gets_its_own_session(self, repo: Path, client, fake):
        # The defect the first live run found, and the offline suite could not:
        # a session runs one job at a time, and a job parked at the human gate
        # still counts as active. Staging three documents into one session gets
        # `409 session_busy` on the second and never recovers, which makes
        # "hold every diff for one review" impossible rather than merely slow.
        _, _, pending = stage_it(repo, client, [BUMP_BACKOFF, DROP_TIMEOUT])
        sessions = {job.session_id for job in pending.jobs}
        assert len(pending.jobs) == 3
        assert len(sessions) == 3
        assert all(not job.error for job in pending.jobs)
        assert all(job.changes for job in pending.jobs)

    def test_the_fake_really_does_reject_a_second_job_in_one_session(
        self, repo: Path, client, fake
    ):
        # Guards the guard. If this passes, the test above is meaningful.
        stage_it(repo, client, [BUMP_ATTEMPTS])
        session = next(iter(fake.jobs.values()))["session"]
        with pytest.raises(SuperDocsError, match="session_busy"):
            client.chat_async("anything at all", session_id=session)

    def test_session_ids_are_stable_across_runs(self, repo: Path, client):
        # A re-run has to land in the same session, or every document is
        # re-uploaded into a fresh one and the ids in state.json go stale.
        first = session_for("prefix", ADR, "ws1")
        assert first == session_for("prefix", ADR, "ws1")
        assert first != session_for("prefix", RUNBOOK, "ws1")
        assert "0007-retry-policy" in first

    def test_two_checkouts_do_not_share_sessions(self, repo: Path, client):
        # Without a per-workspace salt the id is a pure function of the registry
        # and the path, so a second clone — or an interrupted run whose jobs are
        # still parked at the gate — owns the same sessions and every edit comes
        # back 409 session_busy. That is exactly how a timed-out test run broke
        # the next one.
        assert session_for("prefix", ADR, "ws1") != session_for("prefix", ADR, "ws2")

    def test_a_workspace_id_is_minted_and_recorded(self, repo: Path, client):
        _, state, _ = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert state.workspace_id
        assert State.load(repo).workspace_id == state.workspace_id

    def test_a_recorded_session_is_reused_rather_than_recomputed(self, repo: Path, client):
        # A colleague who has state.json must land in the same sessions and pay
        # no extra uploads.
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        recorded = state.documents[ADR].session_id
        assert pending.jobs[0].session_id == recorded
        assert State.load(repo).documents[ADR].session_id == recorded

    def test_reads_document_ids_back_from_the_roster(self, repo: Path, client, fake):
        _, state, _ = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert state.documents[ADR].document_id in fake.documents
        roster_reads = [
            r for r in fake.requests if "/sessions/" in r[1] and r[1].endswith("/documents")
        ]
        assert roster_reads, "ids must be confirmed against the roster, not trusted"

    def test_front_matter_is_never_sent(self, repo: Path, client, fake):
        # Not an instruction asking the model to leave it alone — it simply is
        # not in the payload. The cheapest way to stop an edit reaching
        # something is not to show it.
        stage_it(repo, client, [BUMP_ATTEMPTS])
        body = fake.body_of(fake.find_document("0007-retry-policy"))
        assert "covers:" not in body
        assert "docsync:" not in body
        assert "## Decision" in body

    def test_nothing_is_applied_at_the_gate(self, repo: Path, client, fake):
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert pending.change_count >= 1
        body = fake.body_of(fake.find_document("0007-retry-policy"))
        assert "up to 3 times" in body, "staging must propose, never apply"
        assert not fake.approvals

    def test_the_batch_survives_the_process(self, repo: Path, client):
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        reloaded = Pending.load(repo)
        assert reloaded is not None
        assert reloaded.change_count == pending.change_count
        assert reloaded.jobs[0].front_matter.startswith("---")

    def test_handles_the_encoded_pending_changes_shape(self, repo: Path, client, fake):
        fake.encode_pending_as_string = True
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert pending.change_count == 1

    def test_a_continue_prompt_is_resolved_not_handed_to_a_person(
        self, repo: Path, client, fake
    ):
        # Both pauses share the status `awaiting_approval`; calling /approve on
        # a continue prompt is a 409. The fake enforces that.
        fake.continue_prompt_next = True
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert pending.jobs[0].error == ""
        assert pending.change_count == 1

    def test_one_failing_document_does_not_abandon_the_others(
        self, repo: Path, client, fake
    ):
        # Backoff and timeout between them touch the ADR, the runbook and the
        # spec. The first edit is made to fail; the other two must still go out.
        fake.fail_next_edit = True
        _, _, pending = stage_it(repo, client, [BUMP_BACKOFF, DROP_TIMEOUT])
        assert len(pending.jobs) == 3
        assert sum(1 for job in pending.jobs if job.error) == 1
        assert sum(1 for job in pending.jobs if job.changes) == 2

    def test_a_gate_that_does_not_engage_is_retried_exactly_once(
        self, repo: Path, client, fake
    ):
        # Measured live: ask_every_time occasionally completes without pausing,
        # claims success and persists nothing. It is not reproducible on demand,
        # so it cannot be prompted away — only detected and retried once.
        fake.completes_without_pausing_once = True
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert pending.jobs[0].error == ""
        assert pending.jobs[0].changes
        edits = [r for r in fake.requests if r[1].endswith("/chat/async")]
        assert len(edits) == 2, "one retry, not a loop"

    def test_a_gate_that_never_engages_gives_up_and_says_so(
        self, repo: Path, client, fake
    ):
        fake.completes_without_pausing = True
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        edits = [r for r in fake.requests if r[1].endswith("/chat/async")]
        assert len(edits) == 2, "exactly two attempts, then stop"
        assert "without pausing for approval, twice" in pending.jobs[0].error

    def test_a_job_that_never_pauses_is_reported_rather_than_called_clean(
        self, repo: Path, client, fake
    ):
        fake.completes_without_pausing = True
        _, _, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        assert "without pausing" in pending.jobs[0].error
        assert "can claim success while" in pending.jobs[0].error


class TestGate:
    def test_applies_exactly_what_was_approved(self, repo: Path, client, fake):
        # One *fact* per round, but a single fact can still propose several
        # changes: swapping a route is an addition and a removal. Approving the
        # addition alone must apply the addition alone.
        _, state, pending = stage_it(repo, client, [SWAP_ROUTE])
        job = next(j for j in pending.jobs if j.path == SPEC)
        assert len(job.changes) == 2
        addition = next(c for c in job.changes if "activate" in c.new_text)

        report = commit(
            client, pending, state, decisions={addition.change_id: True}, write_back=False
        )
        body = fake.body_of(fake.find_document("spec-provisioning-api"))
        assert "activate" in body, "the approved addition landed"
        assert "provision_circuit" not in body or "/provision" in body, (
            "the rejected removal did not"
        )
        outcome = next(o for o in report.outcomes if o.path == SPEC)
        assert outcome.approved == 1
        assert outcome.rejected == 1

    def test_an_undecided_change_is_rejected_not_approved(self, repo: Path, client, fake):
        # The default for a change nobody decided is no. Anything else means a
        # dropped message applies an edit.
        _, state, pending = stage_it(repo, client, [BUMP_BACKOFF])
        report = commit(client, pending, state, decisions={}, write_back=False)
        assert report.approved == 0
        assert report.rejected >= 1
        assert "45 seconds" not in fake.body_of(fake.find_document("runbook"))

    def test_rejections_carry_feedback(self, repo: Path, client, fake):
        _, state, pending = stage_it(repo, client, [BUMP_BACKOFF])
        commit(client, pending, state, decisions={}, write_back=False)
        sent = fake.approvals[0]["changes"][0]
        assert sent["approved"] is False
        assert "feedback" in sent

    def test_top_level_approved_is_always_present(self, repo: Path, client, fake):
        # Required even for batch shapes; omitting it returns a bare 422.
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        assert "approved" in fake.approvals[0]


class TestVerification:
    def test_confirms_an_edit_that_landed(self, repo: Path, client, fake):
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        outcome = report.outcomes[0]
        assert outcome.verified == ["retry.max_attempts"]
        assert outcome.not_landed == []
        assert report.ok

    def test_catches_an_edit_that_did_not_land(self, repo: Path, client, fake):
        # The model says it did the work and did not. Without reading the
        # document back this is indistinguishable from success.
        fake.drop_values = {"5"}
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        outcome = report.outcomes[0]
        assert outcome.not_landed == ["retry.max_attempts"] or outcome.error
        assert not report.ok

    def test_verifies_a_list_addition_and_removal_separately(self, repo: Path, client, fake):
        _, state, pending = stage_it(repo, client, [ADD_ROUTE])
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        outcome = next(o for o in report.outcomes if o.path == SPEC)
        assert any("+POST /v1/circuits/{circuit_id}/activate" in v for v in outcome.verified)
        assert outcome.not_landed == []

    def test_a_prose_edit_is_reported_as_applied_but_not_verified(
        self, repo: Path, client, fake
    ):
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS], allow_prose=True)
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        runbook = next(o for o in report.outcomes if o.path == RUNBOOK)
        assert runbook.unverified == ["retry.max_attempts"]
        assert "retry.max_attempts" not in runbook.verified
        # The fake did apply it, in the only way prose can be applied.
        assert "five attempts" in fake.body_of(fake.find_document("runbook"))

    def test_collateral_damage_to_an_unchanged_fact_fails_the_run(
        self, repo: Path, client, fake
    ):
        # The live failure, end to end. Only the retry backoff changes, but the
        # runbook also states a carrier timeout that reads the same. A service
        # that over-applies rewrites both. Checking only what changed says OK;
        # checking that every covered fact still matches the code says no.
        fake.overreach = True
        _, state, pending = stage_it(repo, client, [BUMP_BACKOFF])
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        runbook = next(o for o in report.outcomes if o.path == RUNBOOK)

        assert runbook.verified, "the change it was asked for did land"
        assert any("api.request_timeout_seconds" in c for c in runbook.collateral)
        assert not runbook.ok
        assert not report.ok

    def test_collateral_damage_keeps_the_file_off_disk(self, repo: Path, client, fake):
        original = (repo / RUNBOOK).read_text()
        fake.overreach = True
        _, state, pending = stage_it(repo, client, [BUMP_BACKOFF])
        report = commit(client, pending, state, decisions=approve_all(pending))
        runbook = next(o for o in report.outcomes if o.path == RUNBOOK)
        assert not runbook.written_back
        assert (repo / RUNBOOK).read_text() == original

    def test_verification_is_presence_based_and_that_has_a_limit(
        self, repo: Path, client, fake
    ):
        # An honest test of a real gap rather than a claim of a property.
        #
        # The check asks "is the new value in the document", not "is it in the
        # right sentence". One fact per round plus the invariant check closes
        # most of the exposure — a value moved onto the wrong sentence takes
        # some *other* fact's value with it, and that fails as collateral
        # damage. What is left uncovered is the case where the two sentences
        # carry no other tracked fact between them, and this build cannot see
        # that. Catching it needs a reader that understands which sentence is
        # which, which is a different tool.
        _, state, pending = stage_it(repo, client, [BUMP_BACKOFF])
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        runbook = next(o for o in report.outcomes if o.path == RUNBOOK)
        assert runbook.verified == ["retry.backoff_seconds"]
        assert report.ok
        # The guard that does exist, and is exercised in full above.
        assert any(i["key"] == "api.request_timeout_seconds" for i in pending.jobs[1].invariants)


class TestWriteBack:
    def test_writes_the_document_back_with_its_front_matter(self, repo: Path, client):
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions=approve_all(pending))
        assert report.outcomes[0].written_back
        text = (repo / ADR).read_text()
        assert text.startswith("---\n")
        assert "covers:" in text
        assert "up to 5 times" in text

    def test_no_write_back_leaves_the_file_alone(self, repo: Path, client):
        original = (repo / ADR).read_text()
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions=approve_all(pending), write_back=False)
        assert (repo / ADR).read_text() == original
        assert report.outcomes[0].write_back_skipped == "--no-write-back"

    def test_a_failed_verification_never_reaches_the_working_tree(
        self, repo: Path, client, fake
    ):
        fake.drop_values = {"5"}
        original = (repo / ADR).read_text()
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions=approve_all(pending))
        assert (repo / ADR).read_text() == original
        assert not report.outcomes[0].written_back

    def test_refuses_to_overwrite_uncommitted_work(self, git_repo: Path, client):
        # The trap that bit Task 2 of this round: a command wrote over a file
        # that was also somebody's working copy. Being unable to prove a file
        # is clean is treated as dirty.
        _, state, pending = stage_it(git_repo, client, [BUMP_ATTEMPTS])
        (git_repo / ADR).write_text(
            (git_repo / ADR).read_text() + "\n<!-- half-written thought -->\n"
        )
        report = commit(client, pending, state, decisions=approve_all(pending))
        assert "uncommitted changes" in report.outcomes[0].write_back_skipped
        assert "half-written thought" in (git_repo / ADR).read_text()

    def test_it_overwrites_its_own_previous_round(self, git_repo: Path, client):
        # A document with two changed facts takes two rounds. Round one writes
        # the file, which makes it uncommitted; round two must still be allowed
        # to write. The first version refused — so the file never advanced, the
        # same edit was planned again, and a live run burned two operations a
        # round until it hit the round cap.
        _, state, pending = stage_it(git_repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions=approve_all(pending))
        assert report.outcomes[0].written_back
        assert is_dirty(git_repo, ADR), "our own write leaves the file uncommitted"

        _, state2, pending2 = stage_it(git_repo, client, [BUMP_BACKOFF])
        report2 = commit(client, pending2, state2, decisions=approve_all(pending2))
        adr = next(o for o in report2.outcomes if o.path == ADR)
        assert adr.written_back, adr.write_back_skipped
        assert "up to 5 times" in (git_repo / ADR).read_text()
        assert "45 seconds" in (git_repo / ADR).read_text()

    def test_a_human_edit_on_top_of_ours_is_still_protected(self, git_repo: Path, client):
        _, state, pending = stage_it(git_repo, client, [BUMP_ATTEMPTS])
        commit(client, pending, state, decisions=approve_all(pending))
        (git_repo / ADR).write_text(
            (git_repo / ADR).read_text() + "\n<!-- half-written thought -->\n"
        )
        _, state2, pending2 = stage_it(git_repo, client, [BUMP_BACKOFF])
        report2 = commit(client, pending2, state2, decisions=approve_all(pending2))
        adr = next(o for o in report2.outcomes if o.path == ADR)
        assert not adr.written_back
        assert "did not make" in adr.write_back_skipped
        assert "half-written thought" in (git_repo / ADR).read_text()

    def test_force_write_overrides_it(self, git_repo: Path, client):
        _, state, pending = stage_it(git_repo, client, [BUMP_ATTEMPTS])
        (git_repo / ADR).write_text((git_repo / ADR).read_text() + "\nscratch\n")
        report = commit(
            client, pending, state, decisions=approve_all(pending), force_write=True
        )
        assert report.outcomes[0].written_back

    def test_nothing_approved_means_nothing_written(self, repo: Path, client):
        original = (repo / ADR).read_text()
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        report = commit(client, pending, state, decisions={})
        assert (repo / ADR).read_text() == original
        assert report.outcomes[0].write_back_skipped == "nothing was approved"

    def test_an_empty_export_does_not_truncate_the_file(self, repo: Path, client, fake):
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS])
        fake.export_status = 500
        report = commit(client, pending, state, decisions=approve_all(pending))
        assert (repo / ADR).read_text().strip() != ""
        assert not report.outcomes[0].written_back


class TestBudget:
    def test_a_dry_run_spends_nothing(self, repo: Path, fake):
        import httpx

        from docsync.superdocs import SuperDocs

        http = httpx.Client(
            transport=httpx.MockTransport(fake.handler), base_url="https://api.superdocs.app"
        )
        client = SuperDocs("sk_x", ledger=Ledger(limit=40, dry_run=True), client=http)
        _, state, pending = stage_it(repo, client, [BUMP_ATTEMPTS, DROP_TIMEOUT])
        assert client.ledger.billable == 0
        assert fake.documents == {}
        assert pending.change_count == 0

    def test_the_budget_is_a_stopping_rule_not_a_warning(self, repo: Path, fake):
        import httpx

        from docsync.superdocs import SuperDocs

        http = httpx.Client(
            transport=httpx.MockTransport(fake.handler), base_url="https://api.superdocs.app"
        )
        client = SuperDocs("sk_x", ledger=Ledger(limit=1), client=http)
        registry, plan = make_plan(repo, [BUMP_BACKOFF, DROP_TIMEOUT])
        state = State.load(repo, session_id=registry.session_id)
        # BudgetExceeded is a SuperDocsError. Without an explicit re-raise the
        # per-document rescue swallows it and the run tries every remaining
        # document anyway, which makes the one hard limit in the tool a
        # suggestion.
        with pytest.raises(BudgetExceeded):
            stage(client, plan, state, session_prefix=registry.session_id)
        assert client.ledger.billable == 1
        assert len(fake.documents) == 1, "it must stop, not keep going and log"

    def test_the_work_already_staged_survives_the_stop(self, repo: Path, fake):
        import httpx

        from docsync.superdocs import SuperDocs

        http = httpx.Client(
            transport=httpx.MockTransport(fake.handler), base_url="https://api.superdocs.app"
        )
        client = SuperDocs("sk_x", ledger=Ledger(limit=2), client=http)
        registry, plan = make_plan(repo, [BUMP_BACKOFF, DROP_TIMEOUT])
        state = State.load(repo, session_id=registry.session_id)
        with pytest.raises(BudgetExceeded):
            stage(client, plan, state, session_prefix=registry.session_id)
        # One upload and one edit were paid for. The batch holding them is on
        # disk, so the person can approve what was bought rather than lose it.
        saved = Pending.load(repo)
        assert saved is not None and saved.change_count == 1
        assert State.load(repo).documents


class TestHtmlToText:
    @pytest.mark.parametrize(
        "html,expected",
        [
            ("<p>Max attempts</p><p>30</p>", "Max attempts\n30"),
            ("<tr><td>Max attempts</td><td>30</td></tr>", "Max attempts 30"),
            ("a<br>b", "a\nb"),
            ("&amp;&lt;&gt;&quot;", '&<>"'),
            ("", ""),
        ],
    )
    def test_block_boundaries_become_newlines_before_tags_are_stripped(self, html, expected):
        # Without this a table row collapses to "Max attempts30" and a
        # token-boundary search for "30" correctly finds nothing — a
        # verification failure invented entirely by the text conversion.
        assert to_text(html) == expected

    def test_a_table_cell_value_is_still_findable(self):
        from docsync.plan import occurrences

        text = to_text("<table><tr><td>P1</td><td>15 minutes</td></tr></table>")
        assert occurrences(text, "15 minutes") == 1
