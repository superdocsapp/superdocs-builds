import time

import pytest

from app.mcp.oauth import CODE_TTL_SECONDS, OAuthServer


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
