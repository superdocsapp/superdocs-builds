"""The wiring that selects a real backend, and the interlocks that keep it off in tests.

None of these touch the network. They cover the decisions made *before* a call goes out:
which database driver, which storage backend, which identity provider - plus the two
safety properties that matter most once real credentials exist in `.env`:

  * the test suite can never be pointed at the production database or bucket
  * a demo session can never be minted while Clerk is configured
"""

import base64

import pytest

from backend.app.core import security
from backend.app.core.config import Settings, settings
from backend.app.services import storage


def _pk(domain: str) -> str:
    payload = base64.b64encode(f"{domain}$".encode()).decode().rstrip("=")
    return f"pk_test_{payload}"


def _settings(**overrides) -> Settings:
    """A Settings built only from its arguments.

    `_env_file=None` is load-bearing: without it pydantic still reads the developer's
    real .env, so a machine with NEON_DATABASE_URL set would see these assertions pass
    or fail depending on local configuration rather than on the code under test.
    """
    return Settings(_env_file=None, **overrides)


# --------------------------------------------------------------------------------------
# Database selection
# --------------------------------------------------------------------------------------


def test_sqlite_url_is_not_postgres():
    assert _settings(database_url="sqlite:///./var/close_pack.db").is_postgres is False


@pytest.mark.parametrize("url", ["postgresql://u:p@host/db", "postgres://u:p@host/db"])
def test_postgres_urls_are_detected(url):
    assert _settings(database_url=url).is_postgres is True


def test_neon_url_overrides_database_url():
    """One env var switches backends; DATABASE_URL can stay at its sqlite default."""
    config = _settings(
        database_url="sqlite:///./var/close_pack.db",
        neon_database_url="postgresql://u:p@neon/db",
    )
    assert config.is_postgres is True
    assert config.resolved_database_url == "postgresql://u:p@neon/db"


def test_blank_database_url_falls_back_to_sqlite_default():
    config = _settings(database_url="", neon_database_url="")
    assert config.is_postgres is False
    assert config.resolved_database_url.startswith("sqlite:")


def test_sqlite_path_refuses_to_answer_for_a_postgres_url():
    """Reading a filesystem path out of a postgres URL would silently create a stray db."""
    with pytest.raises(RuntimeError, match="is_postgres"):
        _ = _settings(neon_database_url="postgresql://u:p@neon/db").sqlite_path


# --------------------------------------------------------------------------------------
# Clerk configuration
# --------------------------------------------------------------------------------------


def test_clerk_domain_is_decoded_from_the_publishable_key():
    config = _settings(clerk_secret_key="sk_test_x", clerk_publishable_key=_pk("bright-cat-42.clerk.accounts.dev"))
    assert config.clerk_domain == "bright-cat-42.clerk.accounts.dev"
    assert config.clerk_issuer == "https://bright-cat-42.clerk.accounts.dev"
    assert config.clerk_jwks_url.endswith("/.well-known/jwks.json")


def test_frontend_publishable_key_is_accepted_too():
    """.env only carries the VITE_-prefixed copy, which the backend cannot see by name."""
    config = _settings(clerk_secret_key="sk_test_x", vite_clerk_publishable_key=_pk("a-b-1.clerk.accounts.dev"))
    assert config.clerk_domain == "a-b-1.clerk.accounts.dev"


def test_clerk_is_disabled_without_a_secret_key():
    assert _settings(clerk_publishable_key=_pk("a-b-1.clerk.accounts.dev")).clerk_enabled is False


def test_clerk_is_disabled_when_the_publishable_key_is_unusable():
    assert _settings(clerk_secret_key="sk_test_x", clerk_publishable_key="not-a-key").clerk_enabled is False


@pytest.mark.parametrize("domain", ["evil.com/path", "evil com"])
def test_a_malformed_key_cannot_redirect_jwks_to_another_host(domain):
    """The JWKS host comes from the key, so a junk key must disable Clerk, not repoint it."""
    config = _settings(clerk_secret_key="sk_test_x", clerk_publishable_key=_pk(domain))
    assert config.clerk_domain == ""
    assert config.clerk_enabled is False


# --------------------------------------------------------------------------------------
# The interlocks
# --------------------------------------------------------------------------------------


def test_demo_session_is_refused_once_clerk_is_configured(client, monkeypatch):
    """An endpoint that mints a session with no credentials is a full auth bypass."""
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "clerk_publishable_key", _pk("a-b-1.clerk.accounts.dev"))
    response = client.post("/api/v1/auth/demo-session")
    assert response.status_code == 403
    assert "Clerk" in response.json()["detail"]


def test_a_local_hmac_token_is_rejected_while_clerk_is_live(monkeypatch):
    """Otherwise the demo identity stays usable as a permanent bypass of real auth."""
    token = security.issue_session({"id": "u1", "name": "Demo", "role": "Controller"})["token"]
    assert security.get_current_user(f"Bearer {token}").name == "Demo"

    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "clerk_publishable_key", _pk("a-b-1.clerk.accounts.dev"))
    security.reset_clerk_cache_for_tests()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        security.get_current_user(f"Bearer {token}")
    assert raised.value.status_code == 401


def test_tests_never_run_against_the_configured_production_database():
    """conftest blanks NEON_DATABASE_URL; reset_for_tests would otherwise DELETE it."""
    assert settings.is_postgres is False
    assert settings.neon_database_url == ""
    assert settings.resolved_database_url.startswith("sqlite:")


def test_tests_never_write_to_the_configured_bucket():
    assert settings.s3_enabled is False


# --------------------------------------------------------------------------------------
# Storage backend selection
# --------------------------------------------------------------------------------------


def test_local_storage_round_trips_without_s3():
    receipt = storage.put_bytes("closes/x/documents/a.txt", b"evidence")
    assert receipt["size"] == 8
    assert storage.get_bytes("closes/x/documents/a.txt") == b"evidence"
    assert storage.exists("closes/x/documents/a.txt")


def test_local_storage_refuses_keys_that_escape_the_root():
    with pytest.raises(ValueError, match="outside storage root"):
        storage.put_bytes("../../etc/passwd", b"nope")


def test_path_for_is_refused_on_object_storage(monkeypatch):
    """A local filesystem path has no meaning against a bucket; callers must use bytes."""
    monkeypatch.setattr(settings, "s3_endpoint_url", "https://gateway.example.com")
    monkeypatch.setattr(settings, "s3_access_key_id", "key")
    monkeypatch.setattr(settings, "s3_bucket_name", "bucket")
    assert settings.s3_enabled is True
    with pytest.raises(RuntimeError, match="no meaning on object storage"):
        storage.path_for("closes/x/documents/a.txt")


def test_s3_is_disabled_unless_endpoint_key_and_bucket_are_all_present(monkeypatch):
    monkeypatch.setattr(settings, "s3_endpoint_url", "https://gateway.example.com")
    monkeypatch.setattr(settings, "s3_access_key_id", "key")
    monkeypatch.setattr(settings, "s3_bucket_name", "")
    assert settings.s3_enabled is False
