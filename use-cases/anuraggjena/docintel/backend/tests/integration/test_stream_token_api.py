# backend/tests/integration/test_stream_token_api.py
"""
Integration tests for stream token API and SSE access control.

Tests:
- Stream token endpoint authorization
- Cross-workspace stream access prevention
- SSE access with stream tokens
- Token confusion prevention at API level
"""
import pytest
from httpx import AsyncClient
from uuid import uuid4
from datetime import timedelta

from backend.models.user import User
from backend.models.workspace import Workspace
from backend.models.workflow import WorkflowRun
from backend.repositories.user import UserRepository
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.workflow import WorkflowRunRepository
from backend.core.auth.security import (
    create_access_token,
    create_stream_token,
    TOKEN_TYPE_ACCESS
)


@pytest.mark.asyncio
class TestStreamTokenEndpoint:
    """Test POST /api/v1/auth/stream-token endpoint"""

    async def test_create_stream_token_requires_authentication(
        self,
        client: AsyncClient
    ):
        """Stream token endpoint should require authentication"""
        response = await client.post(
            "/api/v1/auth/stream-token",
            json={"run_id": str(uuid4())}
        )

        assert response.status_code == 401

    async def test_create_stream_token_for_valid_run(
        self,
        client: AsyncClient,
        test_user: User,
        test_workspace: Workspace,
        auth_headers: dict
    ):
        """Should create stream token for user's own run"""
        # Create a workflow run
        from sqlalchemy.ext.asyncio import AsyncSession
        from backend.api.deps import get_db

        async with client as c:
            # Get DB session (using test fixture)
            async for db in get_db():
                run_repo = WorkflowRunRepository(db)
                run = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Request stream token
                response = await c.post(
                    "/api/v1/auth/stream-token",
                    json={"run_id": str(run.id)},
                    headers=auth_headers
                )

                assert response.status_code == 200
                data = response.json()

                assert "stream_token" in data
                assert data["token_type"] == "stream"
                assert data["expires_in"] == 60

                # Verify token is valid stream token
                from backend.core.auth.security import decode_token, TOKEN_TYPE_STREAM
                payload = decode_token(data["stream_token"], expected_type=TOKEN_TYPE_STREAM)
                assert payload["sub"] == str(test_user.id)
                assert payload["run_id"] == str(run.id)

                break

    async def test_create_stream_token_for_nonexistent_run(
        self,
        client: AsyncClient,
        auth_headers: dict
    ):
        """Should return 404 for nonexistent run"""
        response = await client.post(
            "/api/v1/auth/stream-token",
            json={"run_id": str(uuid4())},
            headers=auth_headers
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_create_stream_token_cross_workspace_denied(
        self,
        client: AsyncClient,
        test_user: User,
        test_user_2: User,
        auth_headers: dict,
        auth_headers_user2: dict
    ):
        """Should deny stream token for another user's run"""
        # User 2 creates workspace and run
        async with client as c:
            async for db in get_db():
                # Create workspace for user 2
                workspace_repo = WorkspaceRepository(db)
                workspace_2 = await workspace_repo.create(
                    name="User 2 Workspace",
                    description="",
                    owner_id=str(test_user_2.id)
                )

                # Create run in user 2's workspace
                run_repo = WorkflowRunRepository(db)
                run = await run_repo.create(
                    workspace_id=workspace_2.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # User 1 tries to get stream token for user 2's run
                response = await c.post(
                    "/api/v1/auth/stream-token",
                    json={"run_id": str(run.id)},
                    headers=auth_headers
                )

                assert response.status_code == 403
                assert "denied" in response.json()["detail"].lower()

                break


@pytest.mark.asyncio
class TestSSEStreamAccess:
    """Test GET /api/v1/stream/workflow-run/{run_id} with stream tokens"""

    async def test_sse_requires_stream_token(
        self,
        client: AsyncClient,
        test_workspace: Workspace
    ):
        """SSE endpoint should require stream token"""
        # Create run
        async with client as c:
            async for db in get_db():
                run_repo = WorkflowRunRepository(db)
                run = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Try to access without token
                response = await c.get(f"/api/v1/stream/workflow-run/{run.id}")

                assert response.status_code == 401

                break

    async def test_sse_rejects_access_token(
        self,
        client: AsyncClient,
        test_user: User,
        test_workspace: Workspace
    ):
        """SSE should reject access tokens (only stream tokens allowed)"""
        async with client as c:
            async for db in get_db():
                # Create run
                run_repo = WorkflowRunRepository(db)
                run = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Create access token
                access_token = create_access_token(
                    {"sub": str(test_user.id), "email": test_user.email, "role": test_user.role},
                    timedelta(minutes=15)
                )

                # Try to use access token for SSE
                response = await c.get(
                    f"/api/v1/stream/workflow-run/{run.id}?token={access_token}"
                )

                # Should be rejected due to wrong token type
                assert response.status_code == 401

                break

    async def test_sse_accepts_valid_stream_token(
        self,
        client: AsyncClient,
        test_user: User,
        test_workspace: Workspace
    ):
        """SSE should accept valid stream token"""
        async with client as c:
            async for db in get_db():
                # Create run
                run_repo = WorkflowRunRepository(db)
                run = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Create stream token
                stream_token = create_stream_token(
                    test_user.id,
                    run.id,
                    timedelta(seconds=60)
                )

                # Access SSE with stream token
                response = await c.get(
                    f"/api/v1/stream/workflow-run/{run.id}?token={stream_token}"
                )

                # Should accept connection (200 or streaming response)
                assert response.status_code in [200, 201]

                break

    async def test_sse_rejects_stream_token_for_wrong_run(
        self,
        client: AsyncClient,
        test_user: User,
        test_workspace: Workspace
    ):
        """SSE should reject stream token when run_id doesn't match"""
        async with client as c:
            async for db in get_db():
                # Create two runs
                run_repo = WorkflowRunRepository(db)
                run_1 = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                run_2 = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Create stream token for run_1
                stream_token = create_stream_token(
                    test_user.id,
                    run_1.id,
                    timedelta(seconds=60)
                )

                # Try to use token for run_2
                response = await c.get(
                    f"/api/v1/stream/workflow-run/{run_2.id}?token={stream_token}"
                )

                # Should be rejected due to run_id mismatch
                assert response.status_code == 403
                assert "not valid for this run" in response.json()["detail"].lower()

                break

    async def test_sse_rejects_expired_stream_token(
        self,
        client: AsyncClient,
        test_user: User,
        test_workspace: Workspace
    ):
        """SSE should reject expired stream tokens"""
        async with client as c:
            async for db in get_db():
                # Create run
                run_repo = WorkflowRunRepository(db)
                run = await run_repo.create(
                    workspace_id=test_workspace.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Create expired stream token
                stream_token = create_stream_token(
                    test_user.id,
                    run.id,
                    timedelta(seconds=-10)  # Already expired
                )

                # Try to use expired token
                response = await c.get(
                    f"/api/v1/stream/workflow-run/{run.id}?token={stream_token}"
                )

                # Should be rejected due to expiration
                assert response.status_code == 401

                break


@pytest.mark.asyncio
class TestStreamTokenCrossWorkspace:
    """Test workspace isolation with stream tokens"""

    async def test_stream_token_enforces_workspace_boundaries(
        self,
        client: AsyncClient,
        test_user: User,
        test_user_2: User
    ):
        """Stream token should not grant access to other user's runs"""
        async with client as c:
            async for db in get_db():
                # Create workspaces for both users
                workspace_repo = WorkspaceRepository(db)
                workspace_1 = await workspace_repo.create(
                    name="User 1 Workspace",
                    description="",
                    owner_id=str(test_user.id)
                )
                workspace_2 = await workspace_repo.create(
                    name="User 2 Workspace",
                    description="",
                    owner_id=str(test_user_2.id)
                )

                # Create runs in each workspace
                run_repo = WorkflowRunRepository(db)
                run_1 = await run_repo.create(
                    workspace_id=workspace_1.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                run_2 = await run_repo.create(
                    workspace_id=workspace_2.id,
                    workflow_slug="test_workflow",
                    document_ids=[]
                )
                await db.commit()

                # Create stream token for user 2's run using user 1's ID
                # This simulates token forgery attempt
                forged_token = create_stream_token(
                    test_user.id,
                    run_2.id,
                    timedelta(seconds=60)
                )

                # Try to use forged token
                response = await c.get(
                    f"/api/v1/stream/workflow-run/{run_2.id}?token={forged_token}"
                )

                # Should be rejected due to workspace ownership
                assert response.status_code == 403

                break
