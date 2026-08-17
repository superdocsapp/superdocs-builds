"""The SuperDocs client, exercised offline.

No key, no network — a mock transport stands in for the API, so every branch
including the failure paths is covered before a single operation is spent.

The behaviour that matters most here is the disagreement between the task
document and the current API documentation about the shape of proposed changes.
The client handles both, and both are tested.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ro_normalizer.superdocs.client import SuperDocsDocumentEditor, SuperDocsError

CHANGE = {
    "change_id": "c1",
    "section": "COMPLAINT",
    "before": "",
    "after": "Cust states CEL on and rough idle.",
}


def _editor(handler, **kwargs) -> SuperDocsDocumentEditor:
    return SuperDocsDocumentEditor(
        api_key="sk_test_not_real",
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test"),
        poll_interval=0,
        **kwargs,
    )


def _live_router(changes):
    """The shape a live completed job actually returns.

    `result.document_changes.changes` — one entry per edit, each carrying
    `old_html`, `new_html`, `chunk_id` and a `status`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "j1"})
        if path.startswith("/v1/jobs/"):
            return httpx.Response(200, json={
                "status": "completed",
                "metadata": {"pending_changes": None},
                "result": {"document_changes": {
                    "updated_html": "<p>THE WHOLE DOCUMENT, not one change</p>",
                    "changes_summary": "1 added, rest untouched",
                    "requires_approval": None,
                    "pending_changes": None,
                    "changes": changes,
                }},
            })
        return httpx.Response(200, json={"upload_id": "u1"})

    return handler


def test_the_granular_change_array_is_preferred_over_the_whole_document() -> None:
    """A live job returns both. Reading the wrong one reports every edit as a
    single change covering the entire document, which is what the first version
    of this client did."""
    editor = _editor(_live_router([{
        "status": "auto_approved",
        "chunk_id": "new",
        "old_html": None,
        "new_html": "<h2>CAUSE</h2><p>Coil failed.</p>",
        "change_id": "729063b4",
        "operation": "create",
    }]))
    ref = editor.upload("RO-1.txt", "x")
    proposed = editor.propose_edit(ref.document_id, "instruction")

    assert len(proposed.changes) == 1
    assert proposed.changes[0].after == "<h2>CAUSE</h2><p>Coil failed.</p>"
    assert "THE WHOLE DOCUMENT" not in proposed.changes[0].after
    assert proposed.changes[0].change_id == "j1", "approval is per job"


def test_a_change_the_api_auto_approved_is_still_reported() -> None:
    """`approval_mode: manual` was sent and the API marked it `auto_approved`.

    The client does not hide that — the pipeline decides what to send precisely
    because this status cannot be relied on.
    """
    editor = _editor(_live_router([{
        "status": "auto_approved", "chunk_id": "c1",
        "old_html": "<p>old</p>", "new_html": "<p>new</p>",
    }]))
    ref = editor.upload("RO-1.txt", "x")
    proposed = editor.propose_edit(ref.document_id, "instruction")

    assert proposed.changes[0].before == "<p>old</p>"
    assert proposed.changes[0].after == "<p>new</p>"


