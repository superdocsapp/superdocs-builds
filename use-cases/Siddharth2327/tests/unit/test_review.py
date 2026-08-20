import pytest

from winloss_superdocs.review import (
    ContinuePromptNotHandled,
    ReviewDecision,
    auto_approve_all,
    run_reviewed_chat,
)


class FakeUsage:
    def check_budget(self, ctx):
        pass


class FakeClient:
    """Minimal stand-in for SuperDocsClient's async-chat surface. Each test wires up
    a scripted sequence of get_job() responses to exercise one branch of the HITL
    loop without any HTTP."""

    def __init__(self, job_sequence, approve_should_advance_to=None):
        self.usage = FakeUsage()
        self._job_sequence = list(job_sequence)
        self._approve_calls = []
        self._approve_should_advance_to = approve_should_advance_to

    def chat_async(self, session_id, message, **kwargs):
        return {"job_id": "job-1"}

    def wait_for_job(self, job_id, stop_statuses=None):
        return self._job_sequence.pop(0)

    def approve_change(self, session_id, job_id, approved, change_id=None, changes=None, feedback=None):
        self._approve_calls.append({"approved": approved, "changes": changes})
        if self._approve_should_advance_to:
            self._job_sequence.insert(0, self._approve_should_advance_to)
        return {"status": "processing"}


def test_run_reviewed_chat_happy_path_no_approval_needed():
    client = FakeClient(job_sequence=[{"status": "completed", "result": {"response": "ok"}}])
    job = run_reviewed_chat(client, "sess-1", "do it", auto_approve_all)
    assert job["status"] == "completed"


def test_run_reviewed_chat_single_approval_round():
    pending = [{"change_id": "ch_1", "operation": "edit", "ai_explanation": "x"}]
    awaiting = {"status": "awaiting_approval", "metadata": {"awaiting_kind": "change_review", "pending_changes": pending}}
    completed = {"status": "completed", "result": {"response": "ok"}}
    client = FakeClient(job_sequence=[awaiting], approve_should_advance_to=completed)

    job = run_reviewed_chat(client, "sess-1", "do it", auto_approve_all)

    assert job["status"] == "completed"
    assert len(client._approve_calls) == 1
    assert client._approve_calls[0]["approved"] is True  # required top-level default
    assert client._approve_calls[0]["changes"][0]["change_id"] == "ch_1"
    assert client._approve_calls[0]["changes"][0]["approved"] is True


def test_run_reviewed_chat_deny_with_feedback():
    def deny_with_feedback(pending):
        return [ReviewDecision(change_id=c["change_id"], approved=False, feedback="please redo") for c in pending]

    pending = [{"change_id": "ch_1", "operation": "edit", "ai_explanation": "x"}]
    awaiting = {"status": "awaiting_approval", "metadata": {"awaiting_kind": "change_review", "pending_changes": pending}}
    completed = {"status": "completed", "result": {"response": "ok"}}
    client = FakeClient(job_sequence=[awaiting], approve_should_advance_to=completed)

    run_reviewed_chat(client, "sess-1", "do it", deny_with_feedback)

    call = client._approve_calls[0]
    assert call["changes"][0]["approved"] is False
    assert call["changes"][0]["feedback"] == "please redo"


def test_run_reviewed_chat_failed_job_raises():
    client = FakeClient(job_sequence=[{"status": "failed", "error": "boom"}])
    with pytest.raises(RuntimeError, match="failed"):
        run_reviewed_chat(client, "sess-1", "do it", auto_approve_all)


def test_run_reviewed_chat_continue_prompt_refuses_to_guess():
    awaiting = {"status": "awaiting_approval", "metadata": {"awaiting_kind": "continue_prompt"}}
    client = FakeClient(job_sequence=[awaiting])
    with pytest.raises(ContinuePromptNotHandled):
        run_reviewed_chat(client, "sess-1", "do it", auto_approve_all)


def test_run_reviewed_chat_multiple_rounds_then_completes():
    pending = [{"change_id": "ch_1", "operation": "edit", "ai_explanation": "x"}]
    awaiting1 = {"status": "awaiting_approval", "metadata": {"awaiting_kind": "change_review", "pending_changes": pending}}
    awaiting2 = {"status": "awaiting_approval", "metadata": {"awaiting_kind": "change_review", "pending_changes": pending}}
    completed = {"status": "completed", "result": {"response": "ok"}}

    client = FakeClient(job_sequence=[awaiting1])
    # Manually script a two-round approval sequence.
    client._job_sequence = [awaiting1]
    calls = {"n": 0}

    def approve_change(session_id, job_id, approved, change_id=None, changes=None, feedback=None):
        calls["n"] += 1
        client._job_sequence.append(awaiting2 if calls["n"] == 1 else completed)
        return {"status": "processing"}

    client.approve_change = approve_change

    job = run_reviewed_chat(client, "sess-1", "do it", auto_approve_all, max_rounds=5)
    assert job["status"] == "completed"
    assert calls["n"] == 2
