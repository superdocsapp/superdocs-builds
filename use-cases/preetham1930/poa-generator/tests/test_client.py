"""The four wire rules, enforced in the client rather than in a caller's care.

Copied from `builds/statutory-statements/tests/` and rebuilt (Decision 31): the
wire rules are the same rules, measured on the same product, and re-deriving
them would be pretending we had not already learned them. The fifth rule, at the
bottom of this file, is this build's own - `export` will not run without a
receipt from the notice gate.
"""

from __future__ import annotations

import inspect

import pytest
from poa.errors import NotConfiguredError, PlanRefusedError
from poa.superdocs.client import PoaClient, select_our_change
from poa.superdocs.transport import HttpTransport, RecordedCall, ReplayTransport
from recorded import gate_job


def _client(calls: list[RecordedCall]) -> tuple[PoaClient, ReplayTransport]:
    transport = ReplayTransport(calls)
    return PoaClient(transport, poll_seconds=0), transport


def test_gated_changes_go_to_the_async_route(monkeypatch) -> None:
    """Decision 32: approve takes a job_id and jobs exist only on /v1/chat/async."""
    job = gate_job("awaiting-approval")
    client, transport = _client(
        [
            RecordedCall("POST", "/v1/chat/async", {"job_id": job["job_id"]}),
            RecordedCall("GET", f"/v1/jobs/{job['job_id']}", job),
        ]
    )
    result = client.chat_gated("session_x", "doc_x", "replace chunk abc with ...")
    assert result.awaiting
    paths = [path for _, path, _ in transport.seen]
    assert paths[0] == "/v1/chat/async"
    assert "/v1/chat" not in paths, "the synchronous route has no gate to reach"
    body = transport.seen[0][2]
    assert body["approval_mode"] == "ask_every_time"
    assert body["response_mode"] == "compact"


def test_a_batch_is_split_into_ours_and_everything_else() -> None:
    """We send one chunk; the product does not always answer with one change."""
    from poa.superdocs.client import _job_from

    job = _job_from(gate_job("awaiting-approval"))
    assert len(job.pending) == 3
    ours, unasked = select_our_change(job, job.pending[1].chunk_id)
    assert ours is job.pending[1]
    assert len(unasked) == 2
    assert ours not in unasked


def test_a_batch_that_does_not_contain_our_target_is_refused_in_full() -> None:
    from poa.superdocs.client import Job, PendingChange

    job = Job("j", "awaiting_approval", 88, [PendingChange("c", "other-chunk", "edit", "", "")], {})
    with pytest.raises(PlanRefusedError) as caught:
        select_our_change(job, "our-chunk")
    assert "none of them on chunk our-chunk" in str(caught.value)
    assert "Every one is denied" in str(caught.value)


def test_a_create_operation_on_our_target_is_refused() -> None:
    from poa.superdocs.client import Job, PendingChange

    job = Job("j", "awaiting_approval", 88, [PendingChange("c", "ours", "create", "", "")], {})
    with pytest.raises(PlanRefusedError, match="one verb"):
        select_our_change(job, "ours")


def test_denials_carry_no_feedback() -> None:
    """Decision 34: there is no call shape in which feedback can be sent."""
    signature = inspect.signature(PoaClient.deny)
    assert "feedback" not in signature.parameters

    client, transport = _client(
        [RecordedCall("POST", "/v1/chat/s/approve", {"status": "ok", "batch_complete": True})]
    )
    client.deny("s", "j", "c")
    body = transport.seen[0][2]
    assert body == {"job_id": "j", "change_id": "c", "approved": False}
    assert "feedback" not in body


def test_a_read_back_with_no_html_verifies_nothing_and_says_so() -> None:
    client, _ = _client([RecordedCall("GET", "/v1/documents/d", {"version": 2})])
    with pytest.raises(RuntimeError, match="carried no html"):
        client.read_back("d")


def test_an_upload_that_is_not_persisted_stops_the_run() -> None:
    """Measured: an upload with no session is not persisted and carries no id."""
    client, _ = _client(
        [
            RecordedCall("POST", "/v1/sessions/init", {"session_id": "s"}),
            RecordedCall(
                "POST",
                "/v1/documents/upload-base64",
                {"filename": "f.html", "chunks_count": 3, "persisted": False},
            ),
        ]
    )
    with pytest.raises(RuntimeError, match="only evidence there is"):
        client.upload_verbatim("f.html", "<p>x</p>")


def test_the_document_id_comes_from_the_session_roster_not_from_the_upload() -> None:
    """The upload response has no document id at all; the roster is a read, not a claim."""
    client, transport = _client(
        [
            RecordedCall("POST", "/v1/sessions/init", {"session_id": "s"}),
            RecordedCall("POST", "/v1/documents/upload-base64", {"persisted": True}),
            RecordedCall(
                "GET",
                "/v1/sessions/s/documents",
                {"documents": [{"document_id": "doc_primary", "durable_document_id": "dur-1"}]},
            ),
        ]
    )
    document_id, session_id = client.upload_verbatim("f.html", "<p>x</p>")
    assert (document_id, session_id) == ("dur-1", "s")
    assert [path for _, path, _ in transport.seen][-1] == "/v1/sessions/s/documents"


def test_a_roster_with_no_durable_id_stops_the_run() -> None:
    client, _ = _client(
        [
            RecordedCall("POST", "/v1/sessions/init", {"session_id": "s"}),
            RecordedCall("POST", "/v1/documents/upload-base64", {"persisted": True}),
            RecordedCall("GET", "/v1/sessions/s/documents", {"documents": []}),
        ]
    )
    with pytest.raises(RuntimeError, match="nothing to verify against"):
        client.upload_verbatim("f.html", "<p>x</p>")


def test_the_replay_transport_never_invents_a_response() -> None:
    client, _ = _client([])
    with pytest.raises(AssertionError) as caught:
        client.read_back("d")
    assert "never invents one" in str(caught.value)


def test_a_live_transport_without_a_key_refuses_to_exist(monkeypatch) -> None:
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    with pytest.raises(NotConfiguredError) as caught:
        HttpTransport()
    assert "recorded responses" in str(caught.value)
    assert "SUPERDOCS_API_KEY" in str(caught.value)


def test_the_key_is_never_in_a_message_this_module_can_produce(monkeypatch) -> None:
    fake = "sk-" + "live-" + "0123456789abcdef"
    monkeypatch.setenv("SUPERDOCS_API_KEY", fake)
    transport = HttpTransport()
    from poa.superdocs.transport import redacted_key

    assert redacted_key() == "...cdef"
    assert fake not in repr(transport.__dict__.get("base_url", ""))


def test_the_export_runs_only_with_a_receipt_from_the_notice_gate(financial, library) -> None:
    """The fifth wire rule, and it is this build's own (INVARIANTS.md B1)."""
    from poa.chunks import ChunkMap
    from poa.notices import check_notices

    client, transport = _client(
        [RecordedCall("POST", "/v1/documents/export", {"download_url": "https://x.invalid"})]
    )
    receipt = check_notices(ChunkMap(financial.html("target")), library, "dur-1")
    client.export("s", "docx", receipt)
    assert [path for _, path, _ in transport.seen] == ["/v1/documents/export"]
    assert client.export_receipts == [receipt.receipt()], (
        "the run log carries what the gate actually checked, not that it was called"
    )
