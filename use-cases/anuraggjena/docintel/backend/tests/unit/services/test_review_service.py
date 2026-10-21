import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from backend.services.review import ReviewService
from backend.models.review import Review
from backend.models.claim import Claim
from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.lineage import LineageLinkRepository


@pytest.fixture
def mock_review_repo():
    """Mock review repository"""
    mock = AsyncMock(spec=ReviewRepository)
    return mock


@pytest.fixture
def mock_claim_repo():
    """Mock claim repository"""
    mock = AsyncMock(spec=ClaimRepository)
    return mock


@pytest.fixture
def mock_lineage_link_repo():
    """Mock lineage link repository"""
    mock = AsyncMock(spec=LineageLinkRepository)
    return mock


@pytest.fixture
def review_service(mock_review_repo, mock_claim_repo):
    """Create review service with mocked repositories"""
    return ReviewService(mock_review_repo, mock_claim_repo)


@pytest.fixture
def review_service_with_lineage(mock_review_repo, mock_claim_repo, mock_lineage_link_repo):
    """Create review service with lineage tracking enabled"""
    return ReviewService(mock_review_repo, mock_claim_repo, mock_lineage_link_repo)


@pytest.mark.asyncio
async def test_create_review(review_service, mock_review_repo):
    """Test review creation via service"""
    workflow_run_id = uuid4()
    workspace_id = uuid4()
    reviewer_id = "user-123"

    # Mock return value
    review_mock = MagicMock(spec=Review)
    review_mock.id = uuid4()
    review_mock.workflow_run_id = workflow_run_id
    review_mock.workspace_id = workspace_id
    review_mock.reviewer_id = reviewer_id
    review_mock.status = "in_review"
    review_mock.notes = None
    review_mock.created_at = datetime.now(timezone.utc)
    review_mock.updated_at = datetime.now(timezone.utc)

    mock_review_repo.create.return_value = review_mock

    # Call service
    result = await review_service.create_review(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        reviewer_id=reviewer_id
    )

    # Assertions
    assert result.status == "in_review"
    assert result.workflow_run_id == workflow_run_id
    mock_review_repo.create.assert_called_once_with(
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        reviewer_id=reviewer_id,
        status="in_review"
    )


@pytest.mark.asyncio
async def test_get_review(review_service, mock_review_repo):
    """Test getting review by ID"""
    review_id = uuid4()

    review_mock = MagicMock(spec=Review)
    review_mock.id = review_id
    review_mock.status = "in_review"

    mock_review_repo.get_by_id.return_value = review_mock

    result = await review_service.get_review(review_id)

    assert result is not None
    assert result.id == review_id
    mock_review_repo.get_by_id.assert_called_once_with(review_id)


@pytest.mark.asyncio
async def test_list_workspace_reviews(review_service, mock_review_repo):
    """Test listing reviews for a workspace"""
    workspace_id = uuid4()

    reviews = [
        MagicMock(spec=Review, id=uuid4(), workspace_id=workspace_id),
        MagicMock(spec=Review, id=uuid4(), workspace_id=workspace_id),
    ]

    mock_review_repo.list_by_workspace.return_value = reviews

    result = await review_service.list_workspace_reviews(workspace_id)

    assert len(result) == 2
    mock_review_repo.list_by_workspace.assert_called_once_with(workspace_id)


@pytest.mark.asyncio
async def test_update_review_status(review_service, mock_review_repo):
    """Test updating review status"""
    review_id = uuid4()
    new_status = "approved"
    notes = "Looks good!"

    review_mock = MagicMock(spec=Review)
    review_mock.id = review_id
    review_mock.status = new_status
    review_mock.notes = notes

    mock_review_repo.update.return_value = review_mock

    result = await review_service.update_review_status(
        review_id=review_id,
        status=new_status,
        notes=notes
    )

    assert result.status == new_status
    assert result.notes == notes
    mock_review_repo.update.assert_called_once_with(
        review_id,
        status=new_status,
        notes=notes
    )


