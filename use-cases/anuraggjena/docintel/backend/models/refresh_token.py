# backend/models/refresh_token.py
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class RefreshToken(Base, UUIDMixin, TimestampMixin):
    """
    Refresh token for JWT token refresh flow.

    Attributes:
        user_id: FK to users table
        token_hash: Hashed refresh token (for validation and revocation)
        expires_at: Token expiration timestamp
        is_revoked: Token revocation status
    """
    __tablename__ = "refresh_tokens"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False, server_default="false")

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")

    def __init__(self, **kwargs):
        # Apply Python-level defaults for unit testing
        # Column defaults only apply during database INSERT, not object instantiation
        kwargs.setdefault('is_revoked', False)
        super().__init__(**kwargs)
