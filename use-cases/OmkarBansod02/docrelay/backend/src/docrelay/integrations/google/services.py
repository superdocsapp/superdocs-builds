import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docrelay.domain.enums import ConnectionStatus, Provider
from docrelay.integrations.google.contracts import GoogleWriteBackPort
from docrelay.integrations.google.credentials import (
    CredentialEncryptionError,
    EncryptedValue,
    GoogleCredentialSet,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import (
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_WATCH_SCOPES,
    GoogleAuthorizationProfile,
    build_authorization_url,
    new_pkce_verifier,
    scopes_for_profile,
)
from docrelay.integrations.google.read_only import (
    BaselineCaptureResult,
    GoogleBaselineCaptureService,
    GoogleFileMetadata,
    GoogleReadPort,
)
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    GoogleBaselineCapture,
    GoogleOAuthState,
    OAuthCredential,
)

OAUTH_BROWSER_COOKIE = "docrelay_google_oauth_nonce"


@dataclass(frozen=True, slots=True)
class OAuthStartResult:
    authorization_url: str
    browser_nonce: str
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class RegisteredBaseline:
    document: CloudDocument
    capture: GoogleBaselineCapture
    result: BaselineCaptureResult


class GoogleConnectionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        runtime: GoogleRuntime,
        owner_subject: str,
        state_ttl_seconds: int,
        refresh_skew_seconds: int,
        baseline_max_attempts: int,
    ) -> None:
        self._session = session
        self._runtime = runtime
        self._owner_subject = owner_subject
        self._state_ttl_seconds = state_ttl_seconds
        self._refresh_skew_seconds = refresh_skew_seconds
        self._baseline_max_attempts = baseline_max_attempts

    async def start_authorization(
        self,
        profile: GoogleAuthorizationProfile = GoogleAuthorizationProfile.SINGLE_FILE,
    ) -> OAuthStartResult:
        requested_scopes = scopes_for_profile(profile)
        state = secrets.token_urlsafe(32)
        browser_nonce = secrets.token_urlsafe(32)
        state_digest = _sha256(state)
        verifier = new_pkce_verifier()
        encrypted_verifier = self._runtime.cipher.encrypt_json(
            context=f"google-oauth-state:{state_digest}",
            payload={"code_verifier": verifier},
        )
        now = datetime.now(UTC)
        self._session.add(
            GoogleOAuthState(
                owner_subject=self._owner_subject,
                state_sha256=state_digest,
                browser_nonce_sha256=_sha256(browser_nonce),
                code_verifier_ciphertext=encrypted_verifier.ciphertext,
                encryption_key_version=encrypted_verifier.key_version,
                requested_scopes=list(requested_scopes),
                expires_at=now + timedelta(seconds=self._state_ttl_seconds),
            )
        )
        await self._session.commit()
        return OAuthStartResult(
            authorization_url=build_authorization_url(
                client_id=self._runtime.client_id,
                redirect_uri=self._runtime.redirect_uri,
                state=state,
                code_verifier=verifier,
                scopes=requested_scopes,
            ),
            browser_nonce=browser_nonce,
            max_age_seconds=self._state_ttl_seconds,
        )

    async def complete_authorization(
        self,
        *,
        state: str | None,
        browser_nonce: str | None,
        code: str | None,
        oauth_error: str | None,
    ) -> CloudConnection:
        oauth_state = await self._consume_oauth_state(
            state=state,
            browser_nonce=browser_nonce,
        )
        if oauth_error:
            raise GoogleIntegrationError(
                GoogleErrorCode.OAUTH_ACCESS_DENIED,
                "Google authorization was denied or blocked",
            )
        if not code:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_OAUTH_STATE,
                "Google OAuth callback did not contain an authorization code",
            )
        encrypted_verifier = EncryptedValue(
            ciphertext=oauth_state.code_verifier_ciphertext,
            key_version=oauth_state.encryption_key_version,
        )
        try:
            verifier_payload = self._runtime.cipher.decrypt_json(
                context=f"google-oauth-state:{oauth_state.state_sha256}",
                encrypted=encrypted_verifier,
            )
        except CredentialEncryptionError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_OAUTH_STATE,
                "Google OAuth state could not be authenticated",
            ) from exc
        verifier = verifier_payload.get("code_verifier")
        if not isinstance(verifier, str) or not verifier:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_OAUTH_STATE,
                "Google OAuth state did not contain a valid PKCE verifier",
            )

        grant = await self._runtime.oauth.exchange_code(code=code, code_verifier=verifier)
        self._require_scopes(grant.scopes, tuple(oauth_state.requested_scopes))
        principal_subject = await self._runtime.oauth.principal_subject(
            access_token=grant.access_token
        )
        connection = await self._session.scalar(
            select(CloudConnection).where(
                CloudConnection.owner_subject == self._owner_subject,
                CloudConnection.provider == Provider.GOOGLE,
                CloudConnection.provider_account_subject == principal_subject,
            )
        )
        if connection is None:
            connection = CloudConnection(
                owner_subject=self._owner_subject,
                provider=Provider.GOOGLE,
                provider_account_subject=principal_subject,
                status=ConnectionStatus.PENDING,
                granted_scopes={},
            )
            self._session.add(connection)
            await self._session.flush()
        existing_credential = await self._credential_for(connection.id)
        refresh_token = grant.refresh_token
        if refresh_token is None and existing_credential is not None:
            if connection.status is ConnectionStatus.CONNECTED:
                refresh_token = self._decrypt_credential(
                    connection.id, existing_credential
                ).refresh_token
        if refresh_token is None:
            connection.status = ConnectionStatus.REAUTH_REQUIRED
            connection.status_reason = GoogleErrorCode.REAUTH_REQUIRED.value
            await self._session.commit()
            raise GoogleIntegrationError(
                GoogleErrorCode.REAUTH_REQUIRED,
                "Google did not issue offline credentials; reconnect and grant consent",
            )
        credentials = GoogleCredentialSet(
            access_token=grant.access_token,
            refresh_token=refresh_token,
            token_type=grant.token_type,
            scopes=grant.scopes,
            access_token_expires_at=grant.access_token_expires_at,
            refresh_token_expires_at=grant.refresh_token_expires_at,
        )
        credential = await self._store_credentials(
            connection=connection,
            credentials=credentials,
            existing=existing_credential,
            refreshed=False,
        )
        connection.status = ConnectionStatus.CONNECTED
        connection.status_reason = None
        connection.disconnected_at = None
        connection.granted_scopes = {"scopes": list(credentials.scopes)}
        connection.credential_reference = f"oauth_credentials:{credential.id}"
        connection.last_validated_at = datetime.now(UTC)
        await self._session.commit()
        return connection

    async def list_connections(self) -> tuple[CloudConnection, ...]:
        rows = await self._session.scalars(
            select(CloudConnection)
            .where(
                CloudConnection.owner_subject == self._owner_subject,
                CloudConnection.provider == Provider.GOOGLE,
            )
            .order_by(CloudConnection.created_at)
        )
        return tuple(rows)

    async def list_sources(self, connection_id: UUID) -> tuple[CloudDocument, ...]:
        """Registered source documents for one connection, most recent first.

        This is a read-only projection of the canonical `CloudDocument` rows
        that `register_and_capture` already persists for every source DocRelay
        has actually read — manual picks and watch-discovered documents alike.
        Nothing is fetched from Google and no row is created or modified.
        """
        connection = await self._owned_connection(connection_id)
        rows = await self._session.scalars(
            select(CloudDocument)
            .where(CloudDocument.connection_id == connection.id)
            .order_by(
                # `last_seen_at` is written on every capture, so it is the
                # truthful recency key; the null guard keeps the ordering
                # portable if a row ever predates that field.
                CloudDocument.last_seen_at.is_(None),
                CloudDocument.last_seen_at.desc(),
                CloudDocument.updated_at.desc(),
            )
        )
        return tuple(rows)

    async def disconnect(self, connection_id: UUID) -> CloudConnection:
        connection = await self._owned_connection(connection_id)
        credential = await self._credential_for(connection.id)
        if credential is not None:
            credentials = self._decrypt_credential(connection.id, credential)
            await self._session.commit()
            await self._runtime.oauth.revoke(token=credentials.refresh_token)
            connection = await self._owned_connection(connection_id)
            credential = await self._credential_for(connection.id)
            if credential is not None:
                await self._session.delete(credential)
        connection.status = ConnectionStatus.DISCONNECTED
        connection.status_reason = None
        connection.credential_reference = None
        connection.disconnected_at = datetime.now(UTC)
        await self._session.commit()
        return connection

    async def register_and_capture(
        self,
        *,
        connection_id: UUID,
        file_id: str,
        required_scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES,
    ) -> RegisteredBaseline:
        connection = await self._owned_connection(connection_id)
        token = await self._valid_access_token(connection, required_scopes=required_scopes)
        capture_service = GoogleBaselineCaptureService(
            self._runtime.read_client_factory(token),
            max_attempts=self._baseline_max_attempts,
        )
        try:
            result = await capture_service.capture(connection_id=connection.id, file_id=file_id)
        except GoogleIntegrationError as exc:
            if exc.code is not GoogleErrorCode.REAUTH_REQUIRED:
                raise
            token = await self._valid_access_token(
                connection,
                force_refresh=True,
                required_scopes=required_scopes,
            )
            capture_service = GoogleBaselineCaptureService(
                self._runtime.read_client_factory(token),
                max_attempts=self._baseline_max_attempts,
            )
            try:
                result = await capture_service.capture(connection_id=connection.id, file_id=file_id)
            except GoogleIntegrationError as retry_error:
                if retry_error.code is GoogleErrorCode.REAUTH_REQUIRED:
                    await self._mark_reauth_required(connection)
                raise

        document = await self._session.scalar(
            select(CloudDocument).where(
                CloudDocument.connection_id == connection.id,
                CloudDocument.provider_file_id == file_id,
            )
        )
        metadata = result.metadata
        if document is None:
            document = CloudDocument(
                connection_id=connection.id,
                provider_file_id=file_id,
                mime_type=metadata.mime_type,
            )
            self._session.add(document)
            await self._session.flush()
        document.mime_type = metadata.mime_type
        document.display_name = metadata.name
        document.parent_ids = list(metadata.parent_ids)
        document.drive_id = metadata.drive_id
        document.last_seen_revision_id = result.revision_id
        document.last_seen_at = result.captured_at
        document.provider_metadata = {
            "trashed": metadata.trashed,
            "is_app_authorized": metadata.is_app_authorized,
            "capabilities": metadata.capabilities.model_dump(mode="json"),
            "content_restrictions": list(metadata.content_restrictions),
            "download_restrictions": metadata.download_restrictions,
            "copy_requires_writer_permission": metadata.copy_requires_writer_permission,
        }
        baseline = GoogleBaselineCapture(
            cloud_document_id=document.id,
            provider_revision_id=result.revision_id,
            native_raw_sha256=result.native_raw_sha256,
            native_canonical_sha256=result.native_canonical_sha256,
            exported_docx_sha256=result.exported_docx_sha256,
            exported_docx_size_bytes=result.exported_docx_size_bytes,
            canonicalizer_version=result.canonicalizer_version,
            canonical_payload=result.canonical_payload,
            capability_evidence=metadata.capabilities.model_dump(mode="json"),
            parent_ids=list(metadata.parent_ids),
            attempt_count=result.attempt_count,
            capture_started_at=result.capture_started_at,
            captured_at=result.captured_at,
            provider_evidence={
                "protocol": "documents.get(A) -> files.export(DOCX) -> documents.get(A)",
                "revision_before": result.revision_id,
                "revision_after": result.revision_id,
                "mime_type": metadata.mime_type,
                "drive_id": metadata.drive_id,
            },
        )
        self._session.add(baseline)
        await self._session.commit()
        return RegisteredBaseline(document=document, capture=baseline, result=result)

    async def recapture_registered_source(self, source_id: UUID) -> RegisteredBaseline:
        document = await self._session.scalar(
            select(CloudDocument)
            .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
            .where(
                CloudDocument.id == source_id,
                CloudConnection.owner_subject == self._owner_subject,
                CloudConnection.provider == Provider.GOOGLE,
            )
        )
        if document is None:
            raise GoogleIntegrationError(
                GoogleErrorCode.FILE_NOT_FOUND,
                "The registered Google source was not found",
            )
        return await self.register_and_capture(
            connection_id=document.connection_id,
            file_id=document.provider_file_id,
        )

    async def watch_read_client(self, connection_id: UUID) -> GoogleReadPort:
        connection = await self._owned_connection(connection_id)
        token = await self._valid_access_token(
            connection,
            required_scopes=GOOGLE_WATCH_SCOPES,
        )
        return self._runtime.read_client_factory(token)

    async def require_watch_authorization(self, connection_id: UUID) -> None:
        connection = await self._owned_connection(connection_id)
        await self._valid_access_token(
            connection,
            required_scopes=GOOGLE_WATCH_SCOPES,
        )

    async def verify_exact_file_write_authorization(
        self, *, connection_id: UUID, file_id: str
    ) -> GoogleFileMetadata:
        provider = await self.watch_read_client(connection_id)
        metadata = await provider.get_file(file_id)
        if metadata.file_id != file_id:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Drive returned an unexpected file identity",
            )
        return metadata

    async def write_client(self, connection_id: UUID) -> GoogleWriteBackPort:
        connection = await self._owned_connection(connection_id)
        token = await self._valid_access_token(connection)
        factory = self._runtime.write_client_factory
        if factory is None:
            raise GoogleIntegrationError(
                GoogleErrorCode.OAUTH_NOT_CONFIGURED,
                "Google write-back is not configured on this server",
            )
        return factory(token)

    async def _consume_oauth_state(
        self, *, state: str | None, browser_nonce: str | None
    ) -> GoogleOAuthState:
        if not state or not browser_nonce:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_OAUTH_STATE,
                "Google OAuth state is missing or does not match this browser",
            )
        state_digest = _sha256(state)
        oauth_state = await self._session.scalar(
            select(GoogleOAuthState)
            .where(GoogleOAuthState.state_sha256 == state_digest)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            oauth_state is None
            or oauth_state.owner_subject != self._owner_subject
            or oauth_state.consumed_at is not None
            or _as_utc(oauth_state.expires_at) <= now
            or not hmac.compare_digest(
                oauth_state.browser_nonce_sha256,
                _sha256(browser_nonce),
            )
        ):
            await self._session.rollback()
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_OAUTH_STATE,
                "Google OAuth state is expired, already used, or does not match this browser",
            )
        oauth_state.consumed_at = now
        await self._session.commit()
        return oauth_state

    async def _valid_access_token(
        self,
        connection: CloudConnection,
        *,
        force_refresh: bool = False,
        required_scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES,
    ) -> SecretStr:
        if connection.status is not ConnectionStatus.CONNECTED:
            raise GoogleIntegrationError(
                GoogleErrorCode.REAUTH_REQUIRED,
                "The Google connection must be reauthorized",
            )
        credential = await self._credential_for(connection.id)
        if credential is None:
            await self._mark_reauth_required(connection)
            raise GoogleIntegrationError(
                GoogleErrorCode.REAUTH_REQUIRED,
                "The Google connection has no usable credentials",
            )
        credentials = self._decrypt_credential(connection.id, credential)
        self._require_scopes(credentials.scopes, required_scopes)
        refresh_at = datetime.now(UTC) + timedelta(seconds=self._refresh_skew_seconds)
        if not force_refresh and _as_utc(credentials.access_token_expires_at) > refresh_at:
            return credentials.access_token
        await self._session.commit()
        try:
            grant = await self._runtime.oauth.refresh_access_token(
                refresh_token=credentials.refresh_token
            )
        except GoogleIntegrationError as exc:
            if exc.code is GoogleErrorCode.REAUTH_REQUIRED:
                connection = await self._owned_connection(connection.id)
                await self._mark_reauth_required(connection)
            raise
        scopes = grant.scopes or credentials.scopes
        self._require_scopes(scopes, required_scopes)
        refreshed = GoogleCredentialSet(
            access_token=grant.access_token,
            refresh_token=grant.refresh_token or credentials.refresh_token,
            token_type=grant.token_type,
            scopes=scopes,
            access_token_expires_at=grant.access_token_expires_at,
            refresh_token_expires_at=(
                grant.refresh_token_expires_at or credentials.refresh_token_expires_at
            ),
        )
        connection = await self._owned_connection(connection.id)
        credential = await self._credential_for(connection.id)
        await self._store_credentials(
            connection=connection,
            credentials=refreshed,
            existing=credential,
            refreshed=True,
        )
        connection.last_validated_at = datetime.now(UTC)
        connection.granted_scopes = {"scopes": list(refreshed.scopes)}
        await self._session.commit()
        return refreshed.access_token

    async def _store_credentials(
        self,
        *,
        connection: CloudConnection,
        credentials: GoogleCredentialSet,
        existing: OAuthCredential | None,
        refreshed: bool,
    ) -> OAuthCredential:
        encrypted = self._runtime.cipher.encrypt_credentials(connection.id, credentials)
        credential = existing or OAuthCredential(
            connection_id=connection.id,
            encrypted_payload=encrypted.ciphertext,
            encryption_key_version=encrypted.key_version,
            access_token_expires_at=credentials.access_token_expires_at,
        )
        if existing is None:
            self._session.add(credential)
        credential.encrypted_payload = encrypted.ciphertext
        credential.encryption_key_version = encrypted.key_version
        credential.access_token_expires_at = credentials.access_token_expires_at
        credential.refresh_token_expires_at = credentials.refresh_token_expires_at
        if refreshed:
            credential.last_refreshed_at = datetime.now(UTC)
        await self._session.flush()
        return credential

    def _decrypt_credential(
        self, connection_id: UUID, credential: OAuthCredential
    ) -> GoogleCredentialSet:
        try:
            return self._runtime.cipher.decrypt_credentials(
                connection_id,
                EncryptedValue(
                    ciphertext=credential.encrypted_payload,
                    key_version=credential.encryption_key_version,
                ),
            )
        except CredentialEncryptionError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.REAUTH_REQUIRED,
                "Stored Google credentials cannot be decrypted; reconnect the account",
            ) from exc

    async def _mark_reauth_required(self, connection: CloudConnection) -> None:
        credential = await self._credential_for(connection.id)
        if credential is not None:
            await self._session.delete(credential)
        connection.status = ConnectionStatus.REAUTH_REQUIRED
        connection.status_reason = GoogleErrorCode.REAUTH_REQUIRED.value
        connection.credential_reference = None
        await self._session.commit()

    async def _credential_for(self, connection_id: UUID) -> OAuthCredential | None:
        return cast(
            OAuthCredential | None,
            await self._session.scalar(
                select(OAuthCredential).where(OAuthCredential.connection_id == connection_id)
            ),
        )

    async def _owned_connection(self, connection_id: UUID) -> CloudConnection:
        connection = await self._session.scalar(
            select(CloudConnection).where(
                CloudConnection.id == connection_id,
                CloudConnection.owner_subject == self._owner_subject,
                CloudConnection.provider == Provider.GOOGLE,
            )
        )
        if connection is None:
            raise GoogleIntegrationError(
                GoogleErrorCode.CONNECTION_NOT_FOUND,
                "Google connection was not found",
            )
        return connection

    @staticmethod
    def _require_scopes(
        scopes: tuple[str, ...], required_scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES
    ) -> None:
        if not set(required_scopes).issubset(scopes):
            watch_profile = set(GOOGLE_WATCH_SCOPES).issubset(required_scopes)
            raise GoogleIntegrationError(
                (
                    GoogleErrorCode.WATCH_AUTHORIZATION_REQUIRED
                    if watch_profile
                    else GoogleErrorCode.PERMISSION_DENIED
                ),
                (
                    "This Google connection must be explicitly upgraded for folder watch access"
                    if watch_profile
                    else "Google did not grant the required per-file Drive authorization"
                ),
            )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
