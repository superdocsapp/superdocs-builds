# backend/tests/unit/test_stream_token_security.py
"""
Unit tests for stream token security.

Verifies:
- Stream token creation and validation
- Token type/audience separation
- Token confusion attacks prevention
- Run ID scope enforcement
"""
import pytest
from datetime import timedelta
from uuid import uuid4, UUID
from jose import jwt, JWTError

from backend.core.auth.security import (
    create_access_token,
    create_refresh_token,
    create_stream_token,
    decode_token,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_STREAM,
    TOKEN_AUD_API,
    TOKEN_AUD_REFRESH,
    TOKEN_AUD_STREAM
)
from backend.config import settings


class TestStreamTokenCreation:
    """Test stream token generation"""

    def test_create_stream_token_includes_all_claims(self):
        """Stream token should include sub, run_id, type, aud, exp"""
        user_id = uuid4()
        run_id = uuid4()
        expires = timedelta(seconds=60)

        token = create_stream_token(user_id, run_id, expires)
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm], options={"verify_aud": False})

        assert payload["sub"] == str(user_id)
        assert payload["run_id"] == str(run_id)
        assert payload["type"] == TOKEN_TYPE_STREAM
        assert payload["aud"] == TOKEN_AUD_STREAM
        assert "exp" in payload

    def test_stream_token_expiry_set_correctly(self):
        """Stream token expiry should be set to specified duration"""
        user_id = uuid4()
        run_id = uuid4()
        expires = timedelta(seconds=60)

        token = create_stream_token(user_id, run_id, expires)
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm], options={"verify_aud": False})

        # Expiry should be ~60 seconds from now (allow 5 second tolerance)
        from datetime import datetime, timezone
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (exp_time - now).total_seconds()

        assert 55 <= delta <= 65


class TestTokenTypeValidation:
    """Test strict token type validation"""

    def test_decode_access_token_with_expected_type(self):
        """Access token should decode successfully with correct type"""
        data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(data, timedelta(minutes=15))

        payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)

        assert payload["sub"] == data["sub"]
        assert payload["type"] == TOKEN_TYPE_ACCESS

    def test_decode_refresh_token_with_expected_type(self):
        """Refresh token should decode successfully with correct type"""
        data = {"sub": str(uuid4())}
        token = create_refresh_token(data, timedelta(days=7))

        payload = decode_token(token, expected_type=TOKEN_TYPE_REFRESH)

        assert payload["sub"] == data["sub"]
        assert payload["type"] == TOKEN_TYPE_REFRESH

    def test_decode_stream_token_with_expected_type(self):
        """Stream token should decode successfully with correct type"""
        user_id = uuid4()
        run_id = uuid4()
        token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        payload = decode_token(token, expected_type=TOKEN_TYPE_STREAM)

        assert payload["sub"] == str(user_id)
        assert payload["run_id"] == str(run_id)
        assert payload["type"] == TOKEN_TYPE_STREAM

    def test_access_token_rejected_when_refresh_expected(self):
        """Access token should be rejected when refresh token expected"""
        data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(data, timedelta(minutes=15))

        with pytest.raises(ValueError, match="Invalid token type"):
            decode_token(token, expected_type=TOKEN_TYPE_REFRESH)

    def test_refresh_token_rejected_when_access_expected(self):
        """Refresh token should be rejected when access token expected"""
        data = {"sub": str(uuid4())}
        token = create_refresh_token(data, timedelta(days=7))

        with pytest.raises(ValueError, match="Invalid token type"):
            decode_token(token, expected_type=TOKEN_TYPE_ACCESS)

    def test_stream_token_rejected_when_access_expected(self):
        """Stream token should be rejected when access token expected"""
        user_id = uuid4()
        run_id = uuid4()
        token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        with pytest.raises(ValueError, match="Invalid token type"):
            decode_token(token, expected_type=TOKEN_TYPE_ACCESS)

    def test_access_token_rejected_when_stream_expected(self):
        """Access token should be rejected when stream token expected"""
        data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(data, timedelta(minutes=15))

        with pytest.raises(ValueError, match="Invalid token type"):
            decode_token(token, expected_type=TOKEN_TYPE_STREAM)


