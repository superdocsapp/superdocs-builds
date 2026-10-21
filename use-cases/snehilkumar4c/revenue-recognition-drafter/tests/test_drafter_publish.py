"""Tests for drafter/publish.py -- the SuperDocs integration layer. Uses a
fake SuperDocsClient (no live key, no network) matching the real client's
public method signatures, same pattern as pipeline/'s fake LLM clients.
"""

from __future__ import annotations

from typing import Any

import pytest

from drafter.publish import (
    MemoJobFailedError,
    change_is_formatting_only,
    export_memo,
    poll_until_resolved,
    resolve_pending_changes_by_content_verification,
    start_memo_authoring_job,
)


class _FakeSuperDocsClient:
    """Scripts a sequence of get_job() responses; records every call made
    so tests can assert on what was actually sent, not just the final
    outcome."""

    def __init__(self, job_sequence: list[dict[str, Any]]) -> None:
        self._job_sequence = job_sequence
        self._poll_index = 0
        self.chat_async_calls: list[dict[str, Any]] = []
        self.approve_calls: list[dict[str, Any]] = []
        self.export_calls: list[dict[str, Any]] = []

    def chat_async(self, **kwargs: Any) -> dict[str, Any]:
        self.chat_async_calls.append(kwargs)
        return {"job_id": "job-1", "status": "pending"}

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self._job_sequence[min(self._poll_index, len(self._job_sequence) - 1)]
        self._poll_index += 1
        return job

    def approve(self, **kwargs: Any) -> dict[str, Any]:
        self.approve_calls.append(kwargs)
        return {}

    def export(self, **kwargs: Any) -> dict[str, Any]:
        self.export_calls.append(kwargs)
        return {"status": "exported"}


def test_start_memo_authoring_job_sends_verbatim_html_and_ask_every_time() -> None:
    fake = _FakeSuperDocsClient([])
    start_memo_authoring_job(fake, "session-1", "<h1>Memo</h1>")  # type: ignore[arg-type]

    call = fake.chat_async_calls[0]
    assert call["document_html"] == "<h1>Memo</h1>"
    assert call["approval_mode"] == "ask_every_time"
    assert call["session_id"] == "session-1"
    # The instruction must explicitly forbid content changes -- the whole
    # trust boundary this module documents depends on that constraint
    # actually being sent, not just claimed in a comment.
    assert "do NOT alter" in call["message"]


def test_poll_until_resolved_returns_immediately_on_completed() -> None:
    fake = _FakeSuperDocsClient([{"status": "completed", "result": {"response": "ok"}}])
    job = poll_until_resolved(fake, "job-1", "session-1", poll_interval_seconds=0)  # type: ignore[arg-type]
    assert job["status"] == "completed"


def test_poll_until_resolved_raises_on_failed() -> None:
    fake = _FakeSuperDocsClient([{"status": "failed", "error": "model error"}])
    with pytest.raises(MemoJobFailedError, match="failed"):
        poll_until_resolved(fake, "job-1", "session-1", poll_interval_seconds=0)  # type: ignore[arg-type]


def test_poll_until_resolved_raises_on_cancelled() -> None:
    fake = _FakeSuperDocsClient([{"status": "cancelled"}])
    with pytest.raises(MemoJobFailedError, match="cancelled"):
        poll_until_resolved(fake, "job-1", "session-1", poll_interval_seconds=0)  # type: ignore[arg-type]


def test_poll_until_resolved_returns_control_without_approving_when_not_auto_approve() -> None:
    """The core HITL guarantee: with auto_approve=False, pending changes
    are surfaced to the caller, never silently approved on their behalf."""
    fake = _FakeSuperDocsClient(
        [
            {
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"change_id": "ch_1"}]},
            }
        ]
    )
    job = poll_until_resolved(
        fake, "job-1", "session-1", auto_approve=False, poll_interval_seconds=0  # type: ignore[arg-type]
    )
    assert job["status"] == "awaiting_approval"
    assert job["metadata"]["pending_changes"][0]["change_id"] == "ch_1"
    assert fake.approve_calls == [], "must not approve anything when auto_approve=False"


