"""
Integration tests for authorization and cross-workspace isolation.

Tests that users can only access resources in their own workspaces,
and that role-based permissions are properly enforced.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from backend.main import app
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.models.document import Document
from backend.models.workflow import WorkflowRun
from backend.models.review import Review
from backend.models.claim import Claim
from backend.services.auth import AuthService
from backend.repositories.user import UserRepository


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    """Create test user A."""
    user_repo = UserRepository(db_session)

    # Check if user exists
    user = await user_repo.get_by_email("user_a@test.com")
    if user:
        return user

    # Create new user
    user = await user_repo.create(
        email="user_a@test.com",
        password_hash="$2b$12$test_hash_a",
        name="User A",
        role="user"
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    """Create test user B."""
    user_repo = UserRepository(db_session)

    user = await user_repo.get_by_email("user_b@test.com")
    if user:
        return user

    user = await user_repo.create(
        email="user_b@test.com",
        password_hash="$2b$12$test_hash_b",
        name="User B",
        role="user"
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def reviewer(db_session: AsyncSession) -> User:
    """Create reviewer user."""
    user_repo = UserRepository(db_session)

    user = await user_repo.get_by_email("reviewer@test.com")
    if user:
        return user

    user = await user_repo.create(
        email="reviewer@test.com",
        password_hash="$2b$12$test_hash_reviewer",
        name="Reviewer",
        role="reviewer"
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession) -> User:
    """Create admin user."""
    user_repo = UserRepository(db_session)

    user = await user_repo.get_by_email("admin@test.com")
    if user:
        return user

    user = await user_repo.create(
        email="admin@test.com",
        password_hash="$2b$12$test_hash_admin",
        name="Admin",
        role="admin"
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def workspace_a(db_session: AsyncSession, user_a: User) -> Workspace:
    """Create workspace owned by user A."""
    workspace = Workspace(
        name="Workspace A",
        owner_id="system",  # Legacy field
        owner_user_id=user_a.id  # New auth field
    )
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    return workspace


@pytest_asyncio.fixture
async def workspace_b(db_session: AsyncSession, user_b: User) -> Workspace:
    """Create workspace owned by user B."""
    workspace = Workspace(
        name="Workspace B",
        owner_id=user_b.email,  # Using email as owner_id for now (pre-migration schema)
        description="Test workspace for user B"
    )
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    return workspace


def create_access_token(user: User) -> str:
    """Create JWT access token for user."""
    from backend.security import create_access_token
    return create_access_token(data={"sub": user.email})


# ==============================================================================
# Cross-Workspace Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_user_cannot_access_other_users_workspace(
    user_a: User,
    user_b: User,
    workspace_a: Workspace,
    workspace_b: Workspace
):
    """Test that User B cannot access User A's workspace."""
    token_b = create_access_token(user_b)
    headers = {"Authorization": f"Bearer {token_b}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User B tries to access User A's workspace
        response = await client.get(
            f"/api/v1/workspaces/{workspace_a.id}",
            headers=headers
        )
        assert response.status_code == 403
        assert "not own" in response.json()["detail"].lower() or "forbidden" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_can_access_own_workspace(
    user_a: User,
    workspace_a: Workspace
):
    """Test that User A can access their own workspace."""
    token_a = create_access_token(user_a)
    headers = {"Authorization": f"Bearer {token_a}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/workspaces/{workspace_a.id}",
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(workspace_a.id)


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_document(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    workspace_a: Workspace
):
    """Test that User B cannot access User A's documents."""
    # Create document in User A's workspace
    document = Document(
        workspace_id=workspace_a.id,
        filename="test.txt",
        file_size=100,
        mime_type="text/plain",
        storage_path="/test/test.txt"
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)

    token_b = create_access_token(user_b)
    headers = {"Authorization": f"Bearer {token_b}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User B tries to access User A's document
        response = await client.get(
            f"/api/v1/documents/{document.id}",
            headers=headers
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_workflow_run(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    workspace_a: Workspace
):
    """Test that User B cannot access User A's workflow runs."""
    # Create workflow run in User A's workspace
    run = WorkflowRun(
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=running
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    token_b = create_access_token(user_b)
    headers = {"Authorization": f"Bearer {token_b}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User B tries to access User A's run
        response = await client.get(
            f"/api/v1/workspaces/{workspace_a.id}/runs/{run.id}",
            headers=headers
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_review(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    workspace_a: Workspace
):
    """Test that User B cannot access User A's reviews."""
    # Create workflow run and review in User A's workspace
    run = WorkflowRun(
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=completed
    )
    db_session.add(run)
    await db_session.flush()

    review = Review(
        workflow_run_id=run.id,
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=in_review
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    token_b = create_access_token(user_b)
    headers = {"Authorization": f"Bearer {token_b}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User B tries to access User A's review
        response = await client.get(
            f"/api/v1/reviews/{review.id}",
            headers=headers
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_claim(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    workspace_a: Workspace
):
    """Test that User B cannot access User A's claims."""
    # Create workflow run, review, and claim in User A's workspace
    run = WorkflowRun(
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=completed
    )
    db_session.add(run)
    await db_session.flush()

    review = Review(
        workflow_run_id=run.id,
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=in_review
    )
    db_session.add(review)
    await db_session.flush()

    claim = Claim(
        review_id=review.id,
        workflow_run_id=run.id,
        claim_text="Test claim",
        status=pending,
        confidence_score=0.8
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    token_b = create_access_token(user_b)
    headers = {"Authorization": f"Bearer {token_b}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User B tries to approve User A's claim
        response = await client.post(
            f"/api/v1/reviews/claims/{claim.id}/approve",
            headers=headers
        )
        assert response.status_code == 403


# ==============================================================================
# Role-Based Access Control Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_user_role_cannot_approve_claim(
    db_session: AsyncSession,
    user_a: User,
    workspace_a: Workspace
):
    """Test that users with 'user' role cannot approve claims."""
    # Create workflow run, review, and claim in User A's workspace
    run = WorkflowRun(
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=completed
    )
    db_session.add(run)
    await db_session.flush()

    review = Review(
        workflow_run_id=run.id,
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=in_review
    )
    db_session.add(review)
    await db_session.flush()

    claim = Claim(
        review_id=review.id,
        workflow_run_id=run.id,
        claim_text="Test claim",
        status=pending,
        confidence_score=0.8
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    token_a = create_access_token(user_a)
    headers = {"Authorization": f"Bearer {token_a}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A (role=user) tries to approve their own claim
        response = await client.post(
            f"/api/v1/reviews/claims/{claim.id}/approve",
            headers=headers
        )
        assert response.status_code == 403
        assert "reviewer" in response.json()["detail"].lower() or "admin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reviewer_can_approve_claim_in_own_workspace(
    db_session: AsyncSession,
    reviewer: User,
):
    """Test that reviewers can approve claims in their own workspace."""
    # Create workspace for reviewer
    workspace = Workspace(
        name="Reviewer Workspace",
        owner_id=reviewer.email,  # Using email as owner_id for now (pre-migration schema)
        description="Test workspace for reviewer"
    )
    db_session.add(workspace)
    await db_session.flush()

    # Create workflow run, review, and claim
    run = WorkflowRun(
        workspace_id=workspace.id,
        workflow_type="test_workflow",
        status=completed
    )
    db_session.add(run)
    await db_session.flush()

    review = Review(
        workflow_run_id=run.id,
        workspace_id=workspace.id,
        workflow_type="test_workflow",
        status=in_review
    )
    db_session.add(review)
    await db_session.flush()

    claim = Claim(
        review_id=review.id,
        workflow_run_id=run.id,
        claim_text="Test claim",
        status=pending,
        confidence_score=0.8
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    token = create_access_token(reviewer)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Reviewer approves claim in their own workspace
        response = await client.post(
            f"/api/v1/reviews/claims/{claim.id}/approve",
            headers=headers
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_reviewer_cannot_approve_claim_in_other_workspace(
    db_session: AsyncSession,
    user_a: User,
    reviewer: User,
    workspace_a: Workspace
):
    """Test that reviewers cannot approve claims in other users' workspaces."""
    # Create workflow run, review, and claim in User A's workspace
    run = WorkflowRun(
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=completed
    )
    db_session.add(run)
    await db_session.flush()

    review = Review(
        workflow_run_id=run.id,
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=in_review
    )
    db_session.add(review)
    await db_session.flush()

    claim = Claim(
        review_id=review.id,
        workflow_run_id=run.id,
        claim_text="Test claim",
        status=pending,
        confidence_score=0.8
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    token = create_access_token(reviewer)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Reviewer tries to approve claim in User A's workspace
        response = await client.post(
            f"/api/v1/reviews/claims/{claim.id}/approve",
            headers=headers
        )
        assert response.status_code == 403


# ==============================================================================
# Admin Override Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_admin_can_access_any_workspace(
    user_a: User,
    admin: User,
    workspace_a: Workspace
):
    """Test that admins can access any workspace."""
    token_admin = create_access_token(admin)
    headers = {"Authorization": f"Bearer {token_admin}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin accesses User A's workspace
        response = await client.get(
            f"/api/v1/workspaces/{workspace_a.id}",
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(workspace_a.id)


@pytest.mark.asyncio
async def test_admin_can_approve_claim_in_any_workspace(
    db_session: AsyncSession,
    user_a: User,
    admin: User,
    workspace_a: Workspace
):
    """Test that admins can approve claims in any workspace."""
    # Create workflow run, review, and claim in User A's workspace
    run = WorkflowRun(
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=completed
    )
    db_session.add(run)
    await db_session.flush()

    review = Review(
        workflow_run_id=run.id,
        workspace_id=workspace_a.id,
        workflow_type="test_workflow",
        status=in_review
    )
    db_session.add(review)
    await db_session.flush()

    claim = Claim(
        review_id=review.id,
        workflow_run_id=run.id,
        claim_text="Test claim",
        status=pending,
        confidence_score=0.8
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    token_admin = create_access_token(admin)
    headers = {"Authorization": f"Bearer {token_admin}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Admin approves claim in User A's workspace
        response = await client.post(
            f"/api/v1/reviews/claims/{claim.id}/approve",
            headers=headers
        )
        assert response.status_code == 200


# ==============================================================================
# Unauthenticated Access Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_unauthenticated_user_cannot_access_workspace(workspace_a: Workspace):
    """Test that unauthenticated users cannot access workspaces."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/workspaces/{workspace_a.id}")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_rejected():
    """Test that invalid JWT tokens are rejected."""
    headers = {"Authorization": "Bearer invalid_token"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/workspaces", headers=headers)
        assert response.status_code == 401