@pytest.mark.asyncio
async def test_create_claim(review_service, mock_claim_repo):
    """Test claim creation via service"""
    workflow_run_id = uuid4()
    review_id = uuid4()
    claim_type = "tariff_code"
    content = "8517.62.00"
    source_stage = "extraction"

    claim_mock = MagicMock(spec=Claim)
    claim_mock.id = uuid4()
    claim_mock.workflow_run_id = workflow_run_id
    claim_mock.review_id = review_id
    claim_mock.claim_type = claim_type
    claim_mock.content = content
    claim_mock.original_content = content
    claim_mock.status = "pending"
    claim_mock.source_stage = source_stage

    mock_claim_repo.create.return_value = claim_mock

    result = await review_service.create_claim(
        workflow_run_id=workflow_run_id,
        claim_type=claim_type,
        content=content,
        review_id=review_id,
        source_stage=source_stage
    )

    assert result.claim_type == claim_type
    assert result.content == content
    assert result.status == "pending"
    mock_claim_repo.create.assert_called_once_with(
        workflow_run_id=workflow_run_id,
        review_id=review_id,
        claim_type=claim_type,
        content=content,
        original_content=content,
        status="pending",
        source_stage=source_stage
    )


@pytest.mark.asyncio
async def test_update_claim(review_service, mock_claim_repo):
    """Test updating claim content"""
    claim_id = uuid4()
    new_content = "8517.62.01"
    edited_by = "user-456"

    claim_mock = MagicMock(spec=Claim)
    claim_mock.id = claim_id
    claim_mock.content = new_content
    claim_mock.edited_by = edited_by
    claim_mock.status = "edited"

    mock_claim_repo.update.return_value = claim_mock

    result = await review_service.update_claim(
        claim_id=claim_id,
        content=new_content,
        edited_by=edited_by
    )

    assert result.content == new_content
    assert result.edited_by == edited_by
    assert result.status == "edited"
    mock_claim_repo.update.assert_called_once_with(
        claim_id,
        content=new_content,
        edited_by=edited_by,
        status="edited"
    )


@pytest.mark.asyncio
async def test_approve_claim(review_service, mock_claim_repo):
    """Test approving a claim"""
    claim_id = uuid4()

    claim_mock = MagicMock(spec=Claim)
    claim_mock.id = claim_id
    claim_mock.status = "approved"

    mock_claim_repo.update.return_value = claim_mock

    result = await review_service.approve_claim(claim_id)

    assert result.status == "approved"
    mock_claim_repo.update.assert_called_once_with(claim_id, status="approved")


@pytest.mark.asyncio
async def test_reject_claim(review_service, mock_claim_repo):
    """Test rejecting a claim"""
    claim_id = uuid4()

    claim_mock = MagicMock(spec=Claim)
    claim_mock.id = claim_id
    claim_mock.status = "rejected"

    mock_claim_repo.update.return_value = claim_mock

    result = await review_service.reject_claim(claim_id)

    assert result.status == "rejected"
    mock_claim_repo.update.assert_called_once_with(claim_id, status="rejected")


@pytest.mark.asyncio
async def test_list_review_claims(review_service, mock_claim_repo, mock_review_repo):
    """Test listing claims for a review"""
    review_id = uuid4()
    mock_review_repo.get_by_id.return_value = MagicMock(spec=Review, id=review_id, workflow_run_id=None)

    claims = [
        MagicMock(spec=Claim, id=uuid4(), review_id=review_id, claim_type="tariff_code"),
        MagicMock(spec=Claim, id=uuid4(), review_id=review_id, claim_type="duty_rate"),
    ]

    mock_claim_repo.list_by_review.return_value = claims

    result = await review_service.list_review_claims(review_id)

    assert len(result) == 2
    mock_claim_repo.list_by_review.assert_called_once_with(review_id)


