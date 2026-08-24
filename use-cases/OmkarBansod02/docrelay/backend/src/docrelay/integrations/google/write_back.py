from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from docrelay.domain.write_plan import GoogleDocsBatchUpdate
from docrelay.integrations.google.canonical import (
    CANONICALIZER_VERSION,
    canonicalize_google_document,
    sha256_json,
)
from docrelay.integrations.google.contracts import (
    BackupReceipt,
    BackupVerification,
    CommitClassification,
    CurrentGoogleDocument,
    GoogleCapabilities,
    GoogleFileIdentity,
    GuardedCommitResult,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.read_only import (
    DOCS_API_BASE,
    DRIVE_API_BASE,
    DRIVE_FOLDER_MIME,
    GOOGLE_DOC_MIME,
    GoogleReadHTTPClient,
)

COPY_FIELDS = "id,mimeType,parents,driveId,trashed"
DESTINATION_FIELDS = "id,mimeType,trashed,capabilities(canAddChildren)"
PERMISSION_FIELDS = (
    "nextPageToken,permissions("
    "id,type,role,allowFileDiscovery,deleted,pendingOwner,inheritedPermissionsDisabled,"
    "permissionDetails(permissionType,inheritedFrom,role,inherited))"
)


class GoogleEffectOutcomeUnknown(RuntimeError):
    """A mutating request may have reached Google; callers must reconcile, not retry."""


class GoogleWriteHTTPClient:
    def __init__(self, *, http: httpx.AsyncClient, access_token: SecretStr) -> None:
        self._http = http
        self._access_token = access_token
        self._read = GoogleReadHTTPClient(http=http, access_token=access_token)

    async def inspect_current(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        watched_root_id: str | None = None,
        watched_ancestor_folder_ids: tuple[str, ...] = (),
    ) -> CurrentGoogleDocument:
        metadata = await self._read.get_file(file_id)
        if metadata.drive_id is not None:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNSUPPORTED_BACKUP_LOCATION,
                "Shared Drive backup locations are not supported for safe write-back",
            )
        destination_proof = "readable_parent_capability"
        try:
            destination = await self._get_json(
                f"{DRIVE_API_BASE}/files/{quote(destination_parent_id, safe='')}",
                params={"fields": DESTINATION_FIELDS, "supportsAllDrives": "true"},
            )
        except GoogleIntegrationError as exc:
            safe_inherited_parent = (
                exc.code is GoogleErrorCode.FILE_NOT_FOUND
                and metadata.is_app_authorized is True
                and metadata.parent_ids == (destination_parent_id,)
                and metadata.mime_type == GOOGLE_DOC_MIME
                and not metadata.trashed
                and metadata.capabilities.can_copy
            )
            if not safe_inherited_parent:
                if exc.code is GoogleErrorCode.FILE_NOT_FOUND:
                    raise GoogleIntegrationError(
                        GoogleErrorCode.UNSUPPORTED_BACKUP_LOCATION,
                        "Google Drive could not prove a safe My Drive backup location",
                    ) from exc
                raise
            destination_ok = True
            destination_proof = "my_drive_discoverable_parent_inheritance"
        else:
            if destination.get("id") != destination_parent_id:
                raise GoogleIntegrationError(
                    GoogleErrorCode.INVALID_RESPONSE,
                    "Google Drive returned an unexpected backup destination identity",
                )
            destination_ok = (
                destination.get("mimeType") == DRIVE_FOLDER_MIME
                and not bool(destination.get("trashed", False))
                and bool((destination.get("capabilities") or {}).get("canAddChildren", False))
            )
        watched_path_verified: bool | None = None
        if watched_root_id is not None:
            watched_path_verified = await self._watched_path_matches(
                source_parent_ids=metadata.parent_ids,
                destination_parent_id=destination_parent_id,
                root_id=watched_root_id,
                ancestor_folder_ids=watched_ancestor_folder_ids,
            )
        native = await self._read.get_document(file_id)
        canonical = canonicalize_google_document(native.raw_payload)
        return CurrentGoogleDocument(
            identity=GoogleFileIdentity(
                file_id=metadata.file_id,
                parent_ids=metadata.parent_ids,
                drive_id=metadata.drive_id,
                mime_type=metadata.mime_type,
            ),
            name=metadata.name,
            revision_id=native.revision_id,
            native_raw_sha256=sha256_json(native.raw_payload),
            canonical_schema_version=CANONICALIZER_VERSION,
            canonical_sha256=sha256_json(canonical),
            canonical_payload=canonical,
            capabilities=GoogleCapabilities(
                can_edit=metadata.capabilities.can_edit,
                can_modify_content=metadata.capabilities.can_modify_content,
                can_download=metadata.capabilities.can_download,
                can_copy=metadata.capabilities.can_copy,
                destination_can_add_children=destination_ok,
                restrictions={
                    "content_restricted": bool(metadata.content_restrictions),
                    "copy_requires_writer_permission": metadata.copy_requires_writer_permission,
                },
            ),
            safe_provider_metadata={
                "trashed": metadata.trashed,
                "drive_id_present": metadata.drive_id is not None,
                "is_app_authorized": metadata.is_app_authorized,
                "backup_destination_proof": destination_proof,
                "watched_path_verified": watched_path_verified,
            },
        )

    async def _watched_path_matches(
        self,
        *,
        source_parent_ids: tuple[str, ...],
        destination_parent_id: str,
        root_id: str,
        ancestor_folder_ids: tuple[str, ...],
    ) -> bool:
        if (
            not ancestor_folder_ids
            or ancestor_folder_ids[0] != root_id
            or ancestor_folder_ids[-1] != destination_parent_id
            or source_parent_ids != (destination_parent_id,)
        ):
            return False
        previous: str | None = None
        for folder_id in ancestor_folder_ids:
            folder = await self._read.get_file(folder_id)
            if (
                folder.file_id != folder_id
                or folder.mime_type != DRIVE_FOLDER_MIME
                or folder.trashed
                or folder.drive_id is not None
                or "drive" not in folder.spaces
                or (folder_id == root_id and folder.owned_by_me is not True)
                or (previous is not None and folder.parent_ids != (previous,))
            ):
                return False
            previous = folder_id
        return True

    async def create_backup(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        backup_name: str,
        operation_metadata: dict[str, str],
    ) -> BackupReceipt:
        # With no parents override, Drive's files.copy contract inherits the
        # source file's discoverable My Drive parent. The receipt and the
        # independent verification below must still prove the exact parent.
        del destination_parent_id
        response = await self._post_effect(
            f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}/copy",
            params={
                "fields": COPY_FIELDS,
                "supportsAllDrives": "true",
                "ignoreDefaultVisibility": "true",
            },
            payload={
                "name": backup_name,
                "appProperties": operation_metadata,
            },
            effect_name="Google backup copy",
        )
        try:
            payload = _json_object(response)
        except GoogleIntegrationError as exc:
            raise GoogleEffectOutcomeUnknown(
                "Google backup copy returned no usable receipt; copy outcome is unknown"
            ) from exc
        backup_id = payload.get("id")
        parents = payload.get("parents")
        if not isinstance(backup_id, str) or not backup_id or not isinstance(parents, list):
            raise GoogleEffectOutcomeUnknown(
                "Google backup copy returned an unusable receipt; copy outcome is unknown"
            )
        return BackupReceipt(
            backup_file_id=backup_id,
            parent_ids=tuple(str(parent) for parent in parents),
            provider_metadata={
                "mime_type": str(payload.get("mimeType") or ""),
                "drive_id_present": bool(payload.get("driveId")),
                "trashed": bool(payload.get("trashed", False)),
            },
        )

    async def verify_backup(
        self,
        *,
        source_file_id: str,
        backup_file_id: str,
        expected_parent_id: str,
        expected_baseline_sha256: str,
    ) -> BackupVerification:
        backup_metadata = await self._read.get_file(backup_file_id)
        native = await self._read.get_document(backup_file_id)
        canonical = canonicalize_google_document(native.raw_payload)
        canonical_sha256 = sha256_json(canonical)
        source_permissions = await self._permissions(source_file_id)
        backup_permissions = await self._permissions(backup_file_id)
        acl_not_broader, acl_evidence = compare_effective_permissions(
            source_permissions, backup_permissions
        )
        separate_file = backup_file_id != source_file_id
        expected_mime = backup_metadata.mime_type == GOOGLE_DOC_MIME
        expected_location = backup_metadata.drive_id is None and backup_metadata.parent_ids == (
            expected_parent_id,
        )
        content_matches = canonical_sha256 == expected_baseline_sha256
        return BackupVerification(
            independently_readable=True,
            separate_file=separate_file,
            expected_mime_type=expected_mime,
            expected_location=expected_location,
            content_matches_baseline=content_matches,
            acl_not_broader=acl_not_broader,
            canonical_sha256=canonical_sha256,
            evidence={
                "separate_file": separate_file,
                "expected_mime_type": expected_mime,
                "expected_location": expected_location,
                "expected_parent_id": expected_parent_id,
                "observed_parent_ids": list(backup_metadata.parent_ids),
                "observed_drive_id_present": backup_metadata.drive_id is not None,
                "location_contract": "my_drive_discoverable_parent_inheritance",
                "content_matches_baseline": content_matches,
                "permission_comparison": acl_evidence,
            },
        )

    async def commit_guarded(
        self,
        *,
        file_id: str,
        operation: GoogleDocsBatchUpdate,
        watched_root_id: str | None = None,
        watched_ancestor_folder_ids: tuple[str, ...] = (),
    ) -> GuardedCommitResult:
        if watched_root_id is not None:
            metadata = await self._read.get_file(file_id)
            destination_parent_id = (
                watched_ancestor_folder_ids[-1] if watched_ancestor_folder_ids else ""
            )
            path_matches = (
                metadata.mime_type == GOOGLE_DOC_MIME
                and not metadata.trashed
                and metadata.drive_id is None
                and metadata.is_app_authorized is True
                and await self._watched_path_matches(
                    source_parent_ids=metadata.parent_ids,
                    destination_parent_id=destination_parent_id,
                    root_id=watched_root_id,
                    ancestor_folder_ids=watched_ancestor_folder_ids,
                )
            )
            if not path_matches:
                return GuardedCommitResult(
                    classification=CommitClassification.DEFINITELY_NOT_APPLIED,
                    safe_provider_evidence={
                        "preflight": "watched_root_path",
                        "watched_path_verified": False,
                        "batch_update_sent": False,
                    },
                )
        try:
            response = await self._http.post(
                f"{DOCS_API_BASE}/documents/{quote(file_id, safe='')}:batchUpdate",
                json=operation.provider_payload(),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise GoogleEffectOutcomeUnknown(
                "Google batchUpdate response was not received; write outcome is unknown"
            ) from exc
        if response.is_success:
            try:
                payload = _json_object(response)
            except GoogleIntegrationError as exc:
                raise GoogleEffectOutcomeUnknown(
                    "Google batchUpdate returned no usable receipt; write outcome is unknown"
                ) from exc
            write_control = payload.get("writeControl") or {}
            revision = write_control.get("requiredRevisionId")
            return GuardedCommitResult(
                classification=CommitClassification.SUCCEEDED,
                resulting_revision_id=revision if isinstance(revision, str) else None,
                safe_provider_evidence={"http_status": response.status_code},
            )
        reason = _safe_google_reason(response)
        if response.status_code == 400 and reason == "required_revision_mismatch":
            return GuardedCommitResult(
                classification=CommitClassification.CONFLICT,
                safe_provider_evidence={
                    "http_status": response.status_code,
                    "reason": reason,
                },
            )
        if response.status_code == 403:
            return GuardedCommitResult(
                classification=CommitClassification.PERMISSION_DENIED,
                safe_provider_evidence={"http_status": response.status_code},
            )
        if response.status_code in {400, 401, 404}:
            return GuardedCommitResult(
                classification=CommitClassification.DEFINITELY_NOT_APPLIED,
                safe_provider_evidence={"http_status": response.status_code},
            )
        raise GoogleEffectOutcomeUnknown(
            "Google batchUpdate returned an ambiguous response; write outcome is unknown"
        )

    async def _permissions(self, file_id: str) -> tuple[dict[str, Any], ...]:
        permissions: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {
                "fields": PERMISSION_FIELDS,
                "supportsAllDrives": "true",
                "pageSize": "100",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get_json(
                f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}/permissions",
                params=params,
            )
            if bool(payload.get("incompleteSearch", False)):
                raise GoogleIntegrationError(
                    GoogleErrorCode.INVALID_RESPONSE,
                    "Google permission verification was incomplete",
                )
            page = payload.get("permissions")
            if not isinstance(page, list):
                raise GoogleIntegrationError(
                    GoogleErrorCode.INVALID_RESPONSE,
                    "Google returned invalid permission verification data",
                )
            permissions.extend(item for item in page if isinstance(item, dict))
            token = payload.get("nextPageToken")
            if not isinstance(token, str) or not token:
                return tuple(permissions)
            page_token = token

    async def _get_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNAVAILABLE,
                "Google API is unavailable",
                retryable=True,
            ) from exc
        if not response.is_success:
            raise _read_error(response)
        return _json_object(response)

    async def _post_effect(
        self,
        url: str,
        *,
        params: dict[str, str],
        payload: dict[str, Any],
        effect_name: str,
    ) -> httpx.Response:
        try:
            response = await self._http.post(
                url,
                params=params,
                json=payload,
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise GoogleEffectOutcomeUnknown(
                f"{effect_name} response was not received; outcome is unknown"
            ) from exc
        if response.is_success:
            return response
        if response.status_code >= 500 or response.status_code == 429:
            raise GoogleEffectOutcomeUnknown(
                f"{effect_name} returned an ambiguous response; outcome is unknown"
            )
        raise _read_error(response)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token.get_secret_value()}"}


