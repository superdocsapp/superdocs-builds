import time

import pytest

from app.mcp.oauth import CODE_TTL_SECONDS, REFRESH_TOKEN_TTL_SECONDS, OAuthServer, compute_code_challenge


def test_full_authorize_then_exchange_flow_succeeds():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    token = server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    assert server.verify(token) is True


def test_unknown_client_cannot_authorize():
    server = OAuthServer()
    with pytest.raises(PermissionError):
        server.authorize("not-a-real-client")


def test_wrong_client_secret_rejected_at_exchange():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    with pytest.raises(PermissionError):
        server.exchange_code_for_token(code, "demo-agent-client", "wrong-secret")


def test_code_cannot_be_used_twice():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    with pytest.raises(PermissionError):
        server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")


def test_expired_code_rejected():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    server._codes[code].issued_at -= (CODE_TTL_SECONDS + 1)
    with pytest.raises(PermissionError):
        server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")


def test_verify_rejects_missing_or_unknown_token():
    server = OAuthServer()
    assert server.verify(None) is False
    assert server.verify("totally-made-up-token") is False


# --- PKCE ---------------------------------------------------------------


def test_pkce_flow_succeeds_with_matching_verifier():
    server = OAuthServer()
    verifier = "a-secret-verifier-only-the-client-knows-1234567890"
    challenge = compute_code_challenge(verifier)
    code = server.authorize("demo-agent-client", code_challenge=challenge)
    token = server.exchange_code_for_token(
        code, "demo-agent-client", "demo-agent-secret", code_verifier=verifier
    )
    assert server.verify(token) is True


def test_pkce_flow_rejects_missing_verifier():
    server = OAuthServer()
    challenge = compute_code_challenge("correct-verifier")
    code = server.authorize("demo-agent-client", code_challenge=challenge)
    with pytest.raises(PermissionError):
        server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")


def test_pkce_flow_rejects_wrong_verifier():
    server = OAuthServer()
    challenge = compute_code_challenge("correct-verifier")
    code = server.authorize("demo-agent-client", code_challenge=challenge)
    with pytest.raises(PermissionError):
        server.exchange_code_for_token(
            code, "demo-agent-client", "demo-agent-secret", code_verifier="wrong-verifier"
        )


def test_no_pkce_still_works_when_no_challenge_was_supplied():
    """Backward compatible: a code issued without a code_challenge
    (e.g. server.py's internal demo flow) can still be exchanged with
    no verifier at all."""
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    token = server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    assert server.verify(token) is True


# --- state (CSRF) ---------------------------------------------------------


def test_state_round_trips_through_authorize_and_exchange():
    server = OAuthServer()
    code = server.authorize("demo-agent-client", state="caller-chosen-nonce")
    server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    assert server.last_state() == "caller-chosen-nonce"


# --- refresh tokens ---------------------------------------------------------


def test_exchange_mints_a_usable_refresh_token():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    refresh_token = server.last_refresh_token()
    assert refresh_token is not None

    new_access = server.refresh(refresh_token, "demo-agent-client", "demo-agent-secret")
    assert server.verify(new_access) is True


def test_refresh_token_is_single_use_and_reuse_revokes_everything():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    original_access = server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    refresh_token = server.last_refresh_token()

    new_access = server.refresh(refresh_token, "demo-agent-client", "demo-agent-secret")
    assert server.verify(new_access) is True
    assert server.verify(original_access) is True  # first access token still valid until its own TTL

    # Reusing the already-rotated refresh token is treated as theft:
    # every token for this client is revoked, including the fresh one.
    with pytest.raises(PermissionError):
        server.refresh(refresh_token, "demo-agent-client", "demo-agent-secret")
    assert server.verify(new_access) is False
    assert server.verify(original_access) is False


def test_refresh_rejects_wrong_client_secret():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    refresh_token = server.last_refresh_token()
    with pytest.raises(PermissionError):
        server.refresh(refresh_token, "demo-agent-client", "wrong-secret")


def test_refresh_rejects_unknown_token():
    server = OAuthServer()
    with pytest.raises(PermissionError):
        server.refresh("not-a-real-refresh-token", "demo-agent-client", "demo-agent-secret")


def test_expired_refresh_token_rejected():
    server = OAuthServer()
    code = server.authorize("demo-agent-client")
    server.exchange_code_for_token(code, "demo-agent-client", "demo-agent-secret")
    refresh_token = server.last_refresh_token()
    server._refresh_tokens[refresh_token].issued_at -= (REFRESH_TOKEN_TTL_SECONDS + 1)
    with pytest.raises(PermissionError):
        server.refresh(refresh_token, "demo-agent-client", "demo-agent-secret")
