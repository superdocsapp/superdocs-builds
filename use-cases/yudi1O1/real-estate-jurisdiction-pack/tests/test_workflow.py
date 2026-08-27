"""The four-call contract, the approval gate, and the two failures that look
like successes.

Every network-touching call is behind a duck-typed interface, so these tests run
against a `FakeClient` with no mocking library, no live key, no cost — and,
importantly, no test that merely proves a mock works: the real orchestration,
retry and verification code is what executes.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from _builders import build_pack

from real_estate_pack.assemble import DOCUMENT_ORDER, INDEX, LEASE, PACKET
from real_estate_pack.client import UsageReport
from real_estate_pack.ledger import RunLedger
from real_estate_pack.workflow import (
    DraftNotApplied,
    DraftUnverified,
    PackInconsistent,
    approve_all,
    draft_pack,
)

TEMPLATE_HTML = "<p>CUSTOMER TEMPLATE</p>"


class FakeClient:
    """Stands in for SuperDocs. Scriptable enough to reproduce the two live
    failures that motivated `verify.py`."""

    def __init__(self, doc_set, mode="ok", recover_after=1, approval_rounds=0, continue_rounds=0):
        self.doc_set = doc_set
        self.mode = mode
        self.recover_after = recover_after
        self.approval_rounds = approval_rounds
        self.continue_rounds = continue_rounds
        self.calls: list[tuple[str, str]] = []
        self.usage = UsageReport()
        self.attempts: dict[str, int] = {}
        self.jobs: dict[str, dict] = {}
        self._pending_approvals: dict[str, int] = {}
        self._pending_continues: dict[str, int] = {}

    # -- helpers ---------------------------------------------------------

    def _kind_for(self, session_id: str) -> str:
        for kind in DOCUMENT_ORDER:
            if session_id.endswith(f"-{kind}"):
                return kind
        raise AssertionError(f"session id {session_id!r} does not name a document kind")

    def _attempt(self, session_id: str) -> int:
        return self.attempts.get(session_id, 0)

    # -- the four calls --------------------------------------------------

    def upload_document(self, file_path, session_id, open_mode=None):
        self.calls.append(("upload", session_id))
        self.attempts[session_id] = self._attempt(session_id) + 1
        return {"html": TEMPLATE_HTML}

    def chat_async(self, message, session_id, document_html=None, **extra):
        self.calls.append(("chat", session_id))
        assert extra.get("approval_mode") == "ask_every_time", "HITL must be requested every time"
        self.usage.calls += 1
        job_id = f"job-{session_id}-{self._attempt(session_id)}"
        self.jobs[job_id] = {"session_id": session_id}
        self._pending_approvals[job_id] = self.approval_rounds
        self._pending_continues[job_id] = self.continue_rounds
        return {"job_id": job_id}

    def poll_job(self, job_id, **kwargs):
        session_id = self.jobs[job_id]["session_id"]
        if self._pending_continues.get(job_id, 0) > 0:
            self._pending_continues[job_id] -= 1
            return {"status": "awaiting_approval",
                    "metadata": {"awaiting_kind": "continue_prompt"}}
        if self._pending_approvals.get(job_id, 0) > 0:
            self._pending_approvals[job_id] -= 1
            return {
                "status": "awaiting_approval",
                "metadata": {
                    "awaiting_kind": "change_review",
                    "pending_changes": [
                        {"change_id": f"c1-{job_id}", "operation": "replace",
                         "old_html": "<p>a</p>", "new_html": "<p>b</p>", "ai_explanation": "because"},
                        {"change_id": f"c2-{job_id}", "operation": "insert",
                         "old_html": None, "new_html": "<p>c</p>", "ai_explanation": "also"},
                    ],
                },
            }

        noop = self.mode == "noop" or (
            self.mode == "noop_then_ok" and self._attempt(session_id) < self.recover_after + 1
        )
        updated = TEMPLATE_HTML if noop else "<p>DRAFTED</p>"
        response = (
            "0 of 4 asked could be completed." if noop else "Done."
        )
        return {"status": "completed",
                "result": {"response": response,
                           "document_changes": {"updated_html": updated}}}

    def approve(self, session_id, job_id, approved, change_id=None, changes=None, feedback=None):
        self.calls.append(("approve", session_id))
        assert approved is True, "the top-level 'approved' field is required by the schema"
        return {"ok": True}

    def continue_job(self, session_id, job_id, do_continue):
        self.calls.append(("continue", session_id))
        return {"ok": True}

    def export_document(self, out_path, session_id=None, html=None, format="docx", options=None):
        self.calls.append(("export", session_id))
        kind = self._kind_for(session_id)
        content = self.doc_set.get(kind).content_html
        if self.mode == "partial" or (
            self.mode == "partial_then_ok" and self._attempt(session_id) < self.recover_after + 1
        ):
            content = content[:120]  # a real document, silently missing sections
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        return out_path


def run(doc_set, tmp_path, client=None, template_text=TEMPLATE_HTML, out_dir_override=None, **kwargs):
    client = client or FakeClient(doc_set)
    template = tmp_path / "template.html"
    template.write_text(template_text, encoding="utf-8")
    kwargs.setdefault("export_format", "html")
    result = draft_pack(
        client=client,
        doc_set=doc_set,
        template_path=str(template),
        session_id="s1",
        out_dir=out_dir_override or str(tmp_path / "out"),
        **kwargs,
    )
    return client, result


# ---------------------------------------------------------- the happy path


def test_a_pack_drafts_all_three_documents(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client, result = run(doc_set, tmp_path)
    assert [d.kind for d in result.documents] == list(DOCUMENT_ORDER)
    assert all(d.verification and d.verification.ok for d in result.documents)


def test_each_document_follows_the_four_call_contract(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client, _ = run(doc_set, tmp_path)
    for kind in DOCUMENT_ORDER:
        session = f"s1-{kind}"
        assert ("upload", session) in client.calls
        assert ("chat", session) in client.calls
        assert ("export", session) in client.calls


def test_each_document_gets_its_own_session_so_a_retry_cannot_inherit_edits(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client, result = run(doc_set, tmp_path)
    sessions = {s for _, s in client.calls}
    assert sessions == {f"s1-{k}" for k in DOCUMENT_ORDER}


def test_only_one_document_is_drafted_when_asked(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client, result = run(doc_set, tmp_path, kinds=[PACKET])
    assert [d.kind for d in result.documents] == [PACKET]
    assert client.usage.calls == 1


def test_the_run_reports_what_it_cost_from_the_server_not_an_estimate(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    _, result = run(doc_set, tmp_path)
    assert "3 billable request(s)" in result.usage_summary


# ------------------------------------------------------ human-in-the-loop


def test_every_pending_change_is_surfaced_for_approval(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, approval_rounds=1)
    _, result = run(doc_set, tmp_path, client=client)
    assert result.approvals == {"approved": 6, "rejected": 0}  # 2 changes x 3 documents


def test_multiple_approval_rounds_are_all_resolved(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, approval_rounds=2)
    _, result = run(doc_set, tmp_path, client=client, kinds=[LEASE])
    assert result.approvals["approved"] == 4


def test_a_rejecting_reviewer_is_recorded_and_does_not_crash_the_run(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, approval_rounds=1)

    def reject_everything(pending):
        return [{"change_id": c["change_id"], "approved": False} for c in pending]

    _, result = run(doc_set, tmp_path, client=client, kinds=[LEASE],
                    approval_callback=reject_everything)
    assert result.approvals == {"approved": 0, "rejected": 2}


def test_a_continue_prompt_is_routed_to_continue_not_approve(tmp_path):
    """Calling /approve on a continue_prompt is rejected with 409."""
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, continue_rounds=1)
    _, result = run(doc_set, tmp_path, client=client, kinds=[LEASE])
    assert ("continue", "s1-lease") in client.calls
    assert ("approve", "s1-lease") not in client.calls


# ------------------------------- the two failures that look like successes


def test_a_completed_job_that_changed_nothing_is_a_failure_not_a_draft(tmp_path):
    """The live failure from the sibling build, replayed. A success message that
    isn't true is the one output this tool must never produce."""
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, mode="noop")
    with pytest.raises(DraftNotApplied, match="changed nothing"):
        run(doc_set, tmp_path, client=client, kinds=[LEASE])


