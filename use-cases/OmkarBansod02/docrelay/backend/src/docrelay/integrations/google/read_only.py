import logging
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from docrelay.integrations.google.canonical import (
    CANONICALIZER_VERSION,
    canonicalize_google_document,
    sha256_bytes,
    sha256_json,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DOCS_API_BASE = "https://docs.googleapis.com/v1"
MAX_GOOGLE_EXPORT_BYTES = 10 * 1024 * 1024
DRIVE_FILE_FIELDS = (
    "id,name,mimeType,parents,driveId,trashed,isAppAuthorized,"
    "version,modifiedTime,spaces,ownedByMe,"
    "copyRequiresWriterPermission,contentRestrictions,downloadRestrictions,"
    "capabilities(canEdit,canModifyContent,canDownload,canCopy)"
)
DRIVE_LIST_FIELDS = f"nextPageToken,incompleteSearch,files({DRIVE_FILE_FIELDS})"

logger = logging.getLogger(__name__)


class GoogleReadContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoogleReadCapabilities(GoogleReadContract):
    can_edit: bool = False
    can_modify_content: bool = False
    can_download: bool = False
    can_copy: bool = False


class GoogleFileMetadata(GoogleReadContract):
    file_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    parent_ids: tuple[str, ...] = ()
    drive_id: str | None = None
    trashed: bool = False
    is_app_authorized: bool | None = None
    provider_version: str | None = None
    modified_time: datetime | None = None
    spaces: tuple[str, ...] = ()
    owned_by_me: bool | None = None
    capabilities: GoogleReadCapabilities
    content_restrictions: tuple[dict[str, Any], ...] = ()
    download_restrictions: dict[str, Any] = Field(default_factory=dict)
    copy_requires_writer_permission: bool = False


class NativeGoogleDocument(GoogleReadContract):
    file_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    raw_payload: dict[str, Any]


class GoogleDrivePage(GoogleReadContract):
    items: tuple[GoogleFileMetadata, ...]
    next_page_token: str | None = None
    incomplete_search: bool = False


class BaselineCaptureResult(GoogleReadContract):
    metadata: GoogleFileMetadata
    revision_id: str = Field(min_length=1)
    native_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exported_docx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exported_docx_size_bytes: int = Field(ge=0)
    canonicalizer_version: str = CANONICALIZER_VERSION
    canonical_payload: dict[str, Any]
    native_raw_payload: dict[str, Any] = Field(exclude=True)
    docx_bytes: bytes = Field(exclude=True)
    attempt_count: int = Field(ge=1)
    capture_started_at: datetime
    captured_at: datetime


class GoogleReadPort(Protocol):
    async def get_file(self, file_id: str) -> GoogleFileMetadata: ...

    async def get_document(self, file_id: str) -> NativeGoogleDocument: ...

    async def export_docx(self, file_id: str) -> bytes: ...

    async def list_children(
        self, folder_id: str, *, page_token: str | None = None
    ) -> GoogleDrivePage: ...


class GoogleReadHTTPClient:
    """Read-only transport: its public provider surface exposes GET operations only."""

    def __init__(self, *, http: httpx.AsyncClient, access_token: SecretStr) -> None:
        self._http = http
        self._access_token = access_token

    async def get_file(self, file_id: str) -> GoogleFileMetadata:
        response = await self._get(
            f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}",
            params={"fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"},
        )
        payload = _json_object(response)
        return _file_metadata(payload)

    async def list_children(
        self, folder_id: str, *, page_token: str | None = None
    ) -> GoogleDrivePage:
        escaped_folder_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        params = {
            "q": f"'{escaped_folder_id}' in parents and trashed = false",
            "spaces": "drive",
            "corpora": "user",
            "pageSize": "1000",
            "fields": DRIVE_LIST_FIELDS,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "false",
        }
        if page_token is not None:
            params["pageToken"] = page_token
        payload = _json_object(await self._get(f"{DRIVE_API_BASE}/files", params=params))
        files = payload.get("files")
        if not isinstance(files, list):
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Drive returned an invalid folder listing",
            )
        token = payload.get("nextPageToken")
        if token is not None and (not isinstance(token, str) or not token):
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Drive returned an invalid pagination cursor",
            )
        try:
            items = tuple(_file_metadata(item) for item in files if isinstance(item, dict))
        except ValueError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Drive returned invalid file metadata",
            ) from exc
        if len(items) != len(files):
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Drive returned an invalid folder listing",
            )
        return GoogleDrivePage(
            items=items,
            next_page_token=token,
            incomplete_search=bool(payload.get("incompleteSearch", False)),
        )

    async def get_document(self, file_id: str) -> NativeGoogleDocument:
        response = await self._get(
            f"{DOCS_API_BASE}/documents/{quote(file_id, safe='')}",
            params={
                "includeTabsContent": "true",
                "suggestionsViewMode": "SUGGESTIONS_INLINE",
            },
        )
        payload = _json_object(response)
        revision_id = payload.get("revisionId")
        if not isinstance(revision_id, str) or not revision_id:
            raise GoogleIntegrationError(
                GoogleErrorCode.PERMISSION_DENIED,
                "Google Docs did not provide the editor-scoped revision required for a baseline",
            )
        returned_id = payload.get("documentId")
        if returned_id != file_id:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Docs returned an unexpected document identity",
            )
        return NativeGoogleDocument(
            file_id=file_id,
            revision_id=revision_id,
            raw_payload=payload,
        )

    async def export_docx(self, file_id: str) -> bytes:
        response = await self._get(
            f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}/export",
            params={"mimeType": DOCX_MIME},
        )
        content = response.content
        if len(content) > MAX_GOOGLE_EXPORT_BYTES:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google DOCX export exceeded the documented 10 MB limit",
            )
        return content

    async def _get(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        try:
            response = await self._http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._access_token.get_secret_value()}"},
            )
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNAVAILABLE,
                "Google API is unavailable",
                retryable=True,
            ) from exc
        if not response.is_success:
            raise _map_google_response(response)
        return response