def compare_effective_permissions(
    source: Iterable[dict[str, Any]], backup: Iterable[dict[str, Any]]
) -> tuple[bool, dict[str, Any]]:
    source_values = tuple(item for item in source if _active_permission(item))
    backup_values = tuple(item for item in backup if _active_permission(item))
    invalid_permissions = sum(
        not all(_permission_key(item)) or _role_rank(item.get("role")) is None
        for item in (*source_values, *backup_values)
    )
    source_active = {_permission_key(item): item for item in source_values}
    backup_active = {_permission_key(item): item for item in backup_values}
    unmatched = []
    elevated = []
    expanded_discovery = []
    for key, backup_permission in backup_active.items():
        source_permission = source_active.get(key)
        if source_permission is None:
            unmatched.append(key[0])
            continue
        backup_rank = _role_rank(backup_permission.get("role"))
        source_rank = _role_rank(source_permission.get("role"))
        if backup_rank is None or source_rank is None or backup_rank > source_rank:
            elevated.append(key[0])
        if bool(backup_permission.get("allowFileDiscovery", False)) and not bool(
            source_permission.get("allowFileDiscovery", False)
        ):
            expanded_discovery.append(key[0])
    safe = not invalid_permissions and not unmatched and not elevated and not expanded_discovery
    return safe, {
        "source_active_count": len(source_active),
        "backup_active_count": len(backup_active),
        "invalid_permission_count": invalid_permissions,
        "new_backup_grantee_count": len(unmatched),
        "elevated_backup_role_count": len(elevated),
        "expanded_discovery_count": len(expanded_discovery),
        "backup_not_broader": safe,
    }


