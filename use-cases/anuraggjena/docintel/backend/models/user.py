# backend/models/user.py
from sqlalchemy import Column, String, Boolean, CheckConstraint
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class User(Base, UUIDMixin, TimestampMixin):
    """
    User model for authentication and authorization.

    Attributes:
        email: Unique email address (login identifier)
        password_hash: Bcrypt password hash (never store plaintext)
        name: User display name
        role: Global role (user, reviewer, admin)
        is_active: Account enabled/disabled
        force_password_change: Set true for migrated/admin-created accounts
    """
    __tablename__ = "users"

    email = Column(String(254), unique=True, nullable=False, index=True)
    password_hash = Column(String(60), nullable=False)  # bcrypt is 60 chars
    name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user", server_default="user")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    force_password_change = Column(Boolean, nullable=False, default=False, server_default="false")

    # Relationships (will be wired when Workspace/RefreshToken get foreign keys)
    # workspaces = relationship("Workspace", back_populates="owner")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'reviewer', 'admin')",
            name="valid_role_check"
        ),
    )

    def __init__(self, **kwargs):
        # Apply Python-level defaults for unit testing
        # Column defaults only apply during database INSERT, not object instantiation
        kwargs.setdefault('role', 'user')
        kwargs.setdefault('is_active', True)
        kwargs.setdefault('force_password_change', False)
        super().__init__(**kwargs)
