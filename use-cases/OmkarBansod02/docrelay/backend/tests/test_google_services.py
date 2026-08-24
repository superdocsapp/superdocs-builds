import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from docrelay.domain.enums import ConnectionStatus
from docrelay.integrations.google.credentials import CredentialCipher
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import (
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_WATCH_SCOPES,
    GoogleAuthorizationProfile,
    OAuthTokenGrant,
)
from docrelay.integrations.google.read_only import (
    GOOGLE_DOC_MIME,
    GoogleFileMetadata,
    GoogleReadCapabilities,
    NativeGoogleDocument,
)
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import GoogleConnectionService
from docrelay.persistence.base import Base
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    GoogleBaselineCapture,
    GoogleOAuthState,
    OAuthCredential,
)


class FakeOAuth:
    def __init__(self, *, initial_expired: bool = False) -> None:
        expiry = datetime.now(UTC) + (
            timedelta(seconds=-1) if initial_expired else timedelta(hours=1)
        )
        self.exchange_grant = OAuthTokenGrant(
            access_token=SecretStr("initial-access-secret"),
            refresh_token=SecretStr("refresh-secret"),
            scopes=GOOGLE_OAUTH_SCOPES,
            access_token_expires_at=expiry,
        )
        self.refresh_grant = OAuthTokenGrant(
            access_token=SecretStr("refreshed-access-secret"),
            refresh_token=None,
            scopes=(),
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.refresh_error: GoogleIntegrationError | None = None
        self.exchange_calls = 0
        self.refresh_calls = 0
        self.revoked: list[str] = []

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthTokenGrant:
        assert code == "authorization-code"
        assert 43 <= len(code_verifier) <= 128
        self.exchange_calls += 1
        return self.exchange_grant

    async def refresh_access_token(self, *, refresh_token: SecretStr) -> OAuthTokenGrant:
        assert refresh_token.get_secret_value() == "refresh-secret"
        self.refresh_calls += 1
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refresh_grant

    async def principal_subject(self, *, access_token: SecretStr) -> str:
        assert access_token.get_secret_value() == "initial-access-secret"
        return "opaque-google-subject-123"

    async def revoke(self, *, token: SecretStr) -> None:
        self.revoked.append(token.get_secret_value())


class StableReadProvider:
    async def get_file(self, file_id: str) -> GoogleFileMetadata:
        return GoogleFileMetadata(
            file_id=file_id,
            name="Synthetic source",
            mime_type=GOOGLE_DOC_MIME,
            parent_ids=("folder-1",),
            is_app_authorized=True,
            capabilities=GoogleReadCapabilities(
                can_edit=True,
                can_modify_content=True,
                can_download=True,
                can_copy=True,
            ),
        )

    async def get_document(self, file_id: str) -> NativeGoogleDocument:
        return NativeGoogleDocument(
            file_id=file_id,
            revision_id="opaque-revision-A",
            raw_payload={
                "documentId": file_id,
                "revisionId": "opaque-revision-A",
                "tabs": [
                    {
                        "tabProperties": {"tabId": "t.0", "title": "Tab 1", "index": 0},
                        "documentTab": {
                            "body": {
                                "content": [
                                    {
                                        "startIndex": 1,
                                        "endIndex": 7,
                                        "paragraph": {
                                            "elements": [
                                                {
                                                    "startIndex": 1,
                                                    "endIndex": 7,
                                                    "textRun": {"content": "hello\n"},
                                                }
                                            ]
                                        },
                                    }
                                ]
                            }
                        },
                    }
                ],
            },
        )

    async def export_docx(self, _: str) -> bytes:
        return b"synthetic-docx-bytes"


@asynccontextmanager
async def _service_environment(
    *, initial_expired: bool = False
) -> AsyncIterator[tuple[AsyncSession, GoogleConnectionService, FakeOAuth, list[str]]]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    fake_oauth = FakeOAuth(initial_expired=initial_expired)
    key = Fernet.generate_key().decode("ascii")
    cipher = CredentialCipher.from_json_keyring(json.dumps({"v1": key}), "v1")
    read_tokens: list[str] = []

    def read_factory(token: SecretStr) -> StableReadProvider:
        read_tokens.append(token.get_secret_value())
        return StableReadProvider()

    runtime = GoogleRuntime(
        oauth=fake_oauth,
        cipher=cipher,
        client_id="client-id",
        redirect_uri="http://localhost:8000/api/v1/google/oauth/callback",
        read_client_factory=read_factory,
    )
    service = GoogleConnectionService(
        session=session,
        runtime=runtime,
        owner_subject="local-owner",
        state_ttl_seconds=600,
        refresh_skew_seconds=60,
        baseline_max_attempts=2,
    )
    try:
        yield session, service, fake_oauth, read_tokens
    finally:
        await session.close()
        await engine.dispose()


async def _authorize(service: GoogleConnectionService) -> CloudConnection:
    started = await service.start_authorization()
    state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
    return await service.complete_authorization(
        state=state,
        browser_nonce=started.browser_nonce,
        code="authorization-code",
        oauth_error=None,
    )


async def test_oauth_state_requires_matching_browser_nonce_and_is_one_time() -> None:
    async with _service_environment() as (session, service, oauth, _):
        started = await service.start_authorization()
        state = parse_qs(urlparse(started.authorization_url).query)["state"][0]

        with pytest.raises(GoogleIntegrationError) as wrong_browser:
            await service.complete_authorization(
                state=state,
                browser_nonce="wrong-browser",
                code="authorization-code",
                oauth_error=None,
            )
        assert wrong_browser.value.code is GoogleErrorCode.INVALID_OAUTH_STATE
        assert oauth.exchange_calls == 0

        connection = await service.complete_authorization(
            state=state,
            browser_nonce=started.browser_nonce,
            code="authorization-code",
            oauth_error=None,
        )
        assert connection.status is ConnectionStatus.CONNECTED

        with pytest.raises(GoogleIntegrationError) as replay:
            await service.complete_authorization(
                state=state,
                browser_nonce=started.browser_nonce,
                code="authorization-code",
                oauth_error=None,
            )
        assert replay.value.code is GoogleErrorCode.INVALID_OAUTH_STATE
        assert oauth.exchange_calls == 1

        stored_state = await session.scalar(select(GoogleOAuthState))
        assert stored_state is not None and stored_state.consumed_at is not None
        assert stored_state.state_sha256 != state
        assert stored_state.browser_nonce_sha256 != started.browser_nonce


async def test_expired_oauth_state_is_rejected_before_code_exchange() -> None:
    async with _service_environment() as (session, service, oauth, _):
        started = await service.start_authorization()
        state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
        stored_state = await session.scalar(select(GoogleOAuthState))
        assert stored_state is not None
        stored_state.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(GoogleIntegrationError) as expired:
            await service.complete_authorization(
                state=state,
                browser_nonce=started.browser_nonce,
                code="authorization-code",
                oauth_error=None,
            )

        assert expired.value.code is GoogleErrorCode.INVALID_OAUTH_STATE
        assert oauth.exchange_calls == 0


async def test_connection_and_credentials_persist_without_plaintext_or_profile_data() -> None:
    async with _service_environment() as (session, service, _, _):
        connection = await _authorize(service)
        credential = await session.scalar(select(OAuthCredential))

        assert connection.provider_account_subject == "opaque-google-subject-123"
        assert connection.display_name is None
        assert credential is not None
        assert "initial-access-secret" not in credential.encrypted_payload
        assert "refresh-secret" not in credential.encrypted_payload
        assert connection.credential_reference == f"oauth_credentials:{credential.id}"


async def test_expired_access_token_refreshes_and_identity_baseline_persists() -> None:
    async with _service_environment(initial_expired=True) as (
        session,
        service,
        oauth,
        read_tokens,
    ):
        connection = await _authorize(service)
        first = await service.register_and_capture(
            connection_id=connection.id, file_id="stable-file-id"
        )
        second = await service.register_and_capture(
            connection_id=connection.id, file_id="stable-file-id"
        )

        assert oauth.refresh_calls == 1
        assert read_tokens == ["refreshed-access-secret", "refreshed-access-secret"]
        assert first.document.id == second.document.id
        assert first.document.provider_file_id == "stable-file-id"
        assert first.result.revision_id == "opaque-revision-A"
        assert first.capture.provider_revision_id == "opaque-revision-A"
        assert first.capture.exported_docx_sha256 == first.result.exported_docx_sha256
        assert await session.scalar(select(func.count()).select_from(CloudDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(GoogleBaselineCapture)) == 2

        credential = await session.scalar(select(OAuthCredential))
        assert credential is not None and credential.last_refreshed_at is not None
        assert "refreshed-access-secret" not in credential.encrypted_payload


async def test_revoked_refresh_marks_reauth_required_and_removes_credentials() -> None:
    async with _service_environment(initial_expired=True) as (session, service, oauth, _):
        connection = await _authorize(service)
        oauth.refresh_error = GoogleIntegrationError(
            GoogleErrorCode.REAUTH_REQUIRED,
            "Google authorization is no longer valid; reconnect the account",
        )

        with pytest.raises(GoogleIntegrationError) as raised:
            await service.register_and_capture(connection_id=connection.id, file_id="file-123")

        assert raised.value.code is GoogleErrorCode.REAUTH_REQUIRED
        await session.refresh(connection)
        assert connection.status is ConnectionStatus.REAUTH_REQUIRED
        assert connection.credential_reference is None
        assert await session.scalar(select(OAuthCredential)) is None


async def test_disconnect_revokes_then_removes_local_credentials() -> None:
    async with _service_environment() as (session, service, oauth, _):
        connection = await _authorize(service)

        disconnected = await service.disconnect(connection.id)

        assert oauth.revoked == ["refresh-secret"]
        assert disconnected.status is ConnectionStatus.DISCONNECTED
        assert disconnected.disconnected_at is not None
        assert disconnected.credential_reference is None
        assert await session.scalar(select(OAuthCredential)) is None


async def test_normal_connection_remains_narrow_and_cannot_silently_enable_watch() -> None:
    async with _service_environment() as (_, service, _, _):
        connection = await _authorize(service)

        with pytest.raises(GoogleIntegrationError) as raised:
            await service.watch_read_client(connection.id)

        assert raised.value.code is GoogleErrorCode.WATCH_AUTHORIZATION_REQUIRED
        assert tuple(connection.granted_scopes["scopes"]) == GOOGLE_OAUTH_SCOPES


async def test_explicit_watch_profile_persists_verified_combined_scope_grant() -> None:
    async with _service_environment() as (_, service, oauth, read_tokens):
        oauth.exchange_grant = oauth.exchange_grant.model_copy(
            update={"scopes": GOOGLE_WATCH_SCOPES}
        )
        started = await service.start_authorization(GoogleAuthorizationProfile.WATCH)
        query = parse_qs(urlparse(started.authorization_url).query)
        state = query["state"][0]

        connection = await service.complete_authorization(
            state=state,
            browser_nonce=started.browser_nonce,
            code="authorization-code",
            oauth_error=None,
        )
        provider = await service.watch_read_client(connection.id)

        assert provider is not None
        assert set(connection.granted_scopes["scopes"]) == set(GOOGLE_WATCH_SCOPES)
        assert query["scope"] == [" ".join(GOOGLE_WATCH_SCOPES)]
        assert read_tokens == ["initial-access-secret"]


async def test_registered_sources_are_listed_without_reading_google_again() -> None:
    async with _service_environment() as (session, service, _, read_tokens):
        connection = await _authorize(service)
        await service.register_and_capture(connection_id=connection.id, file_id="file-a")
        await service.register_and_capture(connection_id=connection.id, file_id="file-b")
        # Re-registering the same file must not create a second source row.
        await service.register_and_capture(connection_id=connection.id, file_id="file-a")
        reads_after_registration = len(read_tokens)

        sources = await service.list_sources(connection.id)

        assert [source.provider_file_id for source in sources] == ["file-a", "file-b"]
        assert all(source.display_name == "Synthetic source" for source in sources)
        assert all(source.last_seen_at is not None for source in sources)
        # Listing is a pure projection: no additional Google read client is built.
        assert len(read_tokens) == reads_after_registration
        assert await session.scalar(select(func.count()).select_from(CloudDocument)) == 2


async def test_listing_sources_for_an_unowned_connection_is_rejected() -> None:
    async with _service_environment() as (_, service, _, _):
        with pytest.raises(GoogleIntegrationError) as raised:
            await service.list_sources(uuid4())
        assert raised.value.code is GoogleErrorCode.CONNECTION_NOT_FOUND
