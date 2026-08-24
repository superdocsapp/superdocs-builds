from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Cookie, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from docrelay.core.config import Settings
from docrelay.domain.enums import ConnectionStatus
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import (
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_WATCH_SCOPES,
    OAUTH_RETURN_COOKIE,
    GoogleAuthorizationProfile,
    frontend_oauth_redirect_url,
    oauth_return_path_for_profile,
)
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import (
    OAUTH_BROWSER_COOKIE,
    GoogleConnectionService,
    RegisteredBaseline,
)
from docrelay.persistence.database import Database
from docrelay.persistence.models import CloudConnection
from docrelay.services.document_preview import FrozenDocumentPreview, preview_from_canonical

router = APIRouter(prefix="/api/v1/google", tags=["google"])


class SafeAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoogleErrorBody(SafeAPIModel):
    code: GoogleErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class GoogleErrorResponse(SafeAPIModel):
    error: GoogleErrorBody


class GoogleConnectionResponse(SafeAPIModel):
    connection_id: UUID
    provider: Literal["GOOGLE"] = "GOOGLE"
    status: ConnectionStatus
    granted_scopes: tuple[str, ...] = ()
    watch_authorized: bool = False
    last_validated_at: datetime | None = None
    disconnected_at: datetime | None = None


class GoogleConnectionsResponse(SafeAPIModel):
    oauth_configured: bool
    selected_scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES
    watch_scopes: tuple[str, ...] = GOOGLE_WATCH_SCOPES
    connections: tuple[GoogleConnectionResponse, ...]


class RegisterGoogleSourceRequest(SafeAPIModel):
    file_id: str = Field(min_length=1, max_length=255)

    @field_validator("file_id")
    @classmethod
    def validate_file_id(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 33 for character in value):
            raise ValueError("file_id must be a single opaque Google file identifier")
        return value


class GoogleCapabilitiesResponse(SafeAPIModel):
    can_edit: bool
    can_modify_content: bool
    can_download: bool
    can_copy: bool


class GoogleSourceResponse(SafeAPIModel):
    source_id: UUID
    connection_id: UUID
    provider_file_id: str
    name: str
    mime_type: str
    parent_ids: tuple[str, ...]
    drive_id: str | None = None
    trashed: bool
    capabilities: GoogleCapabilitiesResponse


class GoogleBaselineResponse(SafeAPIModel):
    capture_id: UUID
    provider_file_id: str
    revision_id: str
    native_raw_sha256: str
    native_canonical_sha256: str
    docx_sha256: str
    docx_size_bytes: int
    canonicalizer_version: str
    attempt_count: int
    capture_started_at: datetime
    captured_at: datetime
    revision_consistent: Literal[True] = True


class RegisterGoogleSourceResponse(SafeAPIModel):
    source: GoogleSourceResponse
    baseline: GoogleBaselineResponse
    preview: FrozenDocumentPreview


class RegisteredSourceResponse(SafeAPIModel):
    """One canonical source document DocRelay has read for this connection."""

    source_id: UUID
    provider_file_id: str
    name: str
    mime_type: str
    last_seen_at: datetime | None = None


class RegisteredSourcesResponse(SafeAPIModel):
    connection_id: UUID
    sources: tuple[RegisteredSourceResponse, ...]


def _connection_response(connection: CloudConnection) -> GoogleConnectionResponse:
    scopes = connection.granted_scopes.get("scopes", [])
    return GoogleConnectionResponse(
        connection_id=connection.id,
        status=connection.status,
        granted_scopes=tuple(str(scope) for scope in scopes),
        watch_authorized=set(GOOGLE_WATCH_SCOPES).issubset(str(scope) for scope in scopes),
        last_validated_at=connection.last_validated_at,
        disconnected_at=connection.disconnected_at,
    )


def _runtime(request: Request) -> GoogleRuntime:
    runtime: GoogleRuntime | None = request.app.state.google_runtime
    if runtime is None:
        raise GoogleIntegrationError(
            GoogleErrorCode.OAUTH_NOT_CONFIGURED,
            "Google OAuth is not configured on this server",
        )
    return runtime


def _service(
    *, request: Request, session: AsyncSession, runtime: GoogleRuntime
) -> GoogleConnectionService:
    settings: Settings = request.app.state.settings
    return GoogleConnectionService(
        session=session,
        runtime=runtime,
        owner_subject=settings.docrelay_owner_subject,
        state_ttl_seconds=settings.google_oauth_state_ttl_seconds,
        refresh_skew_seconds=settings.google_access_token_refresh_skew_seconds,
        baseline_max_attempts=settings.google_baseline_max_attempts,
    )


@router.get("/connections", response_model=GoogleConnectionsResponse)
async def list_google_connections(request: Request) -> GoogleConnectionsResponse:
    settings: Settings = request.app.state.settings
    if not settings.google_oauth_configured:
        return GoogleConnectionsResponse(oauth_configured=False, connections=())
    runtime = _runtime(request)
    database: Database = request.app.state.database
    async with database.sessions() as session:
        connections = await _service(
            request=request, session=session, runtime=runtime
        ).list_connections()
    return GoogleConnectionsResponse(
        oauth_configured=True,
        connections=tuple(_connection_response(connection) for connection in connections),
    )


