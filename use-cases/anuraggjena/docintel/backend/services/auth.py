# backend/services/auth.py
"""
Authentication service for user registration, login, and token management.
"""
from typing import Optional, Tuple
from datetime import timedelta, datetime, timezone
from uuid import UUID

from jose import JWTError

from backend.repositories.user import UserRepository
from backend.repositories.refresh_token import RefreshTokenRepository
from backend.models.user import User
from backend.core.auth.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token
)


class AuthService:
    """Service for authentication operations"""

    def __init__(
        self,
        user_repo: UserRepository,
        refresh_token_repo: RefreshTokenRepository
    ):
        self.user_repo = user_repo
        self.refresh_token_repo = refresh_token_repo

    async def register_user(
        self,
        email: str,
        password: str,
        name: str,
        role: str = "user"
    ) -> User:
        """
        Register a new user.

        Args:
            email: User email
            password: Plaintext password
            name: User display name
            role: User role (default: user)

        Returns:
            Created User instance

        Raises:
            ValueError: If email already registered
        """
        # Check if user exists
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise ValueError("Email already registered")

        # Hash password
        password_hash = get_password_hash(password)

        # Create user
        user = await self.user_repo.create(
            email=email,
            password_hash=password_hash,
            name=name,
            role=role
        )

        return user

    async def authenticate_user(
        self,
        email: str,
        password: str
    ) -> Optional[User]:
        """
        Authenticate user with email and password.

        Args:
            email: User email
            password: Plaintext password

        Returns:
            User instance if authentication successful, None otherwise
        """
        user = await self.user_repo.get_by_email(email)

        if not user:
            return None

        if not user.is_active:
            return None

        if not verify_password(password, user.password_hash):
            return None

        return user

    async def create_tokens(self, user: User) -> Tuple[str, str]:
        """
        Create access and refresh tokens for user.

        Args:
            user: User instance

        Returns:
            Tuple of (access_token, refresh_token)
        """
        # Create access token (15 minutes)
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role},
            expires_delta=timedelta(minutes=15)
        )

        # Create refresh token (7 days)
        refresh_token = create_refresh_token(
            data={"sub": str(user.id)},
            expires_delta=timedelta(days=7)
        )

        # Store refresh token in database
        await self.refresh_token_repo.create(
            user_id=user.id,
            token_hash=refresh_token,  # Store the actual token for validation
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )

        return access_token, refresh_token

    async def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token string

        Returns:
            New access token or None if refresh token invalid
        """
        try:
            # Decode refresh token
            payload = decode_token(refresh_token)

            if payload.get("type") != "refresh":
                return None

            user_id = UUID(payload.get("sub"))

            # Get user
            user = await self.user_repo.get_by_id(user_id)
            if not user or not user.is_active:
                return None

            # Verify refresh token exists and is not revoked
            stored_token = await self.refresh_token_repo.get_by_token_hash(refresh_token)
            if not stored_token or stored_token.is_revoked:
                return None

            # Check expiration
            # SQLite doesn't preserve timezone info, so we need to ensure comparison
            # works with both naive and timezone-aware datetimes
            expires_at = stored_token.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at < datetime.now(timezone.utc):
                return None

            # Create new access token
            access_token = create_access_token(
                data={"sub": str(user.id), "email": user.email, "role": user.role},
                expires_delta=timedelta(minutes=15)
            )

            return access_token

        except JWTError:
            return None

    async def revoke_refresh_token(self, refresh_token: str) -> None:
        """
        Revoke a refresh token.

        Args:
            refresh_token: Refresh token string
        """
        stored_token = await self.refresh_token_repo.get_by_token_hash(refresh_token)
        if stored_token:
            await self.refresh_token_repo.revoke(stored_token.id)
