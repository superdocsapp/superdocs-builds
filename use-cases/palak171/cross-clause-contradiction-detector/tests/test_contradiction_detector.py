"""
End-to-end control-flow tests for the CLI, against a fully mocked SuperDocs
API: upload -> detect (chat) -> resolve (chat/async -> poll -> approve -> poll
-> export). Proves our orchestration is correct; SuperDocs' own contradiction-
finding accuracy is out of scope for a no-live-key test (see demo video for
that half of the proof).
"""
import json

import httpx
import respx

from contradiction_detector import cmd_detect, cmd_resolve
from superdocs_client import SuperDocsClient

API = "https://api.superdocs.app/v1"


@respx.mock
def test_detect_uploads_then_runs_read_only_chat(tmp_path, capsys):
    contract = tmp_path / "contract.txt"
    contract.write_text("Clause 7. Payment Terms\nPay within 30 days.\n\nClause 12. Pay within 45 days.")

    respx.post(f"{API}/documents/upload").mock(
        return_value=httpx.Response(200, json={"html": "<div>...</div>", "session_id": "sess-1"})
    )
    chat_route = respx.post(f"{API}/chat").mock(
        return_value=httpx.Response(200, json={
            "response": "1. Clause 7 vs Clause 12: 30 days vs 45 days.",
            "usage": {"ops_charged": 1, "monthly_remaining": 499},
        })
    )

    with SuperDocsClient("sk_test") as client:
        cmd_detect(client, str(contract), "sess-1", None, None)

    sent = json.loads(chat_route.calls.last.request.content)
    assert "approval_mode" not in sent  # detection never edits
    assert "Clause 7 vs Clause 12" in capsys.readouterr().out


@respx.mock
def test_resolve_applies_mixed_approve_reject_decisions_and_exports(tmp_path, monkeypatch, capsys):
    respx.post(f"{API}/chat/async").mock(return_value=httpx.Response(200, json={"job_id": "job-1"}))

    awaiting = httpx.Response(200, json={
        "status": "awaiting_approval",
        "metadata": {"pending_changes": [
            {"change_id": "ch_1", "chunk_id": "c7", "operation": "replace_text",
             "old_html": "<p>30 days</p>", "new_html": "<p>45 days</p>",
             "ai_explanation": "Clause 7 conflicts with Clause 12; Clause 12 supersedes."},
            {"change_id": "ch_2", "chunk_id": "c20", "operation": "replace_text",
             "old_html": "<p>12 months</p>", "new_html": "<p>24 months</p>",
             "ai_explanation": "Clause 20 conflicts with Clause 21."},
        ]},
    })
    completed = httpx.Response(200, json={"status": "completed", "result": {"response": "Applied 1 edit."}})
    respx.get(f"{API}/jobs/job-1").mock(side_effect=[awaiting, completed])

    approve_route = respx.post(f"{API}/chat/sess-1/approve").mock(return_value=httpx.Response(200, json={}))

    export_path = tmp_path / "reviewed.docx"
    respx.post(f"{API}/documents/export").mock(
        return_value=httpx.Response(
            200, content=b"DOCX_BYTES",
            headers={"content-disposition": 'attachment; filename="reviewed.docx"'},
        )
    )

    # Simulate a human approving the first proposed edit and rejecting the second.
    answers = iter(["y", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    with SuperDocsClient("sk_test") as client:
        cmd_resolve(client, "sess-1", auto_approve=False, auto_deny=False,
                    export_path=str(export_path), export_format="docx")

    sent = json.loads(approve_route.calls.last.request.content)
    assert sent["changes"] == [
        {"change_id": "ch_1", "approved": True},
        {"change_id": "ch_2", "approved": False},
    ]
    assert export_path.read_bytes() == b"DOCX_BYTES"
    assert "Applied 1 edit." in capsys.readouterr().out


@respx.mock
def test_resolve_auto_deny_produces_a_dry_run_with_no_committed_edits(monkeypatch):
    respx.post(f"{API}/chat/async").mock(return_value=httpx.Response(200, json={"job_id": "job-2"}))
    awaiting = httpx.Response(200, json={
        "status": "awaiting_approval",
        "metadata": {"pending_changes": [
            {"change_id": "ch_1", "chunk_id": "c7", "operation": "replace_text",
             "old_html": "<p>30 days</p>", "new_html": "<p>45 days</p>", "ai_explanation": "conflict"},
        ]},
    })
    completed = httpx.Response(200, json={"status": "completed", "result": {"response": "No edits applied."}})
    respx.get(f"{API}/jobs/job-2").mock(side_effect=[awaiting, completed])
    approve_route = respx.post(f"{API}/chat/sess-2/approve").mock(return_value=httpx.Response(200, json={}))

    with SuperDocsClient("sk_test") as client:
        cmd_resolve(client, "sess-2", auto_approve=False, auto_deny=True, export_path=None, export_format="docx")

    sent = json.loads(approve_route.calls.last.request.content)
    assert sent["changes"] == [{"change_id": "ch_1", "approved": False, "feedback": "auto-denied (dry run)"}]
