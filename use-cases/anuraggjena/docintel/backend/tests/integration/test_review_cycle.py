"""
Integration tests for the review cycle with selective regeneration.

Tests exercise ReviewService with mocked repositories to verify:
- Creating reviews and claims
- Approving, rejecting, and editing claims
- Review status transitions
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from backend.services.review import ReviewService


def make_review(workspace_id=None, workflow_run_id=None, status="in_review"):
    r = MagicMock()
    r.id = uuid4()
    r.workspace_id = str(workspace_id or uuid4())
    r.workflow_run_id = str(workflow_run_id or uuid4())
    r.status = status
    r.reviewer_id = None
    r.notes = None
    r.created_at = datetime.now(timezone.utc)
    return r


def make_claim(review_id=None, workflow_run_id=None, status="pending", content=None):
    c = MagicMock()
    c.id = uuid4()
    c.review_id = str(review_id or uuid4())
    c.workflow_run_id = str(workflow_run_id or uuid4())
    c.content = content or '{"hs_code": "8471.30", "description": "Laptop"}'
    c.status = status
    c.original_content = None
    c.edited_by = None
    c.claim_type = "tariff"
    c.source_stage = None
    c.created_at = datetime.now(timezone.utc)
    return c


def make_service():
    review_repo = MagicMock()
    review_repo.create = AsyncMock()
    review_repo.get_by_id = AsyncMock()
    review_repo.list_by_workspace = AsyncMock()
    review_repo.update = AsyncMock()

    claim_repo = MagicMock()
    claim_repo.create = AsyncMock()
    claim_repo.get_by_id = AsyncMock()
    claim_repo.update = AsyncMock()
    claim_repo.list_by_review = AsyncMock()

    service = ReviewService(review_repo, claim_repo)
    return service, review_repo, claim_repo


# ---------------------------------------------------------------------------
# Test: create_review
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_review_returns_review():
    service, review_repo, _ = make_service()

    workspace_id = uuid4()
    workflow_run_id = uuid4()
    expected = make_review(workspace_id=workspace_id, workflow_run_id=workflow_run_id)
    review_repo.create.return_value = expected

    result = await service.create_review(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
    )

    assert result is expected
    review_repo.create.assert_awaited_once_with(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        reviewer_id=None,
        status="in_review",
    )


@pytest.mark.asyncio
async def test_create_review_with_reviewer_id():
    service, review_repo, _ = make_service()

    workspace_id = uuid4()
    workflow_run_id = uuid4()
    reviewer_id = "user-abc"
    expected = make_review(workspace_id=workspace_id, workflow_run_id=workflow_run_id)
    expected.reviewer_id = reviewer_id
    review_repo.create.return_value = expected

    result = await service.create_review(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        reviewer_id=reviewer_id,
    )

    assert result.reviewer_id == reviewer_id
    review_repo.create.assert_awaited_once_with(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        reviewer_id=reviewer_id,
        status="in_review",
    )


# ---------------------------------------------------------------------------
# Test: create_claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_claim_stores_original_content():
    service, _, claim_repo = make_service()

    workflow_run_id = uuid4()
    review_id = uuid4()
    content = '{"hs_code": "8471.30", "description": "Laptop", "duty_rate": "0%"}'
    expected = make_claim(review_id=review_id, workflow_run_id=workflow_run_id, content=content)
    expected.original_content = content
    claim_repo.create.return_value = expected

    result = await service.create_claim(
        workflow_run_id=workflow_run_id,
        claim_type="tariff",
        content=content,
        review_id=review_id,
        source_stage="extract",
    )

    assert result is expected
    call_kwargs = claim_repo.create.call_args.kwargs
    assert call_kwargs["content"] == content
    assert call_kwargs["original_content"] == content
    assert call_kwargs["status"] == "pending"


@pytest.mark.asyncio
async def test_create_claim_without_review_id():
    service, _, claim_repo = make_service()

    workflow_run_id = uuid4()
    content = '{"hs_code": "4202.11"}'
    expected = make_claim(workflow_run_id=workflow_run_id, content=content)
    claim_repo.create.return_value = expected

    result = await service.create_claim(
        workflow_run_id=workflow_run_id,
        claim_type="tariff",
        content=content,
    )

    assert result is expected
    call_kwargs = claim_repo.create.call_args.kwargs
    assert call_kwargs["review_id"] is None


# ---------------------------------------------------------------------------
# Test: approve_claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_claim_sets_status_approved():
    service, _, claim_repo = make_service()

    claim_id = uuid4()
    approved_claim = make_claim(status="approved")
    approved_claim.id = claim_id
    claim_repo.update.return_value = approved_claim

    result = await service.approve_claim(claim_id)

    assert result.status == "approved"
    claim_repo.update.assert_awaited_once_with(claim_id, status="approved")


@pytest.mark.asyncio
async def test_approve_claim_returns_none_for_missing():
    service, _, claim_repo = make_service()

    claim_repo.update.return_value = None

    result = await service.approve_claim(uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# Test: reject_claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_claim_sets_status_rejected():
    service, _, claim_repo = make_service()

    claim_id = uuid4()
    rejected_claim = make_claim(status="rejected")
    rejected_claim.id = claim_id
    claim_repo.update.return_value = rejected_claim

    result = await service.reject_claim(claim_id)

    assert result.status == "rejected"
    claim_repo.update.assert_awaited_once_with(claim_id, status="rejected")


# ---------------------------------------------------------------------------
# Test: update_claim (edit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_claim_preserves_original_and_sets_edited():
    service, _, claim_repo = make_service()

    claim_id = uuid4()
    original_content = '{"hs_code": "8471.30", "description": "Laptop"}'
    new_content = '{"hs_code": "8471.30", "description": "Laptop Computer", "duty_rate": "0%"}'
    editor = "user-xyz"

    edited_claim = make_claim(status="edited", content=new_content)
    edited_claim.id = claim_id
    edited_claim.original_content = original_content
    edited_claim.edited_by = editor
    claim_repo.update.return_value = edited_claim

    result = await service.update_claim(claim_id, content=new_content, edited_by=editor)

    assert result.status == "edited"
    assert result.content == new_content
    assert result.original_content == original_content
    assert result.edited_by == editor
    claim_repo.update.assert_awaited_once_with(
        claim_id,
        content=new_content,
        edited_by=editor,
        status="edited",
    )


@pytest.mark.asyncio
async def test_update_claim_without_editor():
    service, _, claim_repo = make_service()

    claim_id = uuid4()
    new_content = '{"hs_code": "9403.20"}'
    edited_claim = make_claim(status="edited", content=new_content)
    edited_claim.id = claim_id
    claim_repo.update.return_value = edited_claim

    result = await service.update_claim(claim_id, content=new_content)

    assert result.status == "edited"
    call_kwargs = claim_repo.update.call_args.kwargs
    assert call_kwargs["edited_by"] is None


# ---------------------------------------------------------------------------
# Test: update_review_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_review_status_to_approved():
    service, review_repo, _ = make_service()

    review_id = uuid4()
    updated_review = make_review(status="approved")
    updated_review.id = review_id
    review_repo.update.return_value = updated_review

    result = await service.update_review_status(review_id, status="approved")

    assert result.status == "approved"
    review_repo.update.assert_awaited_once_with(review_id, status="approved", notes=None)


@pytest.mark.asyncio
async def test_update_review_status_with_notes():
    service, review_repo, _ = make_service()

    review_id = uuid4()
    notes = "All claims verified against HTS schedule."
    updated_review = make_review(status="approved")
    updated_review.id = review_id
    updated_review.notes = notes
    review_repo.update.return_value = updated_review

    result = await service.update_review_status(review_id, status="approved", notes=notes)

    assert result.notes == notes
    review_repo.update.assert_awaited_once_with(review_id, status="approved", notes=notes)


@pytest.mark.asyncio
async def test_update_review_status_to_rejected():
    service, review_repo, _ = make_service()

    review_id = uuid4()
    updated_review = make_review(status="rejected")
    updated_review.id = review_id
    review_repo.update.return_value = updated_review

    result = await service.update_review_status(review_id, status="rejected")

    assert result.status == "rejected"


# ---------------------------------------------------------------------------
# Test: full review cycle — all claims approved -> review completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_cycle_all_approved():
    """
    Simulates: create review, create 2 claims, approve both, mark review approved.
    Verifies review reaches approved state.
    """
    service, review_repo, claim_repo = make_service()

    workspace_id = uuid4()
    workflow_run_id = uuid4()

    # 1. Create review
    review = make_review(workspace_id=workspace_id, workflow_run_id=workflow_run_id)
    review_repo.create.return_value = review
    created_review = await service.create_review(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
    )
    assert created_review.status == "in_review"

    # 2. Create two claims
    claim1_content = '{"hs_code": "8471.30", "description": "Laptop"}'
    claim2_content = '{"hs_code": "8517.12", "description": "Smartphone"}'
    claim1 = make_claim(review_id=review.id, workflow_run_id=workflow_run_id, content=claim1_content)
    claim2 = make_claim(review_id=review.id, workflow_run_id=workflow_run_id, content=claim2_content)
    claim_repo.create.side_effect = [claim1, claim2]

    c1 = await service.create_claim(
        workflow_run_id=workflow_run_id,
        claim_type="tariff",
        content=claim1_content,
        review_id=review.id,
    )
    c2 = await service.create_claim(
        workflow_run_id=workflow_run_id,
        claim_type="tariff",
        content=claim2_content,
        review_id=review.id,
    )

    # 3. Approve both claims
    approved_c1 = make_claim(review_id=review.id, status="approved")
    approved_c1.id = c1.id
    approved_c2 = make_claim(review_id=review.id, status="approved")
    approved_c2.id = c2.id
    claim_repo.update.side_effect = [approved_c1, approved_c2]

    r1 = await service.approve_claim(c1.id)
    r2 = await service.approve_claim(c2.id)
    assert r1.status == "approved"
    assert r2.status == "approved"

    # 4. List claims to check all approved
    claim_repo.list_by_review.return_value = [approved_c1, approved_c2]
    claims = await service.list_review_claims(review.id)
    assert all(c.status == "approved" for c in claims)

    # 5. Mark review as approved/completed
    approved_review = make_review(status="approved")
    approved_review.id = review.id
    review_repo.update.return_value = approved_review

    final_review = await service.update_review_status(review.id, status="approved")
    assert final_review.status == "approved"


# ---------------------------------------------------------------------------
# Test: mixed approved/rejected claims -> review reaches terminal state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_cycle_mixed_approved_rejected():
    """
    Simulates: create review, create 3 claims, approve 2, reject 1.
    Mark review as rejected since some claims were rejected.
    """
    service, review_repo, claim_repo = make_service()

    workspace_id = uuid4()
    workflow_run_id = uuid4()

    # 1. Create review
    review = make_review(workspace_id=workspace_id, workflow_run_id=workflow_run_id)
    review_repo.create.return_value = review
    await service.create_review(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
    )

    # 2. Create 3 claims
    claims_content = [
        '{"hs_code": "8471.30", "description": "Laptop"}',
        '{"hs_code": "8517.12", "description": "Smartphone"}',
        '{"hs_code": "9999.99", "description": "Unknown item"}',
    ]
    raw_claims = [
        make_claim(review_id=review.id, workflow_run_id=workflow_run_id, content=c)
        for c in claims_content
    ]
    claim_repo.create.side_effect = raw_claims

    created = []
    for content in claims_content:
        c = await service.create_claim(
            workflow_run_id=workflow_run_id,
            claim_type="tariff",
            content=content,
            review_id=review.id,
        )
        created.append(c)

    # 3. Approve first two, reject third
    approved_c1 = make_claim(review_id=review.id, status="approved")
    approved_c1.id = created[0].id
    approved_c2 = make_claim(review_id=review.id, status="approved")
    approved_c2.id = created[1].id
    rejected_c3 = make_claim(review_id=review.id, status="rejected")
    rejected_c3.id = created[2].id

    claim_repo.update.side_effect = [approved_c1, approved_c2, rejected_c3]

    r1 = await service.approve_claim(created[0].id)
    r2 = await service.approve_claim(created[1].id)
    r3 = await service.reject_claim(created[2].id)

    assert r1.status == "approved"
    assert r2.status == "approved"
    assert r3.status == "rejected"

    # 4. List claims — mixed state
    claim_repo.list_by_review.return_value = [approved_c1, approved_c2, rejected_c3]
    claims = await service.list_review_claims(review.id)
    statuses = {c.status for c in claims}
    assert "approved" in statuses
    assert "rejected" in statuses

    # 5. Mark review as rejected (terminal state for mixed with rejections)
    rejected_review = make_review(status="rejected")
    rejected_review.id = review.id
    review_repo.update.return_value = rejected_review

    final_review = await service.update_review_status(
        review.id,
        status="rejected",
        notes="Claim 3 has invalid HS code.",
    )
    assert final_review.status == "rejected"


# ---------------------------------------------------------------------------
# Test: edit then approve claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edit_then_approve_claim():
    """
    Edit a claim's content, then approve it.
    Verifies the edited status transitions to approved.
    """
    service, _, claim_repo = make_service()

    claim_id = uuid4()
    original_content = '{"hs_code": "8471.30", "description": "Laptop"}'
    edited_content = '{"hs_code": "8471.30", "description": "Laptop Computer", "duty_rate": "0%"}'
    editor = "reviewer-1"

    # Edit the claim
    edited_claim = make_claim(status="edited", content=edited_content)
    edited_claim.id = claim_id
    edited_claim.original_content = original_content
    edited_claim.edited_by = editor

    approved_claim = make_claim(status="approved", content=edited_content)
    approved_claim.id = claim_id
    approved_claim.original_content = original_content
    approved_claim.edited_by = editor

    claim_repo.update.side_effect = [edited_claim, approved_claim]

    updated = await service.update_claim(claim_id, content=edited_content, edited_by=editor)
    assert updated.status == "edited"
    assert updated.content == edited_content
    assert updated.original_content == original_content

    approved = await service.approve_claim(claim_id)
    assert approved.status == "approved"


# ---------------------------------------------------------------------------
# Test: get_review
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_review_by_id():
    service, review_repo, _ = make_service()

    review_id = uuid4()
    expected = make_review()
    expected.id = review_id
    review_repo.get_by_id.return_value = expected

    result = await service.get_review(review_id)

    assert result is expected
    review_repo.get_by_id.assert_awaited_once_with(review_id)


@pytest.mark.asyncio
async def test_get_review_returns_none_for_missing():
    service, review_repo, _ = make_service()

    review_repo.get_by_id.return_value = None

    result = await service.get_review(uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# Test: list_review_claims
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_review_claims():
    service, _, claim_repo = make_service()

    review_id = uuid4()
    claims = [
        make_claim(review_id=review_id, status="approved"),
        make_claim(review_id=review_id, status="rejected"),
        make_claim(review_id=review_id, status="pending"),
    ]
    claim_repo.list_by_review.return_value = claims

    result = await service.list_review_claims(review_id)

    assert len(result) == 3
    claim_repo.list_by_review.assert_awaited_once_with(review_id)


# ---------------------------------------------------------------------------
# Test: list_workspace_reviews
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_workspace_reviews():
    service, review_repo, _ = make_service()

    workspace_id = uuid4()
    reviews = [make_review(workspace_id=workspace_id) for _ in range(3)]
    review_repo.list_by_workspace.return_value = reviews

    result = await service.list_workspace_reviews(workspace_id)

    assert len(result) == 3
    review_repo.list_by_workspace.assert_awaited_once_with(workspace_id)