class GoogleBaselineCaptureService:
    def __init__(self, provider: GoogleReadPort, *, max_attempts: int = 3) -> None:
        self._provider = provider
        self._max_attempts = max_attempts

    async def capture(self, *, connection_id: UUID, file_id: str) -> BaselineCaptureResult:
        capture_started_at = datetime.now(UTC)
        metadata = await self._observe(
            connection_id=connection_id,
            file_id=file_id,
            operation="drive.files.get",
            attempt=0,
            call=lambda: self._provider.get_file(file_id),
        )
        if metadata.file_id != file_id:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google Drive returned an unexpected file identity",
            )
        if metadata.mime_type != GOOGLE_DOC_MIME:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNSUPPORTED_SOURCE_TYPE,
                "DocRelay currently supports only native Google Docs",
                safe_details={"observed_mime_type": metadata.mime_type},
            )
        if metadata.trashed:
            raise GoogleIntegrationError(
                GoogleErrorCode.SOURCE_TRASHED,
                "The selected Google document is in the trash",
            )
        if not metadata.capabilities.can_download:
            raise GoogleIntegrationError(
                GoogleErrorCode.PERMISSION_DENIED,
                "The connected Google principal cannot export this document",
            )

        last_before: NativeGoogleDocument | None = None
        for attempt in range(1, self._max_attempts + 1):
            before = await self._observe(
                connection_id=connection_id,
                file_id=file_id,
                operation="docs.documents.get.before_export",
                attempt=attempt,
                call=lambda: self._provider.get_document(file_id),
            )
            last_before = before
            docx = await self._observe(
                connection_id=connection_id,
                file_id=file_id,
                operation="drive.files.export.docx",
                attempt=attempt,
                call=lambda: self._provider.export_docx(file_id),
            )
            after = await self._observe(
                connection_id=connection_id,
                file_id=file_id,
                operation="docs.documents.get.after_export",
                attempt=attempt,
                call=lambda: self._provider.get_document(file_id),
            )
            if before.revision_id != after.revision_id:
                logger.warning(
                    "google_baseline_revision_mismatch",
                    extra={
                        "safe_metadata": {
                            "connection_id": str(connection_id),
                            "provider_file_id": file_id,
                            "operation": "baseline.capture",
                            "attempt": attempt,
                            "outcome": "discarded_revision_mismatch",
                        }
                    },
                )
                continue
            canonical = canonicalize_google_document(before.raw_payload)
            captured_at = datetime.now(UTC)
            return BaselineCaptureResult(
                metadata=metadata,
                revision_id=before.revision_id,
                native_raw_sha256=sha256_json(before.raw_payload),
                native_canonical_sha256=sha256_json(canonical),
                exported_docx_sha256=sha256_bytes(docx),
                exported_docx_size_bytes=len(docx),
                canonical_payload=canonical,
                native_raw_payload=before.raw_payload,
                docx_bytes=docx,
                attempt_count=attempt,
                capture_started_at=capture_started_at,
                captured_at=captured_at,
            )

        raise GoogleIntegrationError(
            GoogleErrorCode.SOURCE_CHANGED_DURING_CAPTURE,
            "The Google document changed during every baseline export attempt",
            retryable=True,
            safe_details={
                "attempt_count": self._max_attempts,
                "last_revision_observed": last_before.revision_id if last_before else None,
            },
        )

    async def _observe(
        self,
        *,
        connection_id: UUID,
        file_id: str,
        operation: str,
        attempt: int,
        call: Any,
    ) -> Any:
        started = time.monotonic()
        outcome = "succeeded"
        try:
            return await call()
        except GoogleIntegrationError as exc:
            outcome = exc.code.value
            raise
        finally:
            logger.info(
                "google_read_operation",
                extra={
                    "safe_metadata": {
                        "connection_id": str(connection_id),
                        "provider_file_id": file_id,
                        "operation": operation,
                        "attempt": attempt,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                        "outcome": outcome,
                    }
                },
            )


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleIntegrationError(
            GoogleErrorCode.INVALID_RESPONSE,
            "Google API returned invalid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise GoogleIntegrationError(
            GoogleErrorCode.INVALID_RESPONSE,
            "Google API returned an invalid response shape",
        )
    return payload


