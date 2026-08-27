"""Exercises the draft workflow's control flow (validation gate, HITL loop,
four-call contract) against a fake client — no network, no live API key."""
from __future__ import annotations

import pytest

from supplier_quality_drafter.ledger import RunLedger
from supplier_quality_drafter.models import ActionItem, DraftRequest, FailureMode
from supplier_quality_drafter.workflow import approve_all, draft_document


class FakeUsage:
    calls = 0

    def summary(self):
        return "fake usage"


class FakeClient:
    """Duck-types the subset of SuperDocsClient the workflow uses, and records
    every call so tests can assert on the four-call contract."""

    def __init__(self, approval_rounds: int = 1, continue_rounds: int = 0):
        self.calls: list[str] = []
        self.approval_rounds_remaining = approval_rounds
        self.continue_rounds_remaining = continue_rounds
        self.approve_calls: list[dict] = []
        self.usage = FakeUsage()

    def upload_document(self, file_path, session_id, open_mode=None):
        self.calls.append("upload_document")
        return {"html": f"<div data-chunk-id='c1'><p>template body for {session_id}</p></div>"}

    def chat_async(self, message, session_id, document_html=None, **extra):
        self.calls.append("chat_async")
        assert extra.get("approval_mode") == "ask_every_time"
        return {"job_id": "job-1", "status": "pending"}

    def poll_job(self, job_id, poll_interval=3.0, max_wait=900.0, on_poll=None):
        self.calls.append("poll_job")
        if self.continue_rounds_remaining > 0:
            self.continue_rounds_remaining -= 1
            return {
                "status": "awaiting_approval",
                "metadata": {"awaiting_kind": "continue_prompt", "continue_prompt": {"remaining": 100}},
            }
        if self.approval_rounds_remaining > 0:
            self.approval_rounds_remaining -= 1
            return {
                "status": "awaiting_approval",
                "metadata": {
                    "awaiting_kind": "change_review",
                    "pending_changes": [
                        {"change_id": "ch_1", "operation": "edit", "old_html": "<p>old</p>", "new_html": "<p>new</p>", "ai_explanation": "filled FMEA table"}
                    ],
                },
            }
        return {
            "status": "completed",
            "result": {"response": "Drafted.", "document_changes": {"updated_html": "<p>final</p>"}},
        }

    def approve(self, session_id, job_id, approved, change_id=None, changes=None, feedback=None):
        self.calls.append("approve")
        self.approve_calls.append({"approved": approved, "changes": changes})
        return {"status": "in_progress"}

    def continue_job(self, session_id, job_id, do_continue):
        self.calls.append("continue_job")
        return {"status": "in_progress"}

    def export_document(self, out_path, session_id=None, html=None, format="docx", options=None):
        self.calls.append("export_document")
        with open(out_path, "wb") as f:
            f.write(b"fake docx bytes")
        return out_path


