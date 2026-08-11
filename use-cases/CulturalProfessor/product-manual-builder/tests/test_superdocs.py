"""The two reply shapes, and the approval payload that silently does nothing.

No network. These pin the three API behaviours that cost real time to discover,
so the next person reads a test instead of rediscovering them against a live
service.
"""
from __future__ import annotations

import json

import pytest

from manualbuilder.superdocs import ProposedChange, SuperDocs, SuperDocsError


def change(change_id: str, document_id: str = "doc_manual") -> dict:
    return {
        "change_id": change_id, "operation": "edit", "chunk_id": "chunk_7",
        "document_id": document_id, "old_html": "<p>1.2 N·m</p>",
        "new_html": "<p>1.6 N·m</p>", "ai_explanation": "torque updated",
    }


def test_the_polling_path_is_already_parsed():
    """`metadata.pending_changes` is a list. Parsing it again would raise."""
    payload = {"metadata": {"pending_changes": [change("c1"), change("c2")]}}
    found = SuperDocs.pending_changes(payload)
    assert [c.change_id for c in found] == ["c1", "c2"]
    assert found[0].new_html == "<p>1.6 N·m</p>"


def test_the_streaming_path_is_a_json_encoded_string():
    """The double-parse trap, and it is narrower than it is usually described:
    it lives here, on the streaming path, not on polling. An integrator seeing
    `undefined` in every diff field is reading SSE."""
    payload = {
        "intermediate_responses": [
            {"type": "text", "content": "Working on it"},
            {"type": "proposed_change_batch",
             "content": json.dumps({"changes": [change("c3")]})},
        ]
    }
    found = SuperDocs.pending_changes(payload)
    assert [c.change_id for c in found] == ["c3"]
    assert found[0].explanation == "torque updated"


def test_a_batch_grouped_by_document_is_flattened():
    """A multi-document turn groups its changes by `document_id`. Every change
    still has to come back, and each one still knows which document it belongs
    to -- that is what makes the two-document edit checkable."""
    payload = {
        "intermediate_responses": [
            {"type": "proposed_change_batch",
             "content": json.dumps({
                 "doc_manual": [change("c4", "doc_manual")],
                 "doc_card": [change("c5", "doc_card")],
             })},
        ]
    }
    found = SuperDocs.pending_changes(payload)
    assert {c.change_id for c in found} == {"c4", "c5"}
    assert {c.document_id for c in found} == {"doc_manual", "doc_card"}


def test_a_batch_that_is_not_json_says_so():
    payload = {"intermediate_responses": [
        {"type": "proposed_change_batch", "content": "not json at all"},
    ]}
    with pytest.raises(SuperDocsError, match="not JSON"):
        SuperDocs.pending_changes(payload)


def test_no_changes_is_an_empty_list_and_not_an_error():
    """A turn that proposed nothing is a normal outcome, not a failure."""
    assert SuperDocs.pending_changes({}) == []
    assert SuperDocs.pending_changes({"metadata": {}}) == []


def test_a_missing_key_is_refused_before_any_request(monkeypatch):
    """With a helpful message rather than a 401 from the far end."""
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    with pytest.raises(SuperDocsError, match="SUPERDOCS_API_KEY is not set"):
        SuperDocs()


def test_the_approval_payload_carries_a_top_level_default(monkeypatch):
    """The trap: `approved` has to appear at the top level as well as per
    change. Without it the call approves nothing and looks exactly like a
    service that ignored the request."""
    sent: dict = {}

    class Fake:
        def post(self, path, json):  # noqa: A002 -- matching httpx's signature
            sent["path"], sent["body"] = path, json
            return _ok({"status": "applied"})

        def close(self):
            pass

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test")
    client = SuperDocs()
    client._client = Fake()

    client.approve("sess_1", "job_7", {"c1": True, "c2": False})

    assert sent["path"] == "/v1/chat/sess_1/approve"
    assert sent["body"]["job_id"] == "job_7", (
        "approve is keyed by the job the changes came from, and the synchronous "
        "chat reply does not carry one -- it comes from the session's job list"
    )
    assert sent["body"]["approved"] is True, (
        "the top-level default is what makes the per-change entries mean anything"
    )
    assert sent["body"]["changes"] == [
        {"change_id": "c1", "approved": True},
        {"change_id": "c2", "approved": False},
    ]


def test_a_chat_turn_parks_for_approval(monkeypatch):
    """Never `apply_immediately`. A build whose whole point is a checkable edit
    cannot let the service apply one before anyone has seen it."""
    sent: dict = {}

    class Fake:
        def post(self, path, json):  # noqa: A002
            sent["body"] = json
            return _ok({"session_id": "sess_1"})

        def close(self):
            pass

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test")
    client = SuperDocs()
    client._client = Fake()

    client.chat("raise the rail torque to 1.6 N·m", "sess_1",
                document_id="doc_manual")

    assert sent["body"]["approval_mode"] == "ask_every_time"
    assert sent["body"]["session_id"] == "sess_1", "chat requires a session"
    assert sent["body"]["document_id"] == "doc_manual", (
        "one turn, one document. An earlier version of this client sent "
        "`document_ids` as a list and looked like it worked: the service "
        "accepts the unknown field, returns proposed changes, and every one of "
        "them lands in the focused document. The pair is kept together at the "
        "approval gate instead -- see session.edit_both."
    )
    assert "document_ids" not in sent["body"]


