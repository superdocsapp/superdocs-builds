"""
Repository for RefreshToken model CRUD operations.
"""
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    """Repository for RefreshToken database operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime
    ) -> RefreshToken:
        """
        Create a new refresh token.

        Args:
            user_id: User UUID
            token_hash: Hashed refresh token
            expires_at: Expiration timestamp

        Returns:
            Created RefreshToken instance
        """
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at
        )
        self.session.add(token)
        await self.session.commit()
        await self.session.refresh(token)
        return token

    async def get_by_token_hash(self, token_hash: str) -> Optional[RefreshToken]:
        """
        Get refresh token by hash.

        Args:
            token_hash: Hashed token

        Returns:
            RefreshToken instance or None if not found
        """
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, token_id: UUID) -> None:
        """
        Revoke a refresh token.

        Args:
            token_id: RefreshToken UUID
        """
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.id == token_id)
        )
        token = result.scalar_one_or_none()

        if token:
            token.is_revoked = True
            await self.session.commit()

    async def delete_expired(self) -> int:
        """
        Delete all expired refresh tokens.

        Returns:
            Number of tokens deleted
        """
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            delete(RefreshToken)
            .where(RefreshToken.expires_at < now)
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()
        return result.rowcount
