# tests/unit/api/test_deps.py
"""
Tests for authentication and authorization dependencies.
"""
import pytest
from uuid import uuid4
from datetime import timedelta
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    get_current_user,
    require_admin,
    require_reviewer_or_admin,
    require_workspace_access
)
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.repositories.user import UserRepository
from backend.repositories.workspace import WorkspaceRepository
from backend.core.auth.security import create_access_token, create_refresh_token


@pytest.fixture
async def user_repo(db_session: AsyncSession):
    return UserRepository(db_session)


@pytest.fixture
async def workspace_repo(db_session: AsyncSession):
    return WorkspaceRepository(db_session)


@pytest.fixture
async def test_user(user_repo: UserRepository):
    """Create a test user"""
    user = await user_repo.create(
        email="test@example.com",
        password_hash="hashed_password",
        name="Test User",
        role="user"
    )
    return user


@pytest.fixture
async def test_reviewer(user_repo: UserRepository):
    """Create a test reviewer"""
    reviewer = await user_repo.create(
        email="reviewer@example.com",
        password_hash="hashed_password",
        name="Test Reviewer",
        role="reviewer"
    )
    return reviewer


@pytest.fixture
async def test_admin(user_repo: UserRepository):
    """Create a test admin"""
    admin = await user_repo.create(
        email="admin@example.com",
        password_hash="hashed_password",
        name="Test Admin",
        role="admin"
    )
    return admin


@pytest.fixture
async def test_workspace(workspace_repo: WorkspaceRepository, test_user: User):
    """Create a test workspace"""
    workspace = await workspace_repo.create(
        name="Test Workspace",
        owner_id=str(test_user.id)
    )
    return workspace


class TestGetCurrentUser:
    """Tests for get_current_user dependency"""

    async def test_valid_token_returns_user(self, test_user: User, db_session: AsyncSession):
        """Valid access token should return user"""
        # Create valid access token
        token = create_access_token(
            data={"sub": str(test_user.id), "email": test_user.email, "role": test_user.role},
            expires_delta=timedelta(minutes=15)
        )

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        user = await get_current_user(credentials=credentials, db=db_session)

        assert user.id == test_user.id
        assert user.email == test_user.email
        assert user.role == test_user.role

    async def test_invalid_token_raises_401(self, db_session: AsyncSession):
        """Invalid token should raise 401"""
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid.token.string"
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    async def test_refresh_token_type_raises_401(self, test_user: User, db_session: AsyncSession):
        """Refresh token (not access token) should raise 401"""
        # Create refresh token instead of access token
        token = create_refresh_token(
            data={"sub": str(test_user.id)},
            expires_delta=timedelta(days=7)
        )

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

        assert exc_info.value.status_code == 401

    async def test_nonexistent_user_raises_401(self, db_session: AsyncSession):
        """Token for nonexistent user should raise 401"""
        fake_user_id = uuid4()
        token = create_access_token(
            data={"sub": str(fake_user_id), "email": "fake@example.com", "role": "user"},
            expires_delta=timedelta(minutes=15)
        )

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

        assert exc_info.value.status_code == 401

    async def test_inactive_user_raises_401(self, user_repo: UserRepository, db_session: AsyncSession):
        """Inactive user should raise 401"""
        # Create inactive user
        inactive_user = await user_repo.create(
            email="inactive@example.com",
            password_hash="hashed_password",
            name="Inactive User",
            role="user",
            is_active=False
        )

        token = create_access_token(
            data={"sub": str(inactive_user.id), "email": inactive_user.email, "role": inactive_user.role},
            expires_delta=timedelta(minutes=15)
        )

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

        assert exc_info.value.status_code == 401
        assert "Inactive user" in exc_info.value.detail


class TestRequireAdmin:
    """Tests for require_admin dependency"""

    async def test_admin_user_passes(self, test_admin: User):
        """Admin user should pass"""
        result = await require_admin(current_user=test_admin)
        assert result == test_admin

    async def test_reviewer_user_raises_403(self, test_reviewer: User):
        """Reviewer user should raise 403"""
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=test_reviewer)

        assert exc_info.value.status_code == 403
        assert "Admin access required" in exc_info.value.detail

    async def test_regular_user_raises_403(self, test_user: User):
        """Regular user should raise 403"""
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=test_user)

        assert exc_info.value.status_code == 403


class TestRequireReviewerOrAdmin:
    """Tests for require_reviewer_or_admin dependency"""

    async def test_admin_user_passes(self, test_admin: User):
        """Admin user should pass"""
        result = await require_reviewer_or_admin(current_user=test_admin)
        assert result == test_admin

    async def test_reviewer_user_passes(self, test_reviewer: User):
        """Reviewer user should pass"""
        result = await require_reviewer_or_admin(current_user=test_reviewer)
        assert result == test_reviewer

    async def test_regular_user_raises_403(self, test_user: User):
        """Regular user should raise 403"""
        with pytest.raises(HTTPException) as exc_info:
            await require_reviewer_or_admin(current_user=test_user)

        assert exc_info.value.status_code == 403
        assert "Reviewer or admin access required" in exc_info.value.detail


class TestRequireWorkspaceAccess:
    """Tests for require_workspace_access dependency"""

    async def test_workspace_owner_has_access(
        self,
        test_workspace: Workspace,
        test_user: User,
        db_session: AsyncSession
    ):
        """Workspace owner should have access"""
        workspace = await require_workspace_access(
            workspace_id=test_workspace.id,
            current_user=test_user,
            db=db_session
        )

        assert workspace.id == test_workspace.id

    async def test_non_owner_raises_403(
        self,
        test_workspace: Workspace,
        test_reviewer: User,
        db_session: AsyncSession
    ):
        """Non-owner should raise 403"""
        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_access(
                workspace_id=test_workspace.id,
                current_user=test_reviewer,
                db=db_session
            )

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail

    async def test_admin_has_access_to_any_workspace(
        self,
        test_workspace: Workspace,
        test_admin: User,
        db_session: AsyncSession
    ):
        """Admin should have access to any workspace"""
        workspace = await require_workspace_access(
            workspace_id=test_workspace.id,
            current_user=test_admin,
            db=db_session
        )

        assert workspace.id == test_workspace.id

    async def test_nonexistent_workspace_raises_404(
        self,
        test_user: User,
        db_session: AsyncSession
    ):
        """Nonexistent workspace should raise 404"""
        fake_workspace_id = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await require_workspace_access(
                workspace_id=fake_workspace_id,
                current_user=test_user,
                db=db_session
            )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()