def _router(pending, *, job_status="awaiting_approval"):
    """A transport that plays the documented flow."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path == "/v1/documents/upload-base64":
            return httpx.Response(200, json={"upload_id": "u1", "chunks_count": 3})
        if path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "j1"})
        if path.startswith("/v1/jobs/"):
            return httpx.Response(
                200, json={"status": job_status, "metadata": {"pending_changes": pending}}
            )
        if path.endswith("/approve"):
            return httpx.Response(200, json={"applied": True})
        if path == "/v1/documents/export":
            return httpx.Response(200, json={"content": "COMPLAINT:\nCust states CEL on."})
        return httpx.Response(404, text="unrouted")

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


# --- the disagreement -------------------------------------------------------


def test_changes_arriving_as_objects_are_read() -> None:
    """What the current documentation describes."""
    editor = _editor(_router([CHANGE]))
    ref = editor.upload("RO-1.txt", "COMPLAINT:\n")
    proposed = editor.propose_edit(ref.document_id, "SECTION: COMPLAINT\nCust states CEL on.")

    assert len(proposed.changes) == 1
    assert proposed.changes[0].section == "COMPLAINT"
    assert "CEL on" in proposed.changes[0].after


def test_changes_arriving_json_encoded_are_also_read() -> None:
    """What the task document warns about.

    Getting this wrong is documented as the single most common reason
    integrators see diff cards where every field reads `undefined`. Whichever
    shape the deployed API actually sends, the client reads it.
    """
    editor = _editor(_router(json.dumps([CHANGE])))
    ref = editor.upload("RO-1.txt", "COMPLAINT:\n")
    proposed = editor.propose_edit(ref.document_id, "SECTION: COMPLAINT\ntext")

    assert len(proposed.changes) == 1
    assert proposed.changes[0].after.startswith("Cust states")


def test_the_documented_chunk_shape_is_read_too() -> None:
    """The docs describe pending changes carrying `chunk_id` and `html`.

    The change id is the job id regardless of shape, because approval is granted
    per job — the chunk id is the API's internal address, not our handle.
    """
    editor = _editor(_router([{"chunk_id": "ch7", "html": "<p>Replaced coil.</p>"}]))
    ref = editor.upload("RO-1.txt", "x")
    proposed = editor.propose_edit(ref.document_id, "instruction")

    assert proposed.changes[0].change_id == "j1"
    assert proposed.changes[0].section == "ch7"
    assert "Replaced coil" in proposed.changes[0].after


def test_no_pending_changes_is_an_empty_list_not_a_crash() -> None:
    editor = _editor(_router([]))
    ref = editor.upload("RO-1.txt", "x")
    assert editor.propose_edit(ref.document_id, "instruction").changes == []


# --- the four calls ---------------------------------------------------------


def test_the_documented_endpoints_are_the_ones_called() -> None:
    handler = _router([CHANGE])
    editor = _editor(handler)

    ref = editor.upload("RO-1.txt", "COMPLAINT:\n")
    proposed = editor.propose_edit(ref.document_id, "instruction")
    editor.approve(ref.document_id, [c.change_id for c in proposed.changes])
    editor.export(ref.document_id)

    assert "/v1/documents/upload-base64" in handler.seen
    assert "/v1/chat/async" in handler.seen
    assert any(p.startswith("/v1/jobs/") for p in handler.seen)
    assert any(p.endswith("/approve") for p in handler.seen)
    assert "/v1/documents/export" in handler.seen


def test_nothing_is_approved_when_there_is_nothing_to_approve() -> None:
    """An empty approve call would spend an operation for no reason."""
    handler = _router([])
    editor = _editor(handler)
    assert editor.approve("s1", []) == 0
    assert not any(p.endswith("/approve") for p in handler.seen)


def test_rejecting_is_possible_because_a_gate_needs_both_answers() -> None:
    handler = _router([CHANGE])
    editor = _editor(handler)
    assert editor.reject("s1", ["j1"], feedback="not supported by the note") == 1
    assert any(p.endswith("/approve") for p in handler.seen)


def test_approval_is_sent_per_job_as_the_api_requires() -> None:
    """The endpoint wants `job_id` and `approved`, not a list of changes.

    Sending a `changes` array returns 422 asking for both fields.
    """
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/approve"):
            captured.append(json.loads(request.content))
        return httpx.Response(200, json={"applied": True})

    editor = _editor(handler)
    editor.approve("s1", ["job-a", "job-a", "job-b"])

    assert len(captured) == 2, "the same job is not approved twice"
    assert captured[0] == {"job_id": "job-a", "approved": True}
    assert captured[1] == {"job_id": "job-b", "approved": True}


def test_the_edit_is_sent_with_approval_mode_manual() -> None:
    """The field is a string — the API rejects a boolean with 422.

    Asserting it is sent, not that it works. Against the live API it does not:
    every accepted value completes the job and applies the edit. The real gate
    is in the pipeline, which does not send a change a human should see first.
    """
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/async":
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"job_id": "j1"})
        if request.url.path.startswith("/v1/jobs/"):
            return httpx.Response(200, json={"status": "awaiting_approval", "metadata": {}})
        return httpx.Response(200, json={"upload_id": "u1"})

    editor = _editor(handler)
    ref = editor.upload("RO-1.txt", "x")
    editor.propose_edit(ref.document_id, "instruction")

    assert captured["approval_mode"] == "manual"
    assert captured["session_id"] == ref.document_id


# --- failure paths ----------------------------------------------------------


def test_a_missing_key_is_refused_before_any_call() -> None:
    with pytest.raises(SuperDocsError) as exc:
        SuperDocsDocumentEditor(api_key="")
    assert "SUPERDOCS_API_KEY" in str(exc.value)
    assert "EDITOR_BACKEND=mock" in str(exc.value)


def test_an_unauthorised_response_names_the_fix() -> None:
    editor = _editor(lambda request: httpx.Response(401, text="nope"))
    with pytest.raises(SuperDocsError) as exc:
        editor.upload("RO-1.txt", "x")
    assert "SUPERDOCS_API_KEY" in str(exc.value)


def test_quota_exhaustion_is_explained_rather_than_raw() -> None:
    editor = _editor(lambda request: httpx.Response(429, text="quota"))
    with pytest.raises(SuperDocsError) as exc:
        editor.upload("RO-1.txt", "x")
    assert "quota" in str(exc.value).lower()
    assert "Exports and downloads are free" in str(exc.value)


def test_a_failed_job_raises_with_its_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/jobs/"):
            return httpx.Response(200, json={"status": "failed", "error": "model unavailable"})
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "j1"})
        return httpx.Response(200, json={"upload_id": "u1"})

    editor = _editor(handler)
    ref = editor.upload("RO-1.txt", "x")
    with pytest.raises(SuperDocsError) as exc:
        editor.propose_edit(ref.document_id, "instruction")
    assert "model unavailable" in str(exc.value)


def test_a_slow_job_times_out_with_advice_not_silence() -> None:
    """A long silence is documented as still processing, so the message says so."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/jobs/"):
            return httpx.Response(200, json={"status": "processing"})
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"job_id": "j1"})
        return httpx.Response(200, json={"upload_id": "u1"})

    editor = _editor(handler, poll_timeout=0.01)
    ref = editor.upload("RO-1.txt", "x")
    with pytest.raises(SuperDocsError) as exc:
        editor.propose_edit(ref.document_id, "instruction")
    assert "can take minutes" in str(exc.value)


def test_an_unreachable_api_says_so_instead_of_leaking_httpx() -> None:
    """No network, a proxy, a DNS failure — all the same to the caller.

    Every other failure path here names the cause and the fix. This one used to
    raise a bare `httpx.ConnectError` from three frames down, which tells a user
    running a batch nothing about what to do next.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nodename nor servname provided")

    editor = _editor(handler)
    with pytest.raises(SuperDocsError) as exc:
        editor.upload("RO-1.txt", "x")

    assert "could not be reached" in str(exc.value)
    assert "EDITOR_BACKEND=mock" in str(exc.value)


def test_a_dropped_connection_mid_batch_is_also_named() -> None:
    """A read timeout is a different exception and was equally raw."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    editor = _editor(handler)
    with pytest.raises(SuperDocsError) as exc:
        editor.upload("RO-1.txt", "x")
    assert "could not be reached" in str(exc.value)


def test_a_chat_reply_without_a_job_id_is_an_explicit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/async":
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json={"upload_id": "u1"})

    editor = _editor(handler)
    ref = editor.upload("RO-1.txt", "x")
    with pytest.raises(SuperDocsError) as exc:
        editor.propose_edit(ref.document_id, "instruction")
    assert "job_id" in str(exc.value)
