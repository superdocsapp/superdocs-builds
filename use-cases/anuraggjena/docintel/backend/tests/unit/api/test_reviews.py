import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from uuid import uuid4
from datetime import datetime, timezone

from backend.main import app
from backend.models.review import Review
from backend.models.claim import Claim
from backend.api.v1.reviews import get_review_service


@pytest.mark.asyncio
async def test_create_review():
    """Test POST /api/v1/reviews"""
    mock_service = AsyncMock()
    workflow_run_id = uuid4()
    workspace_id = uuid4()
    review_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_review = Review(
        id=review_id,
        workflow_run_id=workflow_run_id,
        workspace_id=workspace_id,
        status="in_review",
        reviewer_id="user-123",
        notes=None,
        created_at=now,
        updated_at=now
    )
    mock_service.create_review.return_value = mock_review

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/reviews",
                json={
                    "workflow_run_id": str(workflow_run_id),
                    "workspace_id": str(workspace_id),
                    "reviewer_id": "user-123"
                }
            )

            assert response.status_code == 201
            data = response.json()
            assert data["status"] == "in_review"
            assert data["reviewer_id"] == "user-123"
            assert "id" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_review():
    """Test GET /api/v1/reviews/{review_id}"""
    mock_service = AsyncMock()
    review_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_review = Review(
        id=review_id,
        workflow_run_id=uuid4(),
        workspace_id=uuid4(),
        status="in_review",
        reviewer_id="user-123",
        notes=None,
        created_at=now,
        updated_at=now
    )
    mock_service.get_review.return_value = mock_review

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/reviews/{review_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == str(review_id)
            assert data["status"] == "in_review"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_review_not_found():
    """Test GET /api/v1/reviews/{review_id} with non-existent ID"""
    from uuid import UUID
    from fastapi import HTTPException, status
    from backend.api.deps import verify_review_workspace_access
    mock_service = AsyncMock()
    review_id = uuid4()

    mock_service.get_review.return_value = None

    async def mock_verify_review(review_id: UUID):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found"
        )

    app.dependency_overrides[get_review_service] = lambda: mock_service
    app.dependency_overrides[verify_review_workspace_access] = mock_verify_review

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/reviews/{review_id}")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_workspace_reviews():
    """Test GET /api/v1/reviews/workspace/{workspace_id}"""
    mock_service = AsyncMock()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_service.list_workspace_reviews.return_value = [
        Review(
            id=uuid4(),
            workflow_run_id=uuid4(),
            workspace_id=workspace_id,
            status="in_review",
            reviewer_id="user-123",
            notes=None,
            created_at=now,
            updated_at=now
        ),
        Review(
            id=uuid4(),
            workflow_run_id=uuid4(),
            workspace_id=workspace_id,
            status="approved",
            reviewer_id="user-456",
            notes="All good",
            created_at=now,
            updated_at=now
        )
    ]

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/reviews/workspace/{workspace_id}")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["status"] == "in_review"
            assert data[1]["status"] == "approved"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_review():
    """Test PATCH /api/v1/reviews/{review_id}"""
    mock_service = AsyncMock()
    review_id = uuid4()
    now = datetime.now(timezone.utc)

    updated_review = Review(
        id=review_id,
        workflow_run_id=uuid4(),
        workspace_id=uuid4(),
        status="approved",
        reviewer_id="user-123",
        notes="Looks great!",
        created_at=now,
        updated_at=now
    )
    mock_service.update_review_status.return_value = updated_review

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/reviews/{review_id}",
                json={"status": "approved", "notes": "Looks great!"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "approved"
            assert data["notes"] == "Looks great!"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_review_not_found():
    """Test PATCH /api/v1/reviews/{review_id} with non-existent ID"""
    mock_service = AsyncMock()
    review_id = uuid4()

    mock_service.update_review_status.return_value = None

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/reviews/{review_id}",
                json={"status": "approved"}
            )

            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_claim():
    """Test POST /api/v1/reviews/claims"""
    mock_service = AsyncMock()
    workflow_run_id = uuid4()
    review_id = uuid4()
    claim_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_claim = Claim(
        id=claim_id,
        workflow_run_id=workflow_run_id,
        review_id=review_id,
        claim_type="tariff_code",
        content="8517.62.00",
        status="pending",
        original_content="8517.62.00",
        edited_by=None,
        source_stage="extraction",
        confidence_score=None,
        created_at=now,
        updated_at=now
    )
    mock_service.create_claim.return_value = mock_claim

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/reviews/claims",
                json={
                    "workflow_run_id": str(workflow_run_id),
                    "review_id": str(review_id),
                    "claim_type": "tariff_code",
                    "content": "8517.62.00",
                    "source_stage": "extraction"
                }
            )

            assert response.status_code == 201
            data = response.json()
            assert data["claim_type"] == "tariff_code"
            assert data["content"] == "8517.62.00"
            assert data["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_review_claims():
    """Test GET /api/v1/reviews/{review_id}/claims"""
    mock_service = AsyncMock()
    review_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_service.list_review_claims.return_value = [
        Claim(
            id=uuid4(),
            workflow_run_id=uuid4(),
            review_id=review_id,
            claim_type="tariff_code",
            content="8517.62.00",
            status="pending",
            original_content="8517.62.00",
            edited_by=None,
            source_stage="extraction",
            confidence_score=None,
            created_at=now,
            updated_at=now
        ),
        Claim(
            id=uuid4(),
            workflow_run_id=uuid4(),
            review_id=review_id,
            claim_type="duty_rate",
            content="15%",
            status="approved",
            original_content="15%",
            edited_by=None,
            source_stage="extraction",
            confidence_score="0.95",
            created_at=now,
            updated_at=now
        )
    ]

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/reviews/{review_id}/claims")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["claim_type"] == "tariff_code"
            assert data[1]["claim_type"] == "duty_rate"
            assert data[1]["status"] == "approved"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_claim():
    """Test PATCH /api/v1/reviews/claims/{claim_id}"""
    mock_service = AsyncMock()
    claim_id = uuid4()
    now = datetime.now(timezone.utc)

    updated_claim = Claim(
        id=claim_id,
        workflow_run_id=uuid4(),
        review_id=uuid4(),
        claim_type="tariff_code",
        content="8517.62.01",
        status="edited",
        original_content="8517.62.00",
        edited_by="user-456",
        source_stage="extraction",
        confidence_score=None,
        created_at=now,
        updated_at=now
    )
    mock_service.update_claim.return_value = updated_claim

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/reviews/claims/{claim_id}",
                json={"content": "8517.62.01", "edited_by": "user-456"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["content"] == "8517.62.01"
            assert data["edited_by"] == "user-456"
            assert data["status"] == "edited"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_claim():
    """Test POST /api/v1/reviews/claims/{claim_id}/approve"""
    mock_service = AsyncMock()
    claim_id = uuid4()
    now = datetime.now(timezone.utc)

    approved_claim = Claim(
        id=claim_id,
        workflow_run_id=uuid4(),
        review_id=uuid4(),
        claim_type="tariff_code",
        content="8517.62.00",
        status="approved",
        original_content="8517.62.00",
        edited_by=None,
        source_stage="extraction",
        confidence_score=None,
        created_at=now,
        updated_at=now
    )
    mock_service.approve_claim.return_value = approved_claim

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/approve")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "approved"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reject_claim():
    """Test POST /api/v1/reviews/claims/{claim_id}/reject"""
    mock_service = AsyncMock()
    claim_id = uuid4()
    now = datetime.now(timezone.utc)

    rejected_claim = Claim(
        id=claim_id,
        workflow_run_id=uuid4(),
        review_id=uuid4(),
        claim_type="tariff_code",
        content="8517.62.00",
        status="rejected",
        original_content="8517.62.00",
        edited_by=None,
        source_stage="extraction",
        confidence_score=None,
        created_at=now,
        updated_at=now
    )
    mock_service.reject_claim.return_value = rejected_claim

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/reject")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "rejected"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_claim_not_found_on_update():
    """Test PATCH /api/v1/reviews/claims/{claim_id} with non-existent ID"""
    mock_service = AsyncMock()
    claim_id = uuid4()

    mock_service.update_claim.return_value = None

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/reviews/claims/{claim_id}",
                json={"content": "new content"}
            )

            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_claim_not_found_on_approve():
    """Test POST /api/v1/reviews/claims/{claim_id}/approve with non-existent ID"""
    mock_service = AsyncMock()
    claim_id = uuid4()

    mock_service.approve_claim.return_value = None

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/approve")

            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_all_review_claims():
    """Test POST /api/v1/reviews/{review_id}/approve-all"""
    mock_service = AsyncMock()
    review_id = uuid4()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_review = Review(
        id=review_id,
        workflow_run_id=uuid4(),
        workspace_id=workspace_id,
        status="in_review",
        reviewer_id="user-123",
        notes=None,
        created_at=now,
        updated_at=now
    )

    mock_service.get_review.return_value = mock_review
    mock_service.approve_all_for_review.return_value = {
        "approved_count": 3,
        "review_id": str(review_id)
    }

    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/{review_id}/approve-all")

            assert response.status_code == 200
            data = response.json()
            assert data["approved_count"] == 3
            assert data["review_id"] == str(review_id)
            mock_service.approve_all_for_review.assert_called_once_with(review_id)
    finally:
        app.dependency_overrides.clear()

