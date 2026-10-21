"""Shared fixtures for API unit tests."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from backend.api.deps import (
    get_current_user,
    require_admin,
    require_reviewer_or_admin,
    require_workspace_access,
    verify_claim_workspace_access,
    verify_document_workspace_access,
    verify_export_workspace_access,
    verify_knowledge_workspace_access,
    verify_review_workspace_access,
    verify_run_workspace_access,
)
from backend.main import app
from backend.models.workspace import Workspace
from backend.models.document import Document
from backend.models.review import Review
from backend.models.claim import Claim


@pytest.fixture(autouse=True)
def api_auth_override():
    """Bypass JWT auth and workspace checks for unit API tests that mock services."""
    mock_user_id = uuid.uuid4()
    mock_user = MagicMock()
    mock_user.id = mock_user_id
    mock_user.email = "api-unit-test@example.com"
    mock_user.role = "admin"
    mock_user.is_active = True

    async def override_get_current_user():
        return mock_user

    async def override_require_admin():
        return mock_user

    async def override_require_reviewer_or_admin():
        return mock_user

    now = datetime.now(timezone.utc)

    async def override_require_workspace_access(workspace_id: UUID):
        return Workspace(
            id=workspace_id,
            name="API Unit Test Workspace",
            owner_user_id=mock_user_id,
            status="active",
            workflow_type=None,
            created_at=now,
            updated_at=now,
        )

    async def override_verify_document(document_id: UUID):
        return Document(
            id=document_id,
            workspace_id=uuid.uuid4(),
            filename="test.pdf",
            storage_path="path/test.pdf",
            mime_type="application/pdf",
            checksum="abc123",
            processing_status="pending",
            document_role="product_spec",
            created_at=now,
            updated_at=now,
        )

    async def override_verify_review(review_id: UUID):
        return Review(
            id=review_id,
            workflow_run_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            status="in_review",
            created_at=now,
            updated_at=now,
        )

    async def override_verify_run(run_id: UUID):
        from backend.models.workflow import WorkflowRun
        return WorkflowRun(
            id=run_id,
            workspace_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            status="queued",
            workflow_version="1.0.0",
            created_by="api-unit-test@example.com",
            version_number=1,
            created_at=now,
            updated_at=now,
        )

    async def override_verify_claim(claim_id: UUID):
        return Claim(
            id=claim_id,
            workflow_run_id=uuid.uuid4(),
            review_id=uuid.uuid4(),
            claim_type="tariff_code",
            content="test claim",
            status="pending",
        )

    async def override_verify_export(export_id: UUID):
        export = MagicMock()
        export.id = export_id
        export.review_id = uuid.uuid4()
        export.filename = "export.docx"
        return export

    async def override_verify_knowledge(entry_id: UUID):
        entry = MagicMock()
        entry.id = str(entry_id)
        entry.workspace_id = str(uuid.uuid4())
        return entry

    overrides = {
        get_current_user: override_get_current_user,
        require_admin: override_require_admin,
        require_reviewer_or_admin: override_require_reviewer_or_admin,
        require_workspace_access: override_require_workspace_access,
        verify_document_workspace_access: override_verify_document,
        verify_run_workspace_access: override_verify_run,
        verify_review_workspace_access: override_verify_review,
        verify_claim_workspace_access: override_verify_claim,
        verify_export_workspace_access: override_verify_export,
        verify_knowledge_workspace_access: override_verify_knowledge,
    }

    for dep, override in overrides.items():
        app.dependency_overrides[dep] = override

    yield

    for dep in overrides:
        app.dependency_overrides.pop(dep, None)
