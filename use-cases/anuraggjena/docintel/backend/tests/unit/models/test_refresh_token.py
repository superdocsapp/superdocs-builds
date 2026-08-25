# tests/unit/models/test_refresh_token.py
import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from backend.models.refresh_token import RefreshToken


def test_refresh_token_model_creation():
    """Test RefreshToken model can be instantiated"""
    user_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    token = RefreshToken(
        id=uuid4(),
        user_id=user_id,
        token_hash="hashed_token",
        expires_at=expires_at,
        is_revoked=False
    )

    assert token.user_id == user_id
    assert token.token_hash == "hashed_token"
    assert token.expires_at == expires_at
    assert token.is_revoked is False


def test_refresh_token_default_not_revoked():
    """Test RefreshToken is not revoked by default"""
    token = RefreshToken(
        user_id=uuid4(),
        token_hash="hash",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )

    assert token.is_revoked is False
