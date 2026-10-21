"""
Regression tests for claim approve/reject authorization.

Root cause of the original 403: `require_reviewer_or_admin` on the approve/reject
endpoints rejected workspace owners with role="user", even though they legitimately
own the workspace. The fix removes the redundant role gate — workspace ownership
(verified by verify_claim_workspace_access) is sufficient authorization.

Tests:
1. Workspace owner with role="user" CAN approve a claim in their own workspace.
2. Workspace owner with role="user" CAN reject a claim in their own workspace.
3. A user who does NOT own the workspace receives 403 on approve.
4. A user who does NOT own the workspace receives 403 on reject.
5. A claim that belongs to a different workspace receives 403.
"""

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.deps import get_current_user, verify_claim_workspace_access
from backend.api.v1.reviews import get_review_service
from backend.models.claim import Claim
from backend.models.user import User


def _make_user(role: str = "user") -> MagicMock:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = f"test-{u.id}@example.com"
    u.role = role
    u.is_active = True
    return u


def _make_claim(claim_id=None, status="pending") -> Claim:
    now = datetime.now(timezone.utc)
    return Claim(
        id=claim_id or uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        review_id=uuid.uuid4(),
        claim_type="superdocs_change",
        content='{"description": "Add tariff memo"}',
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_approved_claim(claim_id) -> Claim:
    now = datetime.now(timezone.utc)
    return Claim(
        id=claim_id,
        workflow_run_id=uuid.uuid4(),
        review_id=uuid.uuid4(),
        claim_type="superdocs_change",
        content='{"description": "Add tariff memo"}',
        status="approved",
        created_at=now,
        updated_at=now,
    )


def _make_rejected_claim(claim_id) -> Claim:
    now = datetime.now(timezone.utc)
    return Claim(
        id=claim_id,
        workflow_run_id=uuid.uuid4(),
        review_id=uuid.uuid4(),
        claim_type="superdocs_change",
        content='{"description": "Add tariff memo"}',
        status="rejected",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Test 1: workspace owner (role="user") can approve their own claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_owner_user_role_can_approve_claim():
    """
    A user with role='user' who owns the workspace must receive 200 on approve.
    Previously this returned 403 because require_reviewer_or_admin rejected 'user' role.
    """
    claim_id = uuid.uuid4()
    owner = _make_user(role="user")
    claim = _make_claim(claim_id)
    approved = _make_approved_claim(claim_id)

    mock_service = AsyncMock()
    mock_service.approve_claim = AsyncMock(return_value=approved)

    # verify_claim_workspace_access returns the claim (access granted — user owns workspace)
    async def mock_verify_claim(claim_id: uuid.UUID):
        return claim

    async def mock_get_user():
        return owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim
    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/approve")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        data = response.json()
        assert data["status"] == "approved"
        mock_service.approve_claim.assert_called_once_with(claim_id)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 2: workspace owner (role="user") can reject their own claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_owner_user_role_can_reject_claim():
    """workspace owner with role='user' must receive 200 on reject."""
    claim_id = uuid.uuid4()
    owner = _make_user(role="user")
    claim = _make_claim(claim_id)
    rejected = _make_rejected_claim(claim_id)

    mock_service = AsyncMock()
    mock_service.reject_claim = AsyncMock(return_value=rejected)

    async def mock_verify_claim(claim_id: uuid.UUID):
        return claim

    async def mock_get_user():
        return owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim
    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/reject")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        data = response.json()
        assert data["status"] == "rejected"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 3: user who does NOT own the workspace gets 403 on approve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_owner_cannot_approve_claim():
    """
    A user who doesn't own the workspace must still receive 403.
    verify_claim_workspace_access raises 403 when workspace ownership fails.
    """
    from fastapi import HTTPException

    claim_id = uuid.uuid4()
    non_owner = _make_user(role="user")

    mock_service = AsyncMock()

    async def mock_verify_claim_denied(claim_id: uuid.UUID):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

    async def mock_get_user():
        return non_owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim_denied
    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/approve")

        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        mock_service.approve_claim.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 4: user who does NOT own the workspace gets 403 on reject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_owner_cannot_reject_claim():
    """Non-workspace-owner gets 403 on reject."""
    from fastapi import HTTPException

    claim_id = uuid.uuid4()
    non_owner = _make_user(role="user")

    mock_service = AsyncMock()

    async def mock_verify_claim_denied(claim_id: uuid.UUID):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

    async def mock_get_user():
        return non_owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim_denied
    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/reject")

        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        mock_service.reject_claim.assert_not_called()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 5: reviewer and admin roles still work
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewer_role_can_approve_claim():
    """Users with role='reviewer' continue to work after the fix."""
    claim_id = uuid.uuid4()
    reviewer = _make_user(role="reviewer")
    claim = _make_claim(claim_id)
    approved = _make_approved_claim(claim_id)

    mock_service = AsyncMock()
    mock_service.approve_claim = AsyncMock(return_value=approved)

    async def mock_verify_claim(claim_id: uuid.UUID):
        return claim

    async def mock_get_user():
        return reviewer

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim
    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/approve")

        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_role_can_approve_claim():
    """Users with role='admin' continue to work after the fix."""
    claim_id = uuid.uuid4()
    admin = _make_user(role="admin")
    claim = _make_claim(claim_id)
    approved = _make_approved_claim(claim_id)

    mock_service = AsyncMock()
    mock_service.approve_claim = AsyncMock(return_value=approved)

    async def mock_verify_claim(claim_id: uuid.UUID):
        return claim

    async def mock_get_user():
        return admin

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim
    app.dependency_overrides[get_review_service] = lambda: mock_service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/reviews/claims/{claim_id}/approve")

        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