def _file_metadata(payload: dict[str, Any]) -> GoogleFileMetadata:
    capabilities = payload.get("capabilities") or {}
    version = payload.get("version")
    is_app_authorized = payload.get("isAppAuthorized")
    owned_by_me = payload.get("ownedByMe")
    if isinstance(version, bool) or not isinstance(version, (int, str)):
        provider_version = None
    else:
        provider_version = str(version)
    return GoogleFileMetadata(
        file_id=str(payload.get("id") or ""),
        name=str(payload.get("name") or ""),
        mime_type=str(payload.get("mimeType") or ""),
        parent_ids=tuple(str(value) for value in payload.get("parents") or []),
        drive_id=payload.get("driveId"),
        trashed=bool(payload.get("trashed", False)),
        is_app_authorized=(is_app_authorized if isinstance(is_app_authorized, bool) else None),
        provider_version=provider_version,
        modified_time=payload.get("modifiedTime"),
        spaces=tuple(str(value) for value in payload.get("spaces") or []),
        owned_by_me=owned_by_me if isinstance(owned_by_me, bool) else None,
        capabilities=GoogleReadCapabilities(
            can_edit=bool(capabilities.get("canEdit", False)),
            can_modify_content=bool(capabilities.get("canModifyContent", False)),
            can_download=bool(capabilities.get("canDownload", False)),
            can_copy=bool(capabilities.get("canCopy", False)),
        ),
        content_restrictions=tuple(payload.get("contentRestrictions") or []),
        download_restrictions=payload.get("downloadRestrictions") or {},
        copy_requires_writer_permission=bool(payload.get("copyRequiresWriterPermission", False)),
    )


def _map_google_response(response: httpx.Response) -> GoogleIntegrationError:
    reasons: set[str] = set()
    try:
        payload = response.json()
        errors = (payload.get("error") or {}).get("errors") or []
        reasons = {
            str(item.get("reason"))
            for item in errors
            if isinstance(item, dict) and item.get("reason")
        }
    except (ValueError, AttributeError):
        pass
    if response.status_code == 401:
        return GoogleIntegrationError(
            GoogleErrorCode.REAUTH_REQUIRED,
            "Google authorization is expired or invalid",
        )
    if response.status_code == 404:
        return GoogleIntegrationError(
            GoogleErrorCode.FILE_NOT_FOUND,
            "The Google file does not exist or is not accessible to this connection",
        )
    rate_reasons = {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "dailyLimitExceeded",
        "quotaExceeded",
    }
    if response.status_code == 429 or reasons & rate_reasons:
        return GoogleIntegrationError(
            GoogleErrorCode.RATE_LIMITED,
            "Google API rate limit was reached",
            retryable=True,
        )
    if response.status_code == 403:
        return GoogleIntegrationError(
            GoogleErrorCode.PERMISSION_DENIED,
            "The connected Google principal is not permitted to read this file",
        )
    if response.status_code >= 500:
        return GoogleIntegrationError(
            GoogleErrorCode.UNAVAILABLE,
            "Google API is unavailable",
            retryable=True,
        )
    return GoogleIntegrationError(
        GoogleErrorCode.UNAVAILABLE,
        "Google API could not complete the request",
        retryable=False,
    )