def test_poll_until_resolved_auto_approves_formatting_only_changes_and_continues() -> None:
    fake = _FakeSuperDocsClient(
        [
            {
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [
                        {
                            "change_id": "ch_1",
                            "old_html": "<h1>Memo</h1>",
                            "new_html": "<h1><strong>Memo</strong></h1>",  # same text, just bolded
                        }
                    ]
                },
            },
            {"status": "completed", "result": {"response": "ok"}},
        ]
    )
    job = poll_until_resolved(
        fake, "job-1", "session-1", auto_approve=True, poll_interval_seconds=0  # type: ignore[arg-type]
    )
    assert job["status"] == "completed"
    assert len(fake.approve_calls) == 1
    assert fake.approve_calls[0]["change_id"] == "ch_1"
    assert fake.approve_calls[0]["approved"] is True


def test_poll_until_resolved_stops_rather_than_polling_forever() -> None:
    """TASK.md's own budget/stopping-rule gotcha, made concrete: a job that
    never resolves must not be polled forever."""
    fake = _FakeSuperDocsClient([{"status": "in_progress"}])
    with pytest.raises(MemoJobFailedError, match="did not reach a terminal status"):
        poll_until_resolved(
            fake, "job-1", "session-1", poll_interval_seconds=0, max_polls=3  # type: ignore[arg-type]
        )


def test_change_is_formatting_only_true_when_text_identical_despite_markup() -> None:
    old = "<p>The extended warranty is distinct.</p>"
    new = '<p>The <strong>extended warranty</strong> is distinct.</p>'
    assert change_is_formatting_only(old, new) is True


def test_change_is_formatting_only_false_when_wording_changes() -> None:
    """Reproduces the exact real finding from the 2026-08-11 MCP validation
    run: "recognition" was changed to "Recognition timing" mid-sentence
    while the change's own ai_explanation still claimed pure formatting."""
    old = "<p>a point-in-time recognition despite the activities</p>"
    new = "<p>a point-in-time <strong>Recognition timing</strong> despite the activities</p>"
    assert change_is_formatting_only(old, new) is False


def test_change_is_formatting_only_false_when_obligation_id_substituted_into_prose() -> None:
    old = "<p>benefit from it together with the extended warranty</p>"
    new = "<p>benefit from it together with the <strong>extended_warranty</strong></p>"
    assert change_is_formatting_only(old, new) is False


def test_resolve_pending_changes_approves_safe_and_denies_content_altering() -> None:
    """THE core guarantee this module exists to provide: mixed batch of one
    genuinely formatting-only change and one content-altering change --
    only the safe one gets approved=True."""
    fake = _FakeSuperDocsClient([])
    pending_changes = [
        {
            "change_id": "ch_safe",
            "old_html": "<h2>Areas of Judgement</h2>",
            "new_html": "<h2><strong>Areas of Judgement</strong></h2>",
        },
        {
            "change_id": "ch_unsafe",
            "old_html": "<li>the extended warranty is distinct</li>",
            "new_html": "<li>the extended_warranty is distinct</li>",
        },
    ]
    result = resolve_pending_changes_by_content_verification(
        fake, "session-1", "job-1", pending_changes  # type: ignore[arg-type]
    )

    assert result == {"approved_count": 1, "denied_count": 1}
    calls_by_id = {c["change_id"]: c for c in fake.approve_calls}
    assert calls_by_id["ch_safe"]["approved"] is True
    assert calls_by_id["ch_unsafe"]["approved"] is False
    assert "altered substantive text" in calls_by_id["ch_unsafe"]["feedback"]


def test_export_memo_calls_client_export_with_session_and_format() -> None:
    fake = _FakeSuperDocsClient([])
    export_memo(fake, "session-1", format="pdf")  # type: ignore[arg-type]
    assert fake.export_calls[0] == {"session_id": "session-1", "format": "pdf"}
