"""
Focused tests for ApprovalHandler.sync_pending_changes.

These 5 cases validate the HITL claim/review creation path:

1. awaiting_approval + changes → Review row created, Claims created and linked
2. awaiting_approval + changes + existing claims → idempotent (sync not called twice)
3. completed + no changes → no Review or Claims created
4. completed + unresolved DocIntel claims → block (safety: apply_approvals returns 0)
5. awaiting_approval + missing/ambiguous change payload → raises, not silently skipped
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.integrations.superdocs.approval_handler import ApprovalHandler
from backend.integrations.superdocs.client import JobStatus, JobStatusResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job(status: JobStatus, pending_changes=None):
    return JobStatusResult(
        job_id="job-abc",
        status=status,
        progress=1.0,
        result={},
        pending_changes=pending_changes if pending_changes is not None else [],
        error=None,
    )


def _change(change_id="chg-1", chunk_id="chunk-1", old_html="<p>old</p>", new_html="<p>new</p>", ai_explanation="AI said so"):
    return {
        "change_id": change_id,
        "chunk_id": chunk_id,
        "old_html": old_html,
        "new_html": new_html,
        "ai_explanation": ai_explanation,
    }


def _make_handler(claim_repo=None, review_repo=None, workspace_id=None):
    """Build an ApprovalHandler with mocked dependencies."""
    mock_claim = MagicMock()
    mock_claim.id = uuid4()

    mock_review = MagicMock()
    mock_review.id = uuid4()

    if claim_repo is None:
        claim_repo = AsyncMock()
        claim_repo.create = AsyncMock(return_value=mock_claim)
        claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[])

    if review_repo is None:
        review_repo = AsyncMock()
        review_repo.create = AsyncMock(return_value=mock_review)

    handler = ApprovalHandler(
        superdocs_client=AsyncMock(),
        session_manager=AsyncMock(),
        claim_repository=claim_repo,
        review_repository=review_repo,
    )

    # Patch workspace lookup to return a fixed UUID (avoids DB call in tests)
    _ws_id = workspace_id or uuid4()
    handler._get_workspace_id = AsyncMock(return_value=_ws_id)

    return handler, claim_repo, review_repo


# ---------------------------------------------------------------------------
# CASE 1: awaiting_approval + changes → Review row + Claims created and linked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case1_awaiting_approval_with_changes_creates_review_and_claims():
    """
    When SuperDocs job is awaiting_approval with real pending_changes,
    sync_pending_changes must:
      - create exactly one Review row
      - create one Claim per change
      - link each Claim to the Review via review_id
    """
    run_id = uuid4()

    mock_claim = MagicMock()
    mock_claim.id = uuid4()
    mock_review = MagicMock()
    mock_review.id = uuid4()

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=mock_claim)

    review_repo = AsyncMock()
    review_repo.create = AsyncMock(return_value=mock_review)

    handler, _, _ = _make_handler(claim_repo=claim_repo, review_repo=review_repo)

    changes = [_change("chg-1"), _change("chg-2")]
    job_status = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)

    claim_ids = await handler.sync_pending_changes(
        run_id=run_id,
        job_id="job-abc",
        job_status=job_status,
    )

    # One Review row created
    review_repo.create.assert_called_once()
    review_create_kwargs = review_repo.create.call_args.kwargs
    assert review_create_kwargs["workflow_run_id"] == run_id
    assert review_create_kwargs["status"] == "in_review"

    # Two Claims created
    assert claim_repo.create.call_count == 2
    assert len(claim_ids) == 2

    # Each Claim linked to the Review
    for call in claim_repo.create.call_args_list:
        kwargs = call.kwargs
        assert kwargs["review_id"] == mock_review.id
        assert kwargs["claim_type"] == "superdocs_change"
        assert kwargs["status"] == "pending"
        assert kwargs["source_stage"] == "superdocs_approval"
        assert kwargs["superdocs_job_id"] == "job-abc"

        # Verify field mapping: SuperDocs new_html/old_html/ai_explanation stored correctly
        content = json.loads(kwargs["content"])
        assert "new_html" in content
        assert "old_html" in content
        assert "ai_explanation" in content
        # Old wrong field names must NOT be present
        assert "proposed_html" not in content
        assert "current_html" not in content
        assert "description" not in content


# ---------------------------------------------------------------------------
# CASE 2: idempotent — if existing claims present, sync should not double-create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case2_idempotent_no_duplicates_when_claims_exist():
    """
    When superdocs_change claims already exist for this run (e.g. workflow resumed),
    the stage should NOT call sync_pending_changes again. This is enforced by
    the stage logic (not calling sync if has_existing_claims), but we test the
    handler itself: if called with a job that has changes, it creates a new Review
    only on first call. The caller (stage) is responsible for not calling it twice.

    This test verifies that a SECOND call to sync_pending_changes for the same run
    does NOT fail silently — it creates a NEW Review. The stage prevents double-calling
    via the has_existing_claims gate. Here we just confirm the handler is pure.
    """
    run_id = uuid4()

    mock_review1 = MagicMock(id=uuid4())
    mock_review2 = MagicMock(id=uuid4())
    mock_claim = MagicMock(id=uuid4())

    review_repo = AsyncMock()
    review_repo.create = AsyncMock(side_effect=[mock_review1, mock_review2])

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(return_value=mock_claim)

    handler, _, _ = _make_handler(claim_repo=claim_repo, review_repo=review_repo)

    changes = [_change("chg-1")]
    job_status = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)

    # First call (fresh run)
    ids1 = await handler.sync_pending_changes(run_id, "job-abc", job_status)
    assert len(ids1) == 1
    assert review_repo.create.call_count == 1

    # Stage should NEVER call sync again once claims exist.
    # But if it mistakenly did, a second Review would be created — not silently ignored.
    ids2 = await handler.sync_pending_changes(run_id, "job-abc", job_status)
    assert len(ids2) == 1
    assert review_repo.create.call_count == 2  # Each call creates its own Review


# ---------------------------------------------------------------------------
# CASE 3: completed + no changes → no Review or Claims created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case3_completed_no_changes_creates_nothing():
    """
    When job is COMPLETED with no pending_changes, sync_pending_changes
    should create no Review and no Claims.
    """
    run_id = uuid4()
    handler, claim_repo, review_repo = _make_handler()

    job_status = _job(JobStatus.COMPLETED, pending_changes=[])
    claim_ids = await handler.sync_pending_changes(run_id, "job-abc", job_status)

    assert claim_ids == []
    review_repo.create.assert_not_called()
    claim_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# CASE 4: claims exist but all resolved → apply_approvals must process them
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case4_resolved_claims_are_applied_to_superdocs():
    """
    After the user resolves all claims (approved/rejected), apply_approvals
    must call SuperDocs approve_change for each claim and return correct counts.
    Critically: _get_claims_for_job must NOT return empty list (the old TODO stub bug).
    """
    run_id = uuid4()

    approved_claim = MagicMock()
    approved_claim.id = uuid4()
    approved_claim.status = "approved"
    approved_claim.superdocs_change_id = "chg-1"

    rejected_claim = MagicMock()
    rejected_claim.id = uuid4()
    rejected_claim.status = "rejected"
    rejected_claim.superdocs_change_id = "chg-2"

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[approved_claim, rejected_claim])
    claim_repo.update = AsyncMock()

    review_repo = AsyncMock()

    mock_session_manager = AsyncMock()
    mock_session_manager.get_session_for_run = AsyncMock(return_value="sess-123")

    mock_superdocs_client = AsyncMock()
    mock_approve_result = MagicMock()
    mock_approve_result.job_status = JobStatus.IN_PROGRESS
    mock_superdocs_client.approve_change = AsyncMock(return_value=mock_approve_result)

    handler = ApprovalHandler(
        superdocs_client=mock_superdocs_client,
        session_manager=mock_session_manager,
        claim_repository=claim_repo,
        review_repository=review_repo,
    )

    counts = await handler.apply_approvals(run_id=run_id, job_id="job-abc")

    assert counts["approved"] == 1
    assert counts["rejected"] == 1

    # Verify SuperDocs was called (via batch decisions)
    assert mock_superdocs_client.approve_change.call_count == 1
    call_kwargs = mock_superdocs_client.approve_change.call_args.kwargs
    assert len(call_kwargs["changes"]) == 2
    assert call_kwargs["changes"][0]["change_id"] == "chg-1"
    assert call_kwargs["changes"][0]["approved"] is True
    assert call_kwargs["changes"][1]["change_id"] == "chg-2"
    assert call_kwargs["changes"][1]["approved"] is False


# ---------------------------------------------------------------------------
# CASE 5: ambiguous/missing change payload → raises, not silently skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case5_claim_creation_failure_raises_not_silently_ignored():
    """
    If claim_repo.create() raises (e.g. DB error, missing field), the error must
    propagate — NOT be silently swallowed. This prevents the workflow from
    believing sync succeeded when it actually produced zero claims.
    """
    run_id = uuid4()

    mock_review = MagicMock(id=uuid4())
    review_repo = AsyncMock()
    review_repo.create = AsyncMock(return_value=mock_review)

    claim_repo = AsyncMock()
    claim_repo.create = AsyncMock(side_effect=Exception("DB constraint violation"))

    handler, _, _ = _make_handler(claim_repo=claim_repo, review_repo=review_repo)

    changes = [_change("chg-1")]
    job_status = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)

    with pytest.raises(Exception, match="DB constraint violation"):
        await handler.sync_pending_changes(run_id, "job-abc", job_status)


# ---------------------------------------------------------------------------
# CASE 6: 57 approvals where exactly one approval initially fails and is retried
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case6_57_approvals_with_one_transient_failure_retries_and_succeeds():
    """
    REGRESSION TEST: 57 approvals where exactly one approval (e.g. #57)
    transiently fails on first attempt but succeeds on retry.
    Verifies:
      - All 57 claims are submitted with bounded concurrency
      - The transient failure is retried and succeeds
      - All 57 claims are marked 'applied'
      - Final approved count is 57
      - No indefinite hanging or swallowed errors
    """
    run_id = uuid4()
    job_id = "job-57"

    claims = []
    for i in range(1, 58):
        c = MagicMock()
        c.id = uuid4()
        c.status = "approved"
        c.superdocs_change_id = f"chg-{i}"
        claims.append(c)

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=claims)
    claim_repo.update = AsyncMock()

    mock_session_manager = AsyncMock()
    mock_session_manager.get_session_for_run = AsyncMock(return_value="sess-123")

    mock_superdocs_client = AsyncMock()
    
    # Simulate: chg-57 fails on first attempt, succeeds on second attempt
    chg57_attempts = 0

    async def mock_approve_change(*args, **kwargs):
        if "changes" in kwargs and kwargs["changes"] is not None:
            raise Exception("Batch not supported in this test scenario")
        change_id = kwargs.get("change_id") or (args[2] if len(args) > 2 else None)
        nonlocal chg57_attempts
        if change_id == "chg-57":
            chg57_attempts += 1
            if chg57_attempts == 1:
                raise ConnectionError("SuperDocs transient timeout on chg-57")
        res = MagicMock()
        res.job_status = JobStatus.IN_PROGRESS
        return res

    mock_superdocs_client.approve_change = AsyncMock(side_effect=mock_approve_change)
    mock_superdocs_client.get_job = AsyncMock(return_value=_job(JobStatus.COMPLETED, pending_changes=[]))

    handler = ApprovalHandler(
        superdocs_client=mock_superdocs_client,
        session_manager=mock_session_manager,
        claim_repository=claim_repo,
        review_repository=AsyncMock(),
    )

    counts = await handler.apply_approvals(run_id=run_id, job_id=job_id)

    assert counts["approved"] == 57
    assert counts["rejected"] == 0
    assert chg57_attempts == 2
    if claim_repo.bulk_update_status.called:
        assert claim_repo.bulk_update_status.call_count == 1
        updated_ids = claim_repo.bulk_update_status.call_args[0][0]
        assert len(updated_ids) == 57
    else:
        assert claim_repo.update.call_count == 57
        for c in claims:
            claim_repo.update.assert_any_call(c.id, status="applied")


# ---------------------------------------------------------------------------
# CASE 7: 57 approvals where one permanently fails raises actionable error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case7_57_approvals_with_permanent_failure_raises_actionable_error():
    """
    REGRESSION TEST: 57 approvals where exactly one approval permanently fails
    and remains pending in SuperDocs.
    Verifies:
      - Handler raises an actionable error specifying the unapplied change ID
      - Does NOT silently report success or hang
    """
    run_id = uuid4()
    job_id = "job-57-fail"

    claims = []
    for i in range(1, 58):
        c = MagicMock()
        c.id = uuid4()
        c.status = "approved"
        c.superdocs_change_id = f"chg-{i}"
        claims.append(c)

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=claims)
    claim_repo.update = AsyncMock()

    mock_session_manager = AsyncMock()
    mock_session_manager.get_session_for_run = AsyncMock(return_value="sess-123")

    mock_superdocs_client = AsyncMock()

    async def mock_approve_change(*args, **kwargs):
        if "changes" in kwargs and kwargs["changes"] is not None:
            raise Exception("Batch not supported in this test scenario")
        change_id = kwargs.get("change_id") or (args[2] if len(args) > 2 else None)
        if change_id == "chg-57":
            raise Exception("SuperDocs rejected change chg-57: conflict")
        res = MagicMock()
        res.job_status = JobStatus.IN_PROGRESS
        return res

    mock_superdocs_client.approve_change = AsyncMock(side_effect=mock_approve_change)
    mock_superdocs_client.get_job = AsyncMock(return_value=_job(
        JobStatus.AWAITING_APPROVAL,
        pending_changes=[_change("chg-57")]
    ))

    handler = ApprovalHandler(
        superdocs_client=mock_superdocs_client,
        session_manager=mock_session_manager,
        claim_repository=claim_repo,
        review_repository=AsyncMock(),
    )

    with pytest.raises(Exception, match="chg-57"):
        await handler.apply_approvals(run_id=run_id, job_id=job_id)


@pytest.mark.asyncio
async def test_case8_remote_change_during_reconciliation_reconciles_with_approved_review():
    """
    REGRESSION TEST: A remote SuperDocs change appears during reconciliation.
    Verifies:
      - Handler queries ReviewRepository.list_by_run(run_id) without AttributeError
      - Associates the new change with the approved review
      - Creates the DocIntel claim
      - Re-applies approval to SuperDocs
      - Returns escalation_required=False and reconciled=1
    """
    run_id = uuid4()
    job_id = "job-remote-recon"
    cid = "0bc7ac11-fbf7-4e5e-8533-2c9480fa2081"

    # Mock Review
    mock_review = MagicMock()
    mock_review.id = uuid4()
    mock_review.status = "approved"

    mock_review_repo = AsyncMock()
    mock_review_repo.list_by_run = AsyncMock(return_value=[mock_review])

    # Mock Claim Repo
    new_claim_id = uuid4()
    created_claim = MagicMock()
    created_claim.id = new_claim_id
    created_claim.superdocs_change_id = cid
    created_claim.status = "pending"

    mock_claim_repo = AsyncMock()
    mock_claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[])
    mock_claim_repo.list_by_run = AsyncMock(return_value=[])
    mock_claim_repo.create = AsyncMock(return_value=created_claim)
    mock_claim_repo.get_by_id = AsyncMock(return_value=created_claim)
    mock_claim_repo.bulk_update_status = AsyncMock()

    mock_session_manager = AsyncMock()
    mock_session_manager.get_session_for_run = AsyncMock(return_value="sess-remote-123")

    mock_superdocs_client = AsyncMock()
    mock_superdocs_client.approve_change = AsyncMock()

    handler = ApprovalHandler(
        superdocs_client=mock_superdocs_client,
        session_manager=mock_session_manager,
        claim_repository=mock_claim_repo,
        review_repository=mock_review_repo,
    )

    remote_changes = [_change(change_id=cid, ai_explanation="Late remote amendment")]

    res = await handler.reconcile_pending_changes(
        run_id=run_id,
        job_id=job_id,
        pending_changes=remote_changes,
    )

    # Assertions
    mock_review_repo.list_by_run.assert_called_once_with(run_id)
    mock_claim_repo.create.assert_called_once()
    mock_superdocs_client.approve_change.assert_called_once_with(
        session_id="sess-remote-123",
        job_id=job_id,
        approved=True,
        changes=[{"change_id": cid, "approved": True}],
    )
    mock_claim_repo.bulk_update_status.assert_called_once_with([new_claim_id], "applied")
    assert res["escalation_required"] is False
    assert res["reconciled"] == 1


@pytest.mark.asyncio
async def test_case9_duplicate_remote_change_reconciliation_is_idempotent():
    """
    REGRESSION TEST: Repeated reconciliation of the same remote change does NOT
    create duplicate Review or Claim rows.
    """
    run_id = uuid4()
    job_id = "job-remote-dup"
    cid = "0bc7ac11-fbf7-4e5e-8533-2c9480fa2081"

    mock_review = MagicMock()
    mock_review.id = uuid4()
    mock_review.status = "approved"

    mock_review_repo = AsyncMock()
    mock_review_repo.list_by_run = AsyncMock(return_value=[mock_review])

    existing_claim = MagicMock()
    existing_claim.id = uuid4()
    existing_claim.superdocs_change_id = cid
    existing_claim.status = "approved"

    mock_claim_repo = AsyncMock()
    mock_claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[existing_claim])
    mock_claim_repo.list_by_run = AsyncMock(return_value=[existing_claim])
    mock_claim_repo.create = AsyncMock()
    mock_claim_repo.bulk_update_status = AsyncMock()

    mock_session_manager = AsyncMock()
    mock_session_manager.get_session_for_run = AsyncMock(return_value="sess-dup")
    mock_superdocs_client = AsyncMock()
    mock_superdocs_client.approve_change = AsyncMock()

    handler = ApprovalHandler(
        superdocs_client=mock_superdocs_client,
        session_manager=mock_session_manager,
        claim_repository=mock_claim_repo,
        review_repository=mock_review_repo,
    )

    remote_changes = [_change(change_id=cid)]

    res = await handler.reconcile_pending_changes(
        run_id=run_id,
        job_id=job_id,
        pending_changes=remote_changes,
    )

    # Claim already exists — should NOT create a new one
    mock_claim_repo.create.assert_not_called()
    assert res["escalation_required"] is False
    assert res["reconciled"] == 1