def test_the_failure_quotes_what_superdocs_actually_said(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, mode="noop")
    with pytest.raises(DraftNotApplied, match="0 of 4 asked could be completed"):
        run(doc_set, tmp_path, client=client, kinds=[LEASE])


def test_a_no_op_exports_nothing(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, mode="noop")
    with pytest.raises(DraftNotApplied):
        run(doc_set, tmp_path, client=client, kinds=[LEASE])
    assert not any(call == "export" for call, _ in client.calls)


def test_a_cold_session_that_settles_on_retry_succeeds(tmp_path):
    """Documented SuperDocs behaviour: the first request in a fresh session can
    no-op while things warm up. Send it again and it settles."""
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, mode="noop_then_ok", recover_after=1)
    _, result = run(doc_set, tmp_path, client=client, kinds=[LEASE])
    assert result.documents[0].attempts == 2
    assert result.documents[0].verification.ok


def test_a_partial_application_is_redrafted_from_the_clean_template(tmp_path):
    """The harder failure: the edit lands some sections and drops others, the
    job says completed, and the output is a real document that is simply wrong."""
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, mode="partial_then_ok", recover_after=1)
    _, result = run(doc_set, tmp_path, client=client, kinds=[PACKET])
    assert result.documents[0].attempts == 2
    # The retry re-uploaded the pristine template rather than layering on.
    assert [s for c, s in client.calls if c == "upload"] == ["s1-disclosure_packet"] * 2


