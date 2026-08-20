from app import auth


def test_auth_disabled_when_no_audience_accepts_all():
    # Local/dev: no audience configured → every request is accepted.
    assert auth.verify_request(None, audience="") is True
    assert auth.verify_request("Bearer whatever", audience="") is True


def test_auth_enabled_rejects_missing_or_malformed_header():
    assert auth.verify_request(None, audience="123456") is False
    assert auth.verify_request("Token abc", audience="123456") is False


def test_auth_enabled_rejects_when_verification_fails(monkeypatch):
    # A forged/garbage token can't be verified against Google's certs → rejected.
    assert auth.verify_request("Bearer not-a-real-jwt", audience="123456") is False
