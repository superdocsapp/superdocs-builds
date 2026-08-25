# backend/api/v1/auth.py
"""
Authentication API endpoints: register, login, refresh, logout, /me
"""
from typing import Optional
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, EmailStr, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, get_current_user
from backend.repositories.user import UserRepository
from backend.repositories.refresh_token import RefreshTokenRepository
from backend.services.auth import AuthService
from backend.models.user import User
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


# Request/Response Schemas
class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, max_length=128, description="Password (8-128 characters)")
    name: str = Field(..., min_length=1, max_length=255, description="User display name")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Response for register/login endpoints"""
    user: "UserResponse"
    access_token: str
    token_type: str = "bearer"


class RefreshResponse(BaseModel):
    """Response for refresh endpoint"""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User information (no sensitive data)"""
    id: UUID
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info) -> str:
        """Serialize datetime to ISO format string"""
        return dt.isoformat()


# Cookie configuration
REFRESH_TOKEN_COOKIE_KEY = "refresh_token"
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """Dependency to create AuthService"""
    user_repo = UserRepository(db)
    refresh_token_repo = RefreshTokenRepository(db)
    return AuthService(user_repo, refresh_token_repo)


def set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    """
    Set refresh token as httpOnly cookie.

    Security settings:
    - httponly=True: JavaScript cannot access (XSS protection)
    - secure=settings.secure_cookies: HTTPS only in production, HTTP allowed in dev
    - samesite="lax": CSRF protection
    - path="/api/v1/auth": Restrict to auth endpoints only
    """
    from backend.config import settings
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_KEY,
        value=refresh_token,
        httponly=True,
        secure=settings.secure_cookies,  # True in production, False in local dev
        samesite="lax",
        max_age=REFRESH_TOKEN_MAX_AGE,
        path="/api/v1/auth"
    )


def clear_refresh_token_cookie(response: Response) -> None:
    """Clear refresh token cookie on logout"""
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_KEY,
        path="/api/v1/auth"
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Register a new user.

    Creates a new user account with email/password authentication.
    Returns access token (15min) and sets refresh token cookie (7 days).

    Default role: "user"
    """
    logger.info("api_register_attempt", email=request.email)

    try:
        # Register user
        user = await auth_service.register_user(
            email=request.email,
            password=request.password,
            name=request.name,
            role="user"
        )

        # Create tokens
        access_token, refresh_token = await auth_service.create_tokens(user)

        # Set refresh token cookie
        set_refresh_token_cookie(response, refresh_token)

        logger.info("api_register_success", user_id=str(user.id), email=user.email)

        return AuthResponse(
            user=UserResponse.model_validate(user),
            access_token=access_token,
            token_type="bearer"
        )

    except ValueError as e:
        # Email already registered
        logger.warning("api_register_failed", email=request.email, reason=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Authenticate user and return tokens.

    Validates email/password credentials.
    Returns access token (15min) and sets refresh token cookie (7 days).
    """
    logger.info("api_login_attempt", email=request.email)

    # Authenticate user
    user = await auth_service.authenticate_user(request.email, request.password)

    if not user:
        logger.warning("api_login_failed", email=request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Create tokens
    access_token, refresh_token = await auth_service.create_tokens(user)

    # Set refresh token cookie
    set_refresh_token_cookie(response, refresh_token)

    logger.info("api_login_success", user_id=str(user.id), email=user.email)

    return AuthResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        token_type="bearer"
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh access token using refresh token.

    Reads refresh token from httpOnly cookie.
    Rotates refresh token (revokes old, creates new).
    Returns new access token and sets new refresh token cookie.
    """
    # Get refresh token from cookie
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_KEY)

    if not refresh_token:
        logger.warning("api_refresh_no_cookie")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found"
        )

    # Refresh access token
    new_access_token = await auth_service.refresh_access_token(refresh_token)

    if not new_access_token:
        logger.warning("api_refresh_invalid_token")
        # Clear invalid cookie
        clear_refresh_token_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # Revoke old refresh token
    await auth_service.revoke_refresh_token(refresh_token)

    # Create new refresh token (token rotation)
    # Extract user from new access token to create new refresh token
    from backend.core.auth.security import decode_token
    payload = decode_token(new_access_token)
    user_id = UUID(payload["sub"])

    # Get user using the existing user_repo from auth_service
    user = await auth_service.user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Create new tokens
    new_access_token, new_refresh_token = await auth_service.create_tokens(user)

    # Set new refresh token cookie
    set_refresh_token_cookie(response, new_refresh_token)

    logger.info("api_refresh_success", user_id=str(user_id))

    return RefreshResponse(
        access_token=new_access_token,
        token_type="bearer"
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Logout user.

    Revokes refresh token and clears cookie.
    Access tokens cannot be revoked (stateless JWT), but they expire in 15 minutes.
    """
    # Get refresh token from cookie
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_KEY)

    if refresh_token:
        # Revoke refresh token
        await auth_service.revoke_refresh_token(refresh_token)
        logger.info("api_logout_success")

    # Clear cookie regardless
    clear_refresh_token_cookie(response)

    return None


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current authenticated user information.

    Requires valid access token in Authorization header.
    """
    logger.info("api_get_me", user_id=str(current_user.id))
    return UserResponse.model_validate(current_user)


class StreamTokenRequest(BaseModel):
    """Request for stream token generation"""
    run_id: UUID = Field(..., description="Workflow run ID to grant stream access")


class StreamTokenResponse(BaseModel):
    """Response containing short-lived stream token"""
    stream_token: str = Field(..., description="Short-lived token for SSE streaming (60 seconds)")
    token_type: str = "stream"
    expires_in: int = Field(..., description="Token expiry in seconds")


@router.post("/stream-token", response_model=StreamTokenResponse)
async def create_stream_token(
    request: StreamTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a short-lived stream token for SSE workflow streaming.

    Stream tokens:
    - Expire in 60 seconds
    - Scoped to specific workflow run
    - Cannot be used for any other API endpoints
    - Prevent full-privilege tokens from appearing in server logs

    This endpoint requires authentication with a valid access token.
    The returned stream token can only access SSE for the specified run_id.
    """
    from backend.repositories.workflow import WorkflowRunRepository
    from backend.repositories.workspace import WorkspaceRepository
    from backend.core.auth.security import create_stream_token as create_stream_jwt
    from backend.config import settings
    from datetime import timedelta

    # Verify run exists
    run_repo = WorkflowRunRepository(db)
    run = await run_repo.get_by_id(request.run_id)

    if not run:
        logger.warning(
            "api_stream_token_run_not_found",
            user_id=str(current_user.id),
            run_id=str(request.run_id)
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run {request.run_id} not found"
        )

    # Verify workspace access
    workspace_repo = WorkspaceRepository(db)
    workspace = await workspace_repo.get_by_id(run.workspace_id)

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )

    if workspace.owner_user_id != current_user.id and current_user.role != "admin":
        logger.warning(
            "api_stream_token_forbidden",
            user_id=str(current_user.id),
            run_id=str(request.run_id),
            workspace_id=str(run.workspace_id)
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this workspace"
        )

    # Create stream token
    stream_token = create_stream_jwt(
        user_id=current_user.id,
        run_id=request.run_id,
        expires_delta=timedelta(seconds=settings.stream_token_expire_seconds)
    )

    logger.info(
        "api_stream_token_created",
        user_id=str(current_user.id),
        run_id=str(request.run_id)
    )

    return StreamTokenResponse(
        stream_token=stream_token,
        token_type="stream",
        expires_in=settings.stream_token_expire_seconds
    )
