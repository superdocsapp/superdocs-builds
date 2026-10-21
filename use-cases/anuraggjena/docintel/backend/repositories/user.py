# backend/repositories/user.py
"""
Repository for User model CRUD operations.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User


class UserRepository:
    """Repository for User database operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        email: str,
        password_hash: str,
        name: str,
        role: str = "user",
        is_active: bool = True,
        force_password_change: bool = False
    ) -> User:
        """
        Create a new user.

        Args:
            email: User email (unique)
            password_hash: Bcrypt hashed password
            name: User display name
            role: User role (user, reviewer, admin)
            is_active: Account enabled status
            force_password_change: Force password change on next login

        Returns:
            Created User instance
        """
        user = User(
            email=email,
            password_hash=password_hash,
            name=name,
            role=role,
            is_active=is_active,
            force_password_change=force_password_change
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User UUID

        Returns:
            User instance or None if not found
        """
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email.

        Args:
            email: User email

        Returns:
            User instance or None if not found
        """
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        user_id: UUID,
        **kwargs
    ) -> Optional[User]:
        """
        Update user fields.

        Args:
            user_id: User UUID
            **kwargs: Fields to update

        Returns:
            Updated User instance or None if not found
        """
        user = await self.get_by_id(user_id)
        if not user:
            return None

        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)

        await self.session.commit()
        await self.session.refresh(user)
        return user