def _ok(body: dict):
    import httpx

    return httpx.Response(
        200, json=body,
        request=httpx.Request("POST", "https://api.superdocs.app/x"),
    )


def test_proposed_change_tolerates_either_id_field():
    assert ProposedChange.from_payload({"id": "c9"}).change_id == "c9"
    assert ProposedChange.from_payload({"change_id": "c9"}).change_id == "c9"


def _client(monkeypatch, fake) -> SuperDocs:
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test")
    client = SuperDocs()
    client._client = fake
    return client


def test_a_cancelled_job_is_terminal(monkeypatch):
    """`cancelled` is a documented job status and was missing from the list this
    poll loop stops on, so a cancelled job was polled until the 600-second
    timeout and then reported as one that never finished."""
    polls = []

    class Fake:
        def get(self, path):
            polls.append(path)
            return _ok({"job_id": "job_7", "status": "cancelled"})

        def close(self):
            pass

    job = _client(monkeypatch, Fake()).wait_for_job("job_7", timeout=30)

    assert job["status"] == "cancelled"
    assert len(polls) == 1, "a terminal status is not polled twice"


def test_a_continue_prompt_is_answered_rather_than_returned(monkeypatch):
    """A large edit pauses at `awaiting_approval` with `metadata.continue_prompt`
    and an empty change list -- the same status a turn parked for review uses.
    Read as review it says "this turn proposed nothing", which is false: it
    proposed half a document and is waiting to be told to finish.

    The documented discriminator, `metadata.awaiting_kind`, is not sent by the
    service (BUGS #18), so the branch is on which of the two is populated."""
    calls: list = []
    replies = [
        {"job_id": "job_7", "session_id": "sess_1", "status": "awaiting_approval",
         "metadata": {"continue_prompt": {"done": 500, "total": 864,
                                          "remaining": 364},
                      "pending_changes": []}},
        {"job_id": "job_7", "session_id": "sess_1", "status": "in_progress"},
        {"job_id": "job_7", "session_id": "sess_1", "status": "completed",
         "metadata": {"pending_changes": [change("c1")]}},
    ]

    class Fake:
        def get(self, path):
            calls.append(("GET", path))
            return _ok(replies.pop(0))

        def post(self, path, json):  # noqa: A002
            calls.append(("POST", path, json))
            return _ok({"status": "resumed"})

        def close(self):
            pass

    client = _client(monkeypatch, Fake())
    job = client.wait_for_job("job_7", timeout=30, poll=0)

    assert job["status"] == "completed"
    assert ("POST", "/v1/chat/sess_1/continue",
            {"job_id": "job_7", "continue": True}) in calls, (
        "stopping keeps whatever was applied, which is a document edited half "
        "way through -- so this client always resumes"
    )
    assert SuperDocs.pending_changes(job)[0].change_id == "c1"


def test_a_review_pause_is_still_returned(monkeypatch):
    """The other half of the same branch: an `awaiting_approval` job carrying
    real pending changes is a human's decision and must not be resumed past."""
    class Fake:
        def get(self, path):
            return _ok({"job_id": "job_7", "session_id": "sess_1",
                        "status": "awaiting_approval",
                        "metadata": {"pending_changes": [change("c1")]}})

        def post(self, path, json):  # noqa: A002
            raise AssertionError("a batch awaiting review was resumed")

        def close(self):
            pass

    job = _client(monkeypatch, Fake()).wait_for_job("job_7", timeout=30)
    assert job["status"] == "awaiting_approval"


def test_templates_upload_uses_the_json_endpoint_and_its_field_names(monkeypatch):
    """`/v1/templates/upload` is multipart; posting JSON to it answers 422 with
    `loc: ["body","file"]`. The JSON sibling is `-base64`, and it takes
    `filename` / `file_base64` -- not the `name` / `content_base64` this client
    guessed."""
    sent: dict = {}

    class Fake:
        def post(self, path, json):  # noqa: A002
            sent["path"], sent["body"] = path, json
            return _ok({"id": "tpl_1", "name": "letterhead.html",
                        "status": "ready"})

        def close(self):
            pass

    template_id = _client(monkeypatch, Fake()).upload_template(
        "letterhead.html", "<h1>x</h1>")

    assert sent["path"] == "/v1/templates/upload-base64"
    assert sorted(sent["body"]) == ["file_base64", "filename"]
    assert sent["body"]["filename"] == "letterhead.html"
    assert template_id == "tpl_1", "the reply names it `id`, not `template_id`"