@pytest.mark.asyncio
async def test_regenerate_claim_without_lineage(review_service, mock_claim_repo):
    """Test claim regeneration without lineage tracking"""
    workflow_run_id = uuid4()
    original_claim_id = uuid4()
    new_content = "8517.62.01"

    # Mock original claim
    original_claim = MagicMock(spec=Claim)
    original_claim.id = original_claim_id
    original_claim.claim_type = "tariff_code"
    original_claim.source_stage = "extraction"
    mock_claim_repo.get_by_id.return_value = original_claim

    # Mock new claim creation
    new_claim = MagicMock(spec=Claim)
    new_claim.id = uuid4()
    new_claim.workflow_run_id = workflow_run_id
    new_claim.claim_type = "tariff_code"
    new_claim.content = new_content
    new_claim.status = "pending"
    new_claim.source_stage = "extraction"
    mock_claim_repo.create.return_value = new_claim

    result = await review_service.regenerate_claim(
        original_claim_id=original_claim_id,
        new_content=new_content,
        workflow_run_id=workflow_run_id
    )

    assert result.content == new_content
    assert result.status == "pending"
    mock_claim_repo.get_by_id.assert_called_once_with(original_claim_id)
    mock_claim_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_regenerate_claim_with_lineage(review_service_with_lineage, mock_claim_repo, mock_lineage_link_repo):
    """Test claim regeneration with lineage link creation"""
    workflow_run_id = uuid4()
    original_claim_id = uuid4()
    new_content = "8517.62.01"

    # Mock original claim
    original_claim = MagicMock(spec=Claim)
    original_claim.id = original_claim_id
    original_claim.claim_type = "tariff_code"
    original_claim.source_stage = "extraction"
    mock_claim_repo.get_by_id.return_value = original_claim

    # Mock new claim creation
    new_claim_id = uuid4()
    new_claim = MagicMock(spec=Claim)
    new_claim.id = new_claim_id
    new_claim.workflow_run_id = workflow_run_id
    new_claim.claim_type = "tariff_code"
    new_claim.content = new_content
    new_claim.status = "pending"
    new_claim.source_stage = "extraction"
    mock_claim_repo.create.return_value = new_claim

    result = await review_service_with_lineage.regenerate_claim(
        original_claim_id=original_claim_id,
        new_content=new_content,
        workflow_run_id=workflow_run_id
    )

    # Verify new claim was created
    assert result.content == new_content
    assert result.status == "pending"

    # Verify lineage link was created
    mock_lineage_link_repo.create_link.assert_called_once()
    call_args = mock_lineage_link_repo.create_link.call_args
    assert call_args.kwargs["source_type"] == "claim"
    assert call_args.kwargs["source_id"] == new_claim_id
    assert call_args.kwargs["target_type"] == "claim"
    assert call_args.kwargs["target_id"] == original_claim_id
    assert call_args.kwargs["link_type"] == "regenerated_from"
    assert call_args.kwargs["workflow_run_id"] == workflow_run_id
    assert call_args.kwargs["stage_name"] == "review_regeneration"
    assert "regeneration_reason" in call_args.kwargs["metadata"]


@pytest.mark.asyncio
async def test_regenerate_claim_with_reason(review_service_with_lineage, mock_claim_repo, mock_lineage_link_repo):
    """Test claim regeneration with custom reason"""
    workflow_run_id = uuid4()
    original_claim_id = uuid4()
    new_content = "8517.62.01"
    reason = "incorrect_code"

    # Mock original claim
    original_claim = MagicMock(spec=Claim)
    original_claim.id = original_claim_id
    original_claim.claim_type = "tariff_code"
    original_claim.source_stage = "extraction"
    mock_claim_repo.get_by_id.return_value = original_claim

    # Mock new claim creation
    new_claim_id = uuid4()
    new_claim = MagicMock(spec=Claim)
    new_claim.id = new_claim_id
    mock_claim_repo.create.return_value = new_claim

    await review_service_with_lineage.regenerate_claim(
        original_claim_id=original_claim_id,
        new_content=new_content,
        workflow_run_id=workflow_run_id,
        regeneration_reason=reason
    )

    # Verify lineage link includes custom reason
    call_args = mock_lineage_link_repo.create_link.call_args
    assert call_args.kwargs["metadata"]["regeneration_reason"] == reason


