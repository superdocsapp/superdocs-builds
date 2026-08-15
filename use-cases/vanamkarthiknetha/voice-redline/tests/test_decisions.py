"""Offline tests: the decision batch we send SuperDocs, and the B6 local gate.

No network, no API key - superdocs_client._call is monkeypatched. These pin
the two bug workarounds this app depends on:
  B1: an approve call without an explicit `changes` array is a silent no-op,
      so every decision batch must carry per-change entries.
  B6: drafting instructions bypass the server-side approval gate, so drafts
      are gated locally and a local decision must NOT call the approve API.
Run:  pytest tests/ -q   (from the voice-redline folder)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import superdocs_client as sd


class FakeAPI:
    def __init__(self, approve_response=None, job_states=("completed",)):
        self.calls = []
        self.approve_response = approve_response or {"batch_complete": True}
        self.job_states = list(job_states)

    def __call__(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        if path.endswith("/approve"):
            return self.approve_response
        if path.startswith("/v1/jobs/"):
            return {"status": self.job_states.pop(0)}
        raise AssertionError(f"unexpected call {method} {path}")


EDIT = {"session": "s1", "job_id": "j1",
        "pending": [{"change_id": "c1"}, {"change_id": "c2"}]}


def test_mixed_batch_sends_explicit_changes_array(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(sd, "_call", fake)
    monkeypatch.setattr(sd.time, "sleep", lambda s: None)
    decisions = [{"change_id": "c1", "approved": True},
                 {"change_id": "c2", "approved": False}]
    state = sd.decide(EDIT, decisions)
    assert state == "completed"
    method, path, body = fake.calls[0]
    assert path == "/v1/chat/s1/approve"
    # B1: the explicit per-change array must be present and complete.
    assert body["changes"][0] == {"change_id": "c1", "approved": True}
    assert body["changes"][1]["change_id"] == "c2"
    assert body["approved"] is True  # any approval -> job must proceed


def test_rejects_get_feedback_and_skip_poll(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(sd, "_call", fake)
    decisions = [{"change_id": "c1", "approved": False},
                 {"change_id": "c2", "approved": False}]
    state = sd.decide(EDIT, decisions)
    assert state == "rejected"
    _, _, body = fake.calls[0]
    assert body["approved"] is False
    assert all(d["feedback"] for d in body["changes"])  # every reject explains itself
    assert len(fake.calls) == 1  # all-reject: no completion poll needed


def test_incomplete_batch_raises(monkeypatch):
    fake = FakeAPI(approve_response={"batch_complete": False})
    monkeypatch.setattr(sd, "_call", fake)
    with pytest.raises(sd.SuperDocsError, match="Approval incomplete"):
        sd.decide(EDIT, [{"change_id": "c1", "approved": True}])


def test_caller_decisions_not_mutated(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(sd, "_call", fake)
    decisions = [{"change_id": "c1", "approved": False}]
    sd.decide(EDIT, decisions)
    assert "feedback" not in decisions[0]  # feedback added to a copy, not the input


def _server_client(monkeypatch):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    import server
    monkeypatch.setattr(server.sd, "upload_doc", lambda *a, **k: "sess-test")
    server.DOCS.clear(); server.EDITS.clear()
    return fastapi_testclient.TestClient(server.app), server


def test_gated_draft_decision_is_local_only(monkeypatch):
    """B6: a locally-gated draft decision must resolve without any approve call."""
    client, server = _server_client(monkeypatch)
    def boom(*a, **k):
        raise AssertionError("approve API must not be called for a local gate")
    monkeypatch.setattr(server.sd, "decide", boom)

    doc = client.post("/api/documents").json()
    server.EDITS["e1"] = {"status": "awaiting", "doc_id": doc["doc_id"],
                          "gated_draft": True, "progress": "",
                          "edit": {"session": "sess-test", "job_id": "j1",
                                   "pending": [], "summary": "draft",
                                   "draft_html": "<p>drafted</p>", "response": ""}}
    r = client.post("/api/edits/e1/decisions",
                    json={"decisions": [{"change_id": "local-draft", "approved": True}]})
    assert r.json() == {"ok": True, "local": True}
    assert server.EDITS["e1"]["status"] == "done"

    # And the status endpoint presents the draft as one synthetic change.
    server.EDITS["e1"]["status"] = "awaiting"
    pending = client.get("/api/edits/e1").json()["pending"]
    assert len(pending) == 1 and pending[0]["change_id"] == "local-draft"


def test_decisions_validated_against_pending(monkeypatch):
    """The upstream approve endpoint accepts nonexistent change_ids and
    completes the job anyway - so the server must refuse them first."""
    client, server = _server_client(monkeypatch)
    server.EDITS["e2"] = {"status": "awaiting", "doc_id": "d", "gated_draft": False,
                          "progress": "",
                          "edit": {"session": "sess-test", "job_id": "j2",
                                   "pending": [{"change_id": "real-1"}],
                                   "summary": "", "draft_html": "", "response": ""}}
    r = client.post("/api/edits/e2/decisions",
                    json={"decisions": [{"change_id": "bogus", "approved": False}]})
    assert r.status_code == 400 and "bogus" in r.json()["detail"]
    r = client.post("/api/edits/e2/decisions", json={"decisions": []})
    assert r.status_code == 400 and "real-1" in r.json()["detail"]
    assert server.EDITS["e2"]["status"] == "awaiting"  # untouched by bad input
