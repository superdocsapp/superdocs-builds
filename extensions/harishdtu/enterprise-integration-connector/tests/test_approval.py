
import pytest

from connector.operations.submit_for_approval import submit_for_approval
from schemas.approval import ApprovalInput, ChangeDecision
from tests.conftest import json_response


@pytest.mark.asyncio
async def test_single_approval_shape(fake_server, client):
    fake_server.on("POST", "/v1/chat/s1/approve", lambda r: json_response(200, {"status": "in_progress"}))

    result = await submit_for_approval(client, ApprovalInput(
        session_id="s1", job_id="job_1", approved=True, change_id="chg_1",
    ))

    sent = fake_server.last_request_json()
    assert sent == {"job_id": "job_1", "approved": True, "change_id": "chg_1"}
    assert result.applied == ["chg_1"]
    assert result.rejected == []


@pytest.mark.asyncio
async def test_batch_same_decision_shape(fake_server, client):
    fake_server.on("POST", "/v1/chat/s1/approve", lambda r: json_response(200, {"status": "in_progress"}))

    result = await submit_for_approval(client, ApprovalInput(
        session_id="s1", job_id="job_1", approved=True, change_ids=["c1", "c2", "c3"],
    ))

    sent = fake_server.last_request_json()
    assert sent["approved"] is True
    assert sent["changes"] == [{"change_id": "c1"}, {"change_id": "c2"}, {"change_id": "c3"}]
    assert result.applied == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_batch_per_change_shape_mixed_decisions(fake_server, client):
    fake_server.on("POST", "/v1/chat/s1/approve", lambda r: json_response(200, {"status": "in_progress"}))

    result = await submit_for_approval(client, ApprovalInput(
        session_id="s1", job_id="job_1", approved=False,  # top-level default for unspecified entries
        changes=[
            ChangeDecision(change_id="c1", approved=True),
            ChangeDecision(change_id="c2", approved=False),
        ],
    ))

    sent = fake_server.last_request_json()
    assert sent["approved"] is False  # top-level ALWAYS present, even in per-change mode
    assert sent["changes"] == [
        {"change_id": "c1", "approved": True},
        {"change_id": "c2", "approved": False},
    ]
    assert result.applied == ["c1"]
    assert result.rejected == ["c2"]


@pytest.mark.asyncio
async def test_top_level_approved_field_is_always_present_regression(fake_server, client):
    """
    Explicit regression test per the assignment's instruction: "Write a
    regression test that ensures the top-level approved field is always
    generated." Exercises all three shapes and asserts `approved` is a
    top-level key of the outgoing JSON body in every case — the single most
    common integration mistake the SuperDocs docs call out.
    """
    fake_server.on("POST", "/v1/chat/s1/approve", lambda r: json_response(200, {"status": "in_progress"}))

    inputs = [
        ApprovalInput(session_id="s1", job_id="j1", approved=True, change_id="c1"),
        ApprovalInput(session_id="s1", job_id="j1", approved=True, change_ids=["c1", "c2"]),
        ApprovalInput(session_id="s1", job_id="j1", approved=False, changes=[ChangeDecision(change_id="c1")]),
    ]
    for approval_input in inputs:
        await submit_for_approval(client, approval_input)
        sent = fake_server.last_request_json()
        assert "approved" in sent, f"top-level 'approved' missing for input shape: {approval_input}"
        assert isinstance(sent["approved"], bool)


@pytest.mark.asyncio
async def test_feedback_is_included_for_single_shape(fake_server, client):
    fake_server.on("POST", "/v1/chat/s1/approve", lambda r: json_response(200, {"status": "in_progress"}))

    await submit_for_approval(client, ApprovalInput(
        session_id="s1", job_id="job_1", approved=False, change_id="c1", feedback="Too aggressive a rewrite",
    ))

    sent = fake_server.last_request_json()
    assert sent["feedback"] == "Too aggressive a rewrite"


def test_mutually_exclusive_shapes_rejected_client_side():
    with pytest.raises(Exception, match="exactly one shape"):
        ApprovalInput(session_id="s1", job_id="j1", approved=True, change_id="c1", change_ids=["c2"])


@pytest.mark.asyncio
async def test_wrong_awaiting_kind_handling_is_documented_and_raises(fake_server, client):
    """
    Calling /approve on a job whose metadata.awaiting_kind is 'continue_prompt'
    (not a HITL change review) is documented to 409. The connector's polling
    layer (poll_for_completion.py) is responsible for routing to /continue
    instead — this test proves that if that branch is bypassed and /approve
    is called anyway, the 409 surfaces as a typed ConflictError, not silently
    swallowed or misreported.
    """
    from connector.errors import ConflictError
    fake_server.on("POST", "/v1/chat/s1/approve", lambda r: json_response(409, {
        "detail": "This job is awaiting a continue_prompt, not a change review. Use /continue instead.",
    }))

    with pytest.raises(ConflictError, match="continue_prompt"):
        await submit_for_approval(client, ApprovalInput(
            session_id="s1", job_id="job_1", approved=True, change_id="c1",
        ))