class TestTokenAudienceValidation:
    """Test strict audience validation"""

    def test_decode_with_correct_audience(self):
        """Token should decode successfully with correct audience"""
        data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(data, timedelta(minutes=15))

        payload = decode_token(token, expected_audience=TOKEN_AUD_API)

        assert payload["aud"] == TOKEN_AUD_API

    def test_token_rejected_with_wrong_audience(self):
        """Token should be rejected when audience doesn't match"""
        data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}
        token = create_access_token(data, timedelta(minutes=15))

        with pytest.raises(ValueError, match="Invalid token audience"):
            decode_token(token, expected_audience=TOKEN_AUD_REFRESH)

    def test_stream_token_has_correct_audience(self):
        """Stream token should have workflow-stream audience"""
        user_id = uuid4()
        run_id = uuid4()
        token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        payload = decode_token(token, expected_audience=TOKEN_AUD_STREAM)

        assert payload["aud"] == TOKEN_AUD_STREAM

    def test_stream_token_rejected_for_api_audience(self):
        """Stream token should be rejected when API audience expected"""
        user_id = uuid4()
        run_id = uuid4()
        token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        with pytest.raises(ValueError, match="Invalid token audience"):
            decode_token(token, expected_audience=TOKEN_AUD_API)


class TestTokenConfusionPrevention:
    """Test that token confusion attacks are prevented"""

    def test_combined_type_and_audience_validation(self):
        """Both type and audience must match for successful decode"""
        user_id = uuid4()
        run_id = uuid4()
        token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        # Should succeed with correct type and audience
        payload = decode_token(
            token,
            expected_type=TOKEN_TYPE_STREAM,
            expected_audience=TOKEN_AUD_STREAM
        )
        assert payload["type"] == TOKEN_TYPE_STREAM
        assert payload["aud"] == TOKEN_AUD_STREAM

        # Should fail with wrong type even if audience not checked
        with pytest.raises(ValueError, match="Invalid token type"):
            decode_token(token, expected_type=TOKEN_TYPE_ACCESS)

        # Should fail with wrong audience even if type not checked
        with pytest.raises(ValueError, match="Invalid token audience"):
            decode_token(token, expected_audience=TOKEN_AUD_API)

    def test_no_token_type_can_substitute_for_another(self):
        """Each token type should be rejected when another type is expected"""
        user_id = uuid4()
        run_id = uuid4()

        access_token = create_access_token(
            {"sub": str(user_id), "email": "test@example.com", "role": "user"},
            timedelta(minutes=15)
        )
        refresh_token = create_refresh_token(
            {"sub": str(user_id)},
            timedelta(days=7)
        )
        stream_token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        # Access token cannot be used as refresh or stream
        with pytest.raises(ValueError):
            decode_token(access_token, expected_type=TOKEN_TYPE_REFRESH)
        with pytest.raises(ValueError):
            decode_token(access_token, expected_type=TOKEN_TYPE_STREAM)

        # Refresh token cannot be used as access or stream
        with pytest.raises(ValueError):
            decode_token(refresh_token, expected_type=TOKEN_TYPE_ACCESS)
        with pytest.raises(ValueError):
            decode_token(refresh_token, expected_type=TOKEN_TYPE_STREAM)

        # Stream token cannot be used as access or refresh
        with pytest.raises(ValueError):
            decode_token(stream_token, expected_type=TOKEN_TYPE_ACCESS)
        with pytest.raises(ValueError):
            decode_token(stream_token, expected_type=TOKEN_TYPE_REFRESH)


class TestStreamTokenRunScope:
    """Test that stream tokens are properly scoped to specific runs"""

    def test_stream_token_contains_run_id(self):
        """Stream token must include run_id claim"""
        user_id = uuid4()
        run_id = uuid4()
        token = create_stream_token(user_id, run_id, timedelta(seconds=60))

        payload = decode_token(token)

        assert "run_id" in payload
        assert UUID(payload["run_id"]) == run_id

    def test_different_runs_get_different_tokens(self):
        """Tokens for different runs should have different run_id claims"""
        user_id = uuid4()
        run_id_1 = uuid4()
        run_id_2 = uuid4()

        token_1 = create_stream_token(user_id, run_id_1, timedelta(seconds=60))
        token_2 = create_stream_token(user_id, run_id_2, timedelta(seconds=60))

        payload_1 = decode_token(token_1)
        payload_2 = decode_token(token_2)

        assert payload_1["run_id"] != payload_2["run_id"]
        assert UUID(payload_1["run_id"]) == run_id_1
        assert UUID(payload_2["run_id"]) == run_id_2


class TestExpiredTokens:
    """Test expired token handling"""

    def test_expired_stream_token_rejected(self):
        """Expired stream token should be rejected"""
        user_id = uuid4()
        run_id = uuid4()

        # Create token with negative expiry (already expired)
        token = create_stream_token(user_id, run_id, timedelta(seconds=-10))

        with pytest.raises(JWTError):
            decode_token(token)

    def test_expired_access_token_rejected(self):
        """Expired access token should be rejected"""
        data = {"sub": str(uuid4()), "email": "test@example.com", "role": "user"}

        # Create token with negative expiry (already expired)
        token = create_access_token(data, timedelta(seconds=-10))

        with pytest.raises(JWTError):
            decode_token(token)
