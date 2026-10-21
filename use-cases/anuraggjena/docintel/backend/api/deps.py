from typing import AsyncGenerator
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from backend.database import async_session_maker
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.user import UserRepository
from backend.services.workspace import WorkspaceService
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.core.auth.security import decode_token


# OAuth2 scheme for JWT Bearer tokens
security = HTTPBearer()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for database sessions"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Extract and validate JWT access token, return current user.

    Args:
        credentials: HTTP Bearer token credentials
        db: Database session

    Returns:
        Authenticated User instance

    Raises:
        HTTPException 401: Invalid/expired token, user not found, user inactive
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode JWT token
        payload = decode_token(credentials.credentials)

        # Verify token type
        if payload.get("type") != "access":
            raise credentials_exception

        # Extract user ID
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception

        user_id = UUID(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    # Get user from database
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if user is None:
        raise credentials_exception

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
        )

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Require admin role.

    Args:
        current_user: Authenticated user

    Returns:
        User with admin role

    Raises:
        HTTPException 403: User is not an admin
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_reviewer_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Require reviewer or admin role.

    Args:
        current_user: Authenticated user

    Returns:
        User with reviewer or admin role

    Raises:
        HTTPException 403: User is neither reviewer nor admin
    """
    if current_user.role not in ("reviewer", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer or admin access required",
        )
    return current_user


async def get_workspace_service(db: AsyncSession = Depends(get_db)) -> WorkspaceService:
    """Dependency for workspace service"""
    repository = WorkspaceRepository(db)
    return WorkspaceService(repository)


async def require_workspace_access(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Workspace:
    """
    Verify user owns/has access to workspace.

    For Phase 5B: Check workspace.owner_id == str(current_user.id)
    For Phase 6+: Check workspace membership table

    Args:
        workspace_id: Workspace UUID
        current_user: Authenticated user
        db: Database session

    Returns:
        Workspace instance

    Raises:
        HTTPException 403: User does not own workspace
        HTTPException 404: Workspace not found
    """
    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get_by_id(workspace_id)

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace {workspace_id} not found"
        )

    # Phase 5B: Single owner check
    # Phase 6+: Check workspace membership table
    if workspace.owner_user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this workspace"
        )

    return workspace


async def verify_document_workspace_access(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to document via workspace ownership.

    Document → Workspace → owner verification
    """
    from backend.repositories.document import DocumentRepository

    doc_repo = DocumentRepository(db)
    document = await doc_repo.get_by_id(document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found"
        )

    # Verify workspace access
    workspace = await require_workspace_access(
        workspace_id=document.workspace_id,
        current_user=current_user,
        db=db
    )

    return document


async def verify_run_workspace_access(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to workflow run via workspace ownership.

    WorkflowRun → Workspace → owner verification
    """
    from backend.repositories.workflow import WorkflowRunRepository

    run_repo = WorkflowRunRepository(db)
    run = await run_repo.get_by_id(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run {run_id} not found"
        )

    # Verify workspace access
    workspace = await require_workspace_access(
        workspace_id=run.workspace_id,
        current_user=current_user,
        db=db
    )

    return run


async def verify_review_workspace_access(
    review_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to review via workspace ownership.

    Review → WorkflowRun → Workspace → owner verification
    """
    from backend.repositories.review import ReviewRepository

    review_repo = ReviewRepository(db)
    review = await review_repo.get_by_id(review_id)

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found"
        )

    # Verify workspace access via run
    run = await verify_run_workspace_access(
        run_id=review.workflow_run_id,
        current_user=current_user,
        db=db
    )

    return review


async def verify_claim_workspace_access(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to claim via workspace ownership.

    Claim → Review → WorkflowRun → Workspace → owner verification
    """
    from backend.repositories.review import ClaimRepository

    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)

    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found"
        )

    # Verify workspace access via review
    if claim.review_id:
        review = await verify_review_workspace_access(
            review_id=claim.review_id,
            current_user=current_user,
            db=db
        )
    else:
        # If no review_id, try workflow_run_id directly
        if hasattr(claim, 'workflow_run_id') and claim.workflow_run_id:
            run = await verify_run_workspace_access(
                run_id=claim.workflow_run_id,
                current_user=current_user,
                db=db
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cannot verify claim ownership: no review_id or workflow_run_id"
            )

    return claim


async def verify_evidence_workspace_access(
    evidence_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to evidence via workspace ownership.

    Evidence → Run → Workspace → owner verification
    """
    from backend.repositories.evidence import EvidenceRepository

    evidence_repo = EvidenceRepository(db)
    evidence = await evidence_repo.get_by_id(evidence_id)

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evidence {evidence_id} not found"
        )

    # Verify run access (which verifies workspace)
    run = await verify_run_workspace_access(
        run_id=evidence.workflow_run_id,
        current_user=current_user,
        db=db
    )

    return evidence


async def verify_export_workspace_access(
    export_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to export via workspace ownership.

    Export → Review → Run → Workspace → owner verification
    """
    from backend.repositories.export import ExportRepository

    export_repo = ExportRepository(db)
    export = await export_repo.get_by_id(export_id)

    if not export:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export {export_id} not found"
        )

    if export.review_id:
        # Standard path: verify via review → workspace
        await verify_review_workspace_access(
            review_id=export.review_id,
            current_user=current_user,
            db=db
        )
    elif export.workflow_run_id:
        # Tariff exports have no review_id — verify via run → workspace
        await verify_run_workspace_access(
            run_id=export.workflow_run_id,
            current_user=current_user,
            db=db
        )
    else:
        # Verify directly via workspace_id on the export record
        await require_workspace_access(
            workspace_id=export.workspace_id,
            current_user=current_user,
            db=db
        )

    return export


async def verify_knowledge_workspace_access(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to knowledge entry via workspace ownership.

    KnowledgeEntry → Workspace → owner verification
    """
    from backend.repositories.knowledge import KnowledgeRepository

    knowledge_repo = KnowledgeRepository(db)
    entry = await knowledge_repo.get_by_id(entry_id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge entry {entry_id} not found"
        )

    # Verify workspace access
    workspace = await require_workspace_access(
        workspace_id=UUID(entry.workspace_id),
        current_user=current_user,
        db=db
    )

    return entry


async def verify_formatting_item_workspace_access(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user has access to formatting item via workspace ownership.

    FormattingItem → Run → Workspace → owner verification
    """
    from backend.repositories.screenplay import FormattingItemRepository

    item_repo = FormattingItemRepository(db)
    item = await item_repo.get_by_id(item_id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Formatting item {item_id} not found"
        )

    # Verify run access (which verifies workspace)
    run = await verify_run_workspace_access(
        run_id=item.workflow_run_id,
        current_user=current_user,
        db=db
    )

    return item
