# backend/core/auth/security.py
"""
Security utilities for password hashing and JWT token management.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from uuid import UUID

from jose import jwt, JWTError
from passlib.context import CryptContext

from backend.config import settings


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token type and audience constants
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_STREAM = "stream"

TOKEN_AUD_API = "docintel-api"
TOKEN_AUD_REFRESH = "docintel-auth-refresh"
TOKEN_AUD_STREAM = "docintel-workflow-stream"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a hashed password.

    Args:
        plain_password: Plaintext password to verify
        hashed_password: Bcrypt hashed password

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plaintext password

    Returns:
        Bcrypt hashed password
    """
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: timedelta) -> str:
    """
    Create a JWT access token for API access.

    Args:
        data: Payload data (should include sub, email, role)
        expires_delta: Token expiration duration

    Returns:
        Encoded JWT token with type=access, aud=docintel-api
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({
        "exp": expire,
        "type": TOKEN_TYPE_ACCESS,
        "aud": TOKEN_AUD_API
    })
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: Dict[str, Any], expires_delta: timedelta) -> str:
    """
    Create a JWT refresh token for token refresh operations.

    Args:
        data: Payload data (should include sub)
        expires_delta: Token expiration duration

    Returns:
        Encoded JWT token with type=refresh, aud=docintel-auth-refresh
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({
        "exp": expire,
        "type": TOKEN_TYPE_REFRESH,
        "aud": TOKEN_AUD_REFRESH
    })
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_stream_token(user_id: UUID, run_id: UUID, expires_delta: timedelta) -> str:
    """
    Create a short-lived stream token for SSE workflow streaming.

    Stream tokens are scoped to a specific workflow run and cannot be used
    for any other API endpoints. This prevents full-privilege tokens from
    appearing in server logs.

    Args:
        user_id: User ID who owns the workflow run
        run_id: Specific workflow run ID this token grants access to
        expires_delta: Token expiration (recommended: 60 seconds)

    Returns:
        Encoded JWT token with type=stream, aud=docintel-workflow-stream, run_id claim
    """
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": str(user_id),
        "run_id": str(run_id),
        "exp": expire,
        "type": TOKEN_TYPE_STREAM,
        "aud": TOKEN_AUD_STREAM
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(
    token: str,
    expected_type: Optional[str] = None,
    expected_audience: Optional[str] = None
) -> Dict[str, Any]:
    """
    Decode and validate a JWT token with strict type and audience checking.

    Args:
        token: JWT token string
        expected_type: Expected token type (access, refresh, stream). If None, any type accepted.
        expected_audience: Expected audience claim. If None, any audience accepted.

    Returns:
        Decoded payload

    Raises:
        JWTError: If token is invalid, expired, or type/audience don't match
        ValueError: If token type or audience validation fails
    """
    # Decode token (validates signature and expiration)
    # Disable automatic audience validation since we validate manually
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_aud": False}
    )

    # Validate token type if specified
    if expected_type is not None:
        token_type = payload.get("type")
        if token_type != expected_type:
            raise ValueError(
                f"Invalid token type: expected '{expected_type}', got '{token_type}'"
            )

    # Validate audience if specified
    if expected_audience is not None:
        token_aud = payload.get("aud")
        if token_aud != expected_audience:
            raise ValueError(
                f"Invalid token audience: expected '{expected_audience}', got '{token_aud}'"
            )

    return payload