@pytest.mark.asyncio
async def test_regenerate_claim_lineage_error_does_not_fail(review_service_with_lineage, mock_claim_repo, mock_lineage_link_repo):
    """Test that lineage link creation error doesn't fail regeneration"""
    workflow_run_id = uuid4()
    original_claim_id = uuid4()
    new_content = "8517.62.01"

    # Mock original claim
    original_claim = MagicMock(spec=Claim)
    original_claim.id = original_claim_id
    original_claim.claim_type = "tariff_code"
    original_claim.source_stage = "extraction"
    mock_claim_repo.get_by_id.return_value = original_claim

    # Mock new claim creation
    new_claim = MagicMock(spec=Claim)
    new_claim.id = uuid4()
    new_claim.content = new_content
    mock_claim_repo.create.return_value = new_claim

    # Mock lineage link creation failure
    mock_lineage_link_repo.create_link.side_effect = Exception("Database error")

    # Should not raise exception
    result = await review_service_with_lineage.regenerate_claim(
        original_claim_id=original_claim_id,
        new_content=new_content,
        workflow_run_id=workflow_run_id
    )

    # Regeneration should still succeed
    assert result.content == new_content


@pytest.mark.asyncio
async def test_approve_all_for_review(review_service, mock_claim_repo, mock_review_repo):
    """Test bulk approving all pending claims for a review"""
    review_id = uuid4()
    mock_review_repo.get_by_id.return_value = MagicMock(spec=Review, id=review_id, workflow_run_id=None)
    mock_claim_repo.bulk_approve_for_review.return_value = 5

    result = await review_service.approve_all_for_review(review_id)

    assert result["approved_count"] == 5
    assert result["review_id"] == str(review_id)
    mock_claim_repo.bulk_approve_for_review.assert_called_once_with(review_id)
    mock_review_repo.update.assert_called_once_with(review_id, status="approved")


@pytest.mark.asyncio
async def test_approve_all_for_run(review_service, mock_claim_repo, mock_review_repo):
    """Test bulk approving all pending claims for a workflow run"""
    run_id = uuid4()
    mock_claim_repo.bulk_approve_for_run.return_value = 4
    review_mock = MagicMock(spec=Review, id=uuid4())
    mock_review_repo.get_by_workflow_run.return_value = review_mock

    result = await review_service.approve_all_for_run(run_id)

    assert result["approved_count"] == 4
    assert result["workflow_run_id"] == str(run_id)
    mock_claim_repo.bulk_approve_for_run.assert_called_once_with(run_id)
    mock_review_repo.update.assert_called_once_with(review_mock.id, status="approved")


@pytest.mark.asyncio
async def test_approve_claim_cannot_reverse_rejection(review_service, mock_claim_repo):
    """Test that an already rejected claim cannot be approved"""
    claim_id = uuid4()
    claim_mock = MagicMock(spec=Claim, id=claim_id, status="rejected")
    mock_claim_repo.get_by_id.return_value = claim_mock

    result = await review_service.approve_claim(claim_id)

    assert result.status == "rejected"
    mock_claim_repo.update.assert_not_called()


@pytest.mark.asyncio
async def test_reject_claim_cannot_reverse_approval(review_service, mock_claim_repo):
    """Test that an already approved claim cannot be rejected"""
    claim_id = uuid4()
    claim_mock = MagicMock(spec=Claim, id=claim_id, status="approved")
    mock_claim_repo.get_by_id.return_value = claim_mock

    result = await review_service.reject_claim(claim_id)

    assert result.status == "approved"
    mock_claim_repo.update.assert_not_called()