def _active_permission(permission: dict[str, Any]) -> bool:
    return not bool(permission.get("deleted", False)) and not bool(
        permission.get("pendingOwner", False)
    )


def _permission_key(permission: dict[str, Any]) -> tuple[str, str]:
    return (str(permission.get("type") or ""), str(permission.get("id") or ""))


def _role_rank(role: object) -> int | None:
    return {
        "reader": 1,
        "commenter": 2,
        "writer": 3,
        "fileOrganizer": 4,
        "organizer": 5,
        "owner": 6,
    }.get(str(role))


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleIntegrationError(
            GoogleErrorCode.INVALID_RESPONSE, "Google API returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise GoogleIntegrationError(
            GoogleErrorCode.INVALID_RESPONSE, "Google API returned an invalid response shape"
        )
    return payload


def _read_error(response: httpx.Response) -> GoogleIntegrationError:
    if response.status_code == 401:
        return GoogleIntegrationError(
            GoogleErrorCode.REAUTH_REQUIRED, "Google authorization is expired or invalid"
        )
    if response.status_code == 403:
        return GoogleIntegrationError(
            GoogleErrorCode.PERMISSION_DENIED,
            "The connected Google principal is not permitted to perform this operation",
        )
    if response.status_code == 404:
        return GoogleIntegrationError(
            GoogleErrorCode.FILE_NOT_FOUND,
            "The Google file does not exist or is not accessible to this connection",
        )
    if response.status_code == 429:
        return GoogleIntegrationError(
            GoogleErrorCode.RATE_LIMITED,
            "Google API rate limit was reached",
            retryable=True,
        )
    return GoogleIntegrationError(
        GoogleErrorCode.UNAVAILABLE,
        "Google API could not complete the request",
        retryable=response.status_code >= 500,
    )


def _safe_google_reason(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
        message = str((payload.get("error") or {}).get("message") or "").lower()
    except (ValueError, AttributeError):
        return None
    if "required revision id" in message and "does not match the latest revision" in message:
        return "required_revision_mismatch"
    return None