def test_a_permanently_partial_draft_is_reported_as_unverified(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    client = FakeClient(doc_set, mode="partial")
    with pytest.raises(DraftUnverified, match="expected fact"):
        run(doc_set, tmp_path, client=client, kinds=[PACKET])


def test_an_unverified_draft_is_never_recorded_in_the_ledger(tmp_path):
    """A false success being cached is two failures compounding."""
    _, _, _, doc_set = build_pack("US-TX")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    client = FakeClient(doc_set, mode="partial")
    with pytest.raises(DraftUnverified):
        run(doc_set, tmp_path, client=client, kinds=[PACKET], ledger=ledger)
    assert ledger._load() == {}


# ------------------------------------------------------------ consistency gate


def test_an_inconsistent_pack_is_refused_before_anything_is_billed(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    lease = doc_set.get(LEASE)
    lease.content_html = lease.content_html.replace("<strong>D-1</strong>", "<strong>D-77</strong>")
    client = FakeClient(doc_set)
    with pytest.raises(PackInconsistent, match="internally inconsistent"):
        run(doc_set, tmp_path, client=client)
    assert client.calls == [], "nothing may be sent when the pack disagrees with itself"
    assert client.usage.calls == 0


# ----------------------------------------------------- per-document idempotency


def test_an_identical_rerun_spends_nothing(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    _, first = run(doc_set, tmp_path, ledger=ledger)
    assert first.billable_documents == 3

    client2 = FakeClient(doc_set)
    _, second = run(doc_set, tmp_path, client=client2, ledger=ledger)
    assert second.billable_documents == 0
    assert client2.usage.calls == 0
    assert all(d.skipped for d in second.documents)


def test_only_the_documents_whose_content_changed_are_re_billed(tmp_path):
    """A pack is three documents. Answering one more question changes the index
    and usually not the lease; re-billing the lease for that is paying twice."""
    _, _, _, doc_set = build_pack("US-TX")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    run(doc_set, tmp_path, ledger=ledger)

    index = doc_set.get(INDEX)
    index.content_html += "<p>a newly answered question</p>"

    client2 = FakeClient(doc_set)
    _, second = run(doc_set, tmp_path, client=client2, ledger=ledger)
    assert client2.usage.calls == 1, "only the changed document should be re-drafted"
    assert [d.kind for d in second.documents if not d.skipped] == [INDEX]


def test_force_defeats_the_skip(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    run(doc_set, tmp_path, ledger=ledger)
    client2 = FakeClient(doc_set)
    _, second = run(doc_set, tmp_path, client=client2, ledger=ledger, force=True)
    assert second.billable_documents == 3


def test_a_deleted_output_file_is_never_reported_as_already_done(tmp_path):
    import os

    _, _, _, doc_set = build_pack("US-TX")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    _, first = run(doc_set, tmp_path, ledger=ledger)
    os.unlink(first.documents[0].exported_path)

    client2 = FakeClient(doc_set)
    _, second = run(doc_set, tmp_path, client=client2, ledger=ledger)
    assert not second.documents[0].skipped


def test_an_edited_template_forces_a_redraft(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    run(doc_set, tmp_path, ledger=ledger)
    # Same path, same name, different bytes — the ledger hashes content, not path.
    client2 = FakeClient(doc_set)
    _, second = run(doc_set, tmp_path, client=client2, ledger=ledger,
                    template_text="<p>A DIFFERENT CUSTOMER TEMPLATE</p>")
    assert second.billable_documents == 3


def test_no_ledger_means_no_fingerprinting_io(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    _, first = run(doc_set, tmp_path, ledger=None)
    client2 = FakeClient(doc_set)
    _, second = run(doc_set, tmp_path, client=client2, ledger=None)
    assert second.billable_documents == 3


# --------------------------------------------------------------- progress


def test_progress_is_reported_per_document(tmp_path):
    _, _, _, doc_set = build_pack("US-TX")
    seen = []
    run(doc_set, tmp_path, on_progress=lambda kind, state: seen.append((kind, state)))
    assert [k for k, _ in seen] == list(DOCUMENT_ORDER)


# ------------------------------------------------------------ path safety


@pytest.mark.parametrize(
    "pack_id",
    ["../../escape", "CA/OAK-1187", "..", "  ", "con:pack", "a" * 200],
)
def test_a_hostile_pack_id_cannot_write_outside_the_output_directory(tmp_path, pack_id):
    """`pack_id` is hand-written YAML that may well be generated by another
    system, so it is treated as untrusted input rather than as a label."""
    _, _, _, doc_set = build_pack("US-TX", pack_id=pack_id)
    out_dir = tmp_path / "out"
    _, result = run(doc_set, tmp_path, out_dir_override=str(out_dir))
    for document in result.documents:
        written = Path(document.exported_path).resolve()
        assert out_dir.resolve() in written.parents, f"{written} escaped {out_dir}"


def test_safe_slug_never_returns_an_empty_name():
    from real_estate_pack.models import safe_slug

    assert safe_slug("") == "pack"
    assert safe_slug("...") == "pack"
    assert safe_slug("///") == "pack"


def test_approve_all_approves_everything_it_is_given():
    decisions = approve_all([{"change_id": "a"}, {"change_id": "b"}])
    assert decisions == [{"change_id": "a", "approved": True}, {"change_id": "b", "approved": True}]