@router.get("/oauth/authorize", response_class=RedirectResponse)
async def authorize_google(
    request: Request,
    profile: Annotated[GoogleAuthorizationProfile, Query()] = (
        GoogleAuthorizationProfile.SINGLE_FILE
    ),
) -> RedirectResponse:
    runtime = _runtime(request)
    database: Database = request.app.state.database
    async with database.sessions() as session:
        started = await _service(
            request=request, session=session, runtime=runtime
        ).start_authorization(profile)
    response = RedirectResponse(started.authorization_url, status_code=status.HTTP_302_FOUND)
    settings: Settings = request.app.state.settings
    _set_oauth_browser_cookie(
        response,
        OAUTH_BROWSER_COOKIE,
        started.browser_nonce,
        max_age=started.max_age_seconds,
        settings=settings,
    )
    _set_oauth_browser_cookie(
        response,
        OAUTH_RETURN_COOKIE,
        oauth_return_path_for_profile(profile),
        max_age=started.max_age_seconds,
        settings=settings,
    )
    return response


@router.get(
    "/oauth/callback",
    response_class=RedirectResponse,
    responses={400: {"model": GoogleErrorResponse}, 403: {"model": GoogleErrorResponse}},
)
async def google_oauth_callback(
    request: Request,
    state: Annotated[str | None, Query()] = None,
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    browser_nonce: Annotated[str | None, Cookie(alias=OAUTH_BROWSER_COOKIE)] = None,
) -> RedirectResponse:
    runtime = _runtime(request)
    database: Database = request.app.state.database
    settings: Settings = request.app.state.settings
    async with database.sessions() as session:
        await _service(
            request=request, session=session, runtime=runtime
        ).complete_authorization(
            state=state,
            browser_nonce=browser_nonce,
            code=code,
            oauth_error=error,
        )
    redirect = RedirectResponse(
        frontend_oauth_redirect_url(
            origins=settings.cors_origins,
            path=request.cookies.get(OAUTH_RETURN_COOKIE),
        ),
        status_code=status.HTTP_302_FOUND,
    )
    clear_oauth_callback_cookies(redirect, settings)
    return redirect


@router.post(
    "/connections/{connection_id}/disconnect",
    response_model=GoogleConnectionResponse,
)
async def disconnect_google(connection_id: UUID, request: Request) -> GoogleConnectionResponse:
    runtime = _runtime(request)
    database: Database = request.app.state.database
    async with database.sessions() as session:
        connection = await _service(request=request, session=session, runtime=runtime).disconnect(
            connection_id
        )
    return _connection_response(connection)


@router.get(
    "/connections/{connection_id}/sources",
    response_model=RegisteredSourcesResponse,
)
async def list_google_sources(connection_id: UUID, request: Request) -> RegisteredSourcesResponse:
    """Read-only list of the source documents already registered for a connection.

    Recent needs the authoritative set of documents DocRelay has actually read,
    including one that has been opened but has not produced a run yet. That set
    already exists as `cloud_documents`; this endpoint only projects it.
    """
    runtime = _runtime(request)
    database: Database = request.app.state.database
    async with database.sessions() as session:
        documents = await _service(
            request=request, session=session, runtime=runtime
        ).list_sources(connection_id)
    return RegisteredSourcesResponse(
        connection_id=connection_id,
        sources=tuple(
            RegisteredSourceResponse(
                source_id=document.id,
                provider_file_id=document.provider_file_id,
                name=document.display_name or "Google document",
                mime_type=document.mime_type,
                last_seen_at=document.last_seen_at,
            )
            for document in documents
        ),
    )


@router.post(
    "/connections/{connection_id}/sources",
    response_model=RegisterGoogleSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_google_source(
    connection_id: UUID,
    request: Request,
    payload: Annotated[RegisterGoogleSourceRequest, Body()],
) -> RegisterGoogleSourceResponse:
    runtime = _runtime(request)
    database: Database = request.app.state.database
    async with database.sessions() as session:
        registered = await _service(
            request=request, session=session, runtime=runtime
        ).register_and_capture(connection_id=connection_id, file_id=payload.file_id)
    return _registered_response(connection_id, registered)


def _oauth_cookie_secure(settings: Settings) -> bool:
    return settings.app_env == "production"


def _set_oauth_browser_cookie(
    response: Response,
    name: str,
    value: str,
    *,
    max_age: int,
    settings: Settings,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=_oauth_cookie_secure(settings),
        samesite="lax",
        path="/api/v1/google/oauth/callback",
    )


def clear_oauth_callback_cookies(response: Response, settings: Settings) -> None:
    for name in (OAUTH_BROWSER_COOKIE, OAUTH_RETURN_COOKIE):
        response.delete_cookie(
            name,
            path="/api/v1/google/oauth/callback",
            httponly=True,
            secure=_oauth_cookie_secure(settings),
            samesite="lax",
        )


def _registered_response(
    connection_id: UUID, registered: RegisteredBaseline
) -> RegisterGoogleSourceResponse:
    result = registered.result
    metadata = result.metadata
    return RegisterGoogleSourceResponse(
        source=GoogleSourceResponse(
            source_id=registered.document.id,
            connection_id=connection_id,
            provider_file_id=registered.document.provider_file_id,
            name=metadata.name,
            mime_type=metadata.mime_type,
            parent_ids=metadata.parent_ids,
            drive_id=metadata.drive_id,
            trashed=metadata.trashed,
            capabilities=GoogleCapabilitiesResponse.model_validate(
                metadata.capabilities.model_dump()
            ),
        ),
        baseline=GoogleBaselineResponse(
            capture_id=registered.capture.id,
            provider_file_id=registered.document.provider_file_id,
            revision_id=result.revision_id,
            native_raw_sha256=result.native_raw_sha256,
            native_canonical_sha256=result.native_canonical_sha256,
            docx_sha256=result.exported_docx_sha256,
            docx_size_bytes=result.exported_docx_size_bytes,
            canonicalizer_version=result.canonicalizer_version,
            attempt_count=result.attempt_count,
            capture_started_at=result.capture_started_at,
            captured_at=result.captured_at,
        ),
        preview=preview_from_canonical(
            result.canonical_payload,
            revision_id=result.revision_id,
        ),
    )