def _valid_request() -> DraftRequest:
    return DraftRequest(
        document_type="fmea",
        item_or_process="Widget",
        customer_name="Customer Co",
        engineer_name="Engineer",
        failure_modes=[FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", severity=5, occurrence=5, detection=5)],
        actions=[ActionItem(id="AC-01", failure_mode_id="FM-01", recommended_action="fix")],
    )


def test_draft_document_runs_the_four_call_contract(tmp_path):
    client = FakeClient(approval_rounds=1)
    out = tmp_path / "out.docx"
    result = draft_document(
        client, _valid_request(), template_path="templates/customer_template_a.html",
        session_id="s1", export_path=str(out),
    )
    assert client.calls == ["upload_document", "chat_async", "poll_job", "approve", "poll_job", "export_document"]
    assert result.exported_path == str(out)
    assert out.read_bytes() == b"fake docx bytes"


def test_draft_document_handles_multiple_approval_rounds(tmp_path):
    client = FakeClient(approval_rounds=3)
    out = tmp_path / "out.docx"
    draft_document(client, _valid_request(), template_path="t.html", session_id="s1", export_path=str(out))
    assert client.calls.count("poll_job") == 4  # 3 awaiting_approval + 1 completed
    assert client.calls.count("approve") == 3


def test_draft_document_refuses_without_calling_the_api_when_invalid(tmp_path):
    client = FakeClient()
    bad_request = DraftRequest(
        document_type="fmea", item_or_process="Widget", customer_name="C", engineer_name="E",
        failure_modes=[FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e")],  # no S/O/D
        actions=[],
    )
    out = tmp_path / "out.docx"
    with pytest.raises(ValueError, match="Refusing to draft"):
        draft_document(client, bad_request, template_path="t.html", session_id="s1", export_path=str(out))
    assert client.calls == []  # never touched the network


def test_approve_all_approves_every_pending_change():
    pending = [{"change_id": "a"}, {"change_id": "b"}]
    decisions = approve_all(pending)
    assert decisions == [{"change_id": "a", "approved": True}, {"change_id": "b", "approved": True}]


def test_custom_approval_callback_can_reject_a_change(tmp_path):
    client = FakeClient(approval_rounds=1)

    def reject_all(pending):
        return [{"change_id": c["change_id"], "approved": False} for c in pending]

    out = tmp_path / "out.docx"
    result = draft_document(
        client, _valid_request(), template_path="t.html", session_id="s1", export_path=str(out),
        approval_callback=reject_all,
    )
    assert client.approve_calls[0]["changes"] == [{"change_id": "ch_1", "approved": False}]
    # Rejecting does not discard the rest of the batch, and the count is reported honestly.
    assert result.approvals == {"approved": 0, "rejected": 1}


def test_a_continue_prompt_pause_is_continued_not_approved(tmp_path):
    """A large edit that pauses to ask 'keep going?' is NOT a change review —
    calling /approve on it is rejected with 409, so the workflow must branch."""
    client = FakeClient(approval_rounds=0, continue_rounds=1)
    out = tmp_path / "out.docx"
    draft_document(client, _valid_request(), template_path="t.html", session_id="s1", export_path=str(out))
    assert "continue_job" in client.calls
    assert "approve" not in client.calls


# --- idempotency: never buy the same operation twice --------------------------

def test_identical_rerun_is_skipped_without_spending_an_operation(tmp_path):
    template = tmp_path / "template.html"
    template.write_bytes(b"<h1>Customer Template</h1>")
    out = tmp_path / "out.docx"
    ledger = RunLedger(str(tmp_path / "ledger.json"))

    first = FakeClient(approval_rounds=1)
    draft_document(
        first, _valid_request(), template_path=str(template), session_id="s1",
        export_path=str(out), ledger=ledger,
    )
    assert "chat_async" in first.calls

    second = FakeClient(approval_rounds=1)
    result = draft_document(
        second, _valid_request(), template_path=str(template), session_id="s1",
        export_path=str(out), ledger=ledger,
    )
    assert result.skipped is True
    assert second.calls == []  # not one billable call on the rerun
    assert "0 billable" in result.usage_summary


def test_force_redrafts_even_when_the_ledger_has_it(tmp_path):
    template = tmp_path / "template.html"
    template.write_bytes(b"<h1>Customer Template</h1>")
    out = tmp_path / "out.docx"
    ledger = RunLedger(str(tmp_path / "ledger.json"))

    draft_document(
        FakeClient(approval_rounds=1), _valid_request(), template_path=str(template),
        session_id="s1", export_path=str(out), ledger=ledger,
    )
    forced = FakeClient(approval_rounds=1)
    result = draft_document(
        forced, _valid_request(), template_path=str(template), session_id="s1",
        export_path=str(out), ledger=ledger, force=True,
    )
    assert result.skipped is False
    assert "chat_async" in forced.calls


def test_editing_the_template_defeats_the_skip(tmp_path):
    """A changed template is different work and must be re-drafted, even at the
    same session id and output path."""
    template = tmp_path / "template.html"
    template.write_bytes(b"<h1>Version 1</h1>")
    out = tmp_path / "out.docx"
    ledger = RunLedger(str(tmp_path / "ledger.json"))

    draft_document(
        FakeClient(approval_rounds=1), _valid_request(), template_path=str(template),
        session_id="s1", export_path=str(out), ledger=ledger,
    )
    template.write_bytes(b"<h1>Version 2 - different customer branding</h1>")
    second = FakeClient(approval_rounds=1)
    result = draft_document(
        second, _valid_request(), template_path=str(template), session_id="s1",
        export_path=str(out), ledger=ledger,
    )
    assert result.skipped is False
    assert "chat_async" in second.calls


def test_no_ledger_means_no_skipping(tmp_path):
    """Idempotency is opt-in; without a ledger the workflow behaves exactly as before."""
    template = tmp_path / "template.html"
    template.write_bytes(b"<h1>T</h1>")
    out = tmp_path / "out.docx"
    for _ in range(2):
        client = FakeClient(approval_rounds=1)
        result = draft_document(
            client, _valid_request(), template_path=str(template), session_id="s1", export_path=str(out),
        )
        assert result.skipped is False
