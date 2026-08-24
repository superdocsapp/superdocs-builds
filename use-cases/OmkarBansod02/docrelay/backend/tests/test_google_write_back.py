from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from docrelay.domain.write_plan import GoogleDocsBatchUpdate
from docrelay.integrations.google.canonical import canonicalize_google_document, sha256_json
from docrelay.integrations.google.contracts import CommitClassification
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import GOOGLE_DRIVE_FILE_SCOPE, GOOGLE_OAUTH_SCOPES
from docrelay.integrations.google.write_back import (
    GoogleEffectOutcomeUnknown,
    GoogleWriteHTTPClient,
    compare_effective_permissions,
)


def _document(file_id: str) -> dict[str, Any]:
    text = "Payment is due in 30 days.\n"
    return {
        "documentId": file_id,
        "revisionId": "revision-A",
        "tabs": [
            {
                "tabProperties": {"tabId": "t.0", "title": "Tab 1", "index": 0},
                "documentTab": {
                    "body": {
                        "content": [
                            {
                                "startIndex": 1,
                                "endIndex": len(text) + 1,
                                "paragraph": {
                                    "elements": [
                                        {
                                            "startIndex": 1,
                                            "endIndex": len(text) + 1,
                                            "textRun": {"content": text},
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                },
            }
        ],
    }


def _source_metadata(*, drive_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "source-a",
        "name": "Contract",
        "mimeType": "application/vnd.google-apps.document",
        "parents": ["parent-a"],
        "trashed": False,
        "isAppAuthorized": True,
        "capabilities": {
            "canEdit": True,
            "canModifyContent": True,
            "canDownload": True,
            "canCopy": True,
        },
    }
    if drive_id is not None:
        payload["driveId"] = drive_id
    return payload


def _folder_metadata(
    folder_id: str, *, parent: str | None = None, owned_by_me: bool = False
) -> dict[str, Any]:
    return {
        "id": folder_id,
        "name": f"Folder {folder_id}",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent] if parent is not None else [],
        "trashed": False,
        "spaces": ["drive"],
        "ownedByMe": owned_by_me,
        "capabilities": {"canAddChildren": True},
    }


def _operation() -> GoogleDocsBatchUpdate:
    return GoogleDocsBatchUpdate(
        required_revision_id="revision-A",
        requests=(
            {
                "deleteContentRange": {
                    "range": {
                        "segmentId": "",
                        "tabId": "t.0",
                        "startIndex": 184,
                        "endIndex": 186,
                    }
                }
            },
            {
                "insertText": {
                    "location": {
                        "segmentId": "",
                        "tabId": "t.0",
                        "index": 184,
                    },
                    "text": "30",
                }
            },
        ),
    )


async def test_files_copy_inherits_same_parent_without_acl_mutation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "backup-1",
                "mimeType": "application/vnd.google-apps.document",
                "parents": ["parent-a"],
                "trashed": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleWriteHTTPClient(http=http, access_token=SecretStr("secret-token"))
        receipt = await client.create_backup(
            file_id="source-a",
            destination_parent_id="parent-a",
            backup_name="Contract — DocRelay backup — timestamp — revision-A",
            operation_metadata={
                "docrelayPlan": "plan-a",
                "docrelayEffect": "effect-a",
                "source_revision": "revision-A",
            },
        )

    assert receipt.backup_file_id == "backup-1"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/drive/v3/files/source-a/copy"
    assert request.url.params["ignoreDefaultVisibility"] == "true"
    payload: dict[str, Any] = __import__("json").loads(request.content)
    assert payload == {
        "name": "Contract — DocRelay backup — timestamp — revision-A",
        "appProperties": {
            "docrelayPlan": "plan-a",
            "docrelayEffect": "effect-a",
            "source_revision": "revision-A",
        },
    }
    assert "/permissions" not in request.url.path


async def test_picker_authorized_my_drive_source_can_use_unreadable_discoverable_parent() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/drive/v3/files/source-a":
            return httpx.Response(200, json=_source_metadata())
        if request.url.path == "/drive/v3/files/parent-a":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        if request.url.path == "/v1/documents/source-a":
            return httpx.Response(200, json=_document("source-a"))
        raise AssertionError(f"unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        current = await GoogleWriteHTTPClient(
            http=http, access_token=SecretStr("secret-token")
        ).inspect_current(file_id="source-a", destination_parent_id="parent-a")

    assert current.identity.drive_id is None
    assert current.identity.parent_ids == ("parent-a",)
    assert current.capabilities.destination_can_add_children
    assert (
        current.safe_provider_metadata["backup_destination_proof"]
        == "my_drive_discoverable_parent_inheritance"
    )
    assert paths == [
        "/drive/v3/files/source-a",
        "/drive/v3/files/parent-a",
        "/v1/documents/source-a",
    ]


async def test_watched_write_inspection_rechecks_entire_frozen_root_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files/source-a":
            return httpx.Response(
                200,
                json=_source_metadata() | {"parents": ["nested-a"]},
            )
        if request.url.path == "/drive/v3/files/nested-a":
            return httpx.Response(
                200,
                json=_folder_metadata("nested-a", parent="outside-a"),
            )
        if request.url.path == "/drive/v3/files/root-a":
            return httpx.Response(200, json=_folder_metadata("root-a", owned_by_me=True))
        if request.url.path == "/v1/documents/source-a":
            return httpx.Response(200, json=_document("source-a"))
        raise AssertionError(f"unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        current = await GoogleWriteHTTPClient(
            http=http, access_token=SecretStr("secret-token")
        ).inspect_current(
            file_id="source-a",
            destination_parent_id="nested-a",
            watched_root_id="root-a",
            watched_ancestor_folder_ids=("root-a", "nested-a"),
        )

    assert current.identity.parent_ids == ("nested-a",)
    assert current.safe_provider_metadata["watched_path_verified"] is False


async def test_watched_commit_preflight_blocks_batch_after_path_move() -> None:
    methods_and_paths: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods_and_paths.append((request.method, request.url.path))
        if request.url.path == "/drive/v3/files/source-a":
            return httpx.Response(200, json=_source_metadata() | {"parents": ["nested-a"]})
        if request.url.path == "/drive/v3/files/root-a":
            return httpx.Response(200, json=_folder_metadata("root-a", owned_by_me=True))
        if request.url.path == "/drive/v3/files/nested-a":
            return httpx.Response(200, json=_folder_metadata("nested-a", parent="outside-a"))
        raise AssertionError(f"unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await GoogleWriteHTTPClient(
            http=http, access_token=SecretStr("secret-token")
        ).commit_guarded(
            file_id="source-a",
            operation=_operation(),
            watched_root_id="root-a",
            watched_ancestor_folder_ids=("root-a", "nested-a"),
        )

    assert result.classification is CommitClassification.DEFINITELY_NOT_APPLIED
    assert result.safe_provider_evidence["batch_update_sent"] is False
    assert all(method == "GET" for method, _ in methods_and_paths)


@pytest.mark.parametrize(
    ("backup_drive_id", "broader_acl", "location_ok", "acl_ok"),
    [
        (None, False, True, True),
        (None, True, True, False),
        ("shared-drive-a", False, False, True),
    ],
)
async def test_backup_is_independently_verified_after_copy(
    backup_drive_id: str | None,
    broader_acl: bool,
    location_ok: bool,
    acl_ok: bool,
) -> None:
    owner = {"id": "owner-a", "type": "user", "role": "owner"}
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/drive/v3/files/backup-1":
            payload = _source_metadata(drive_id=backup_drive_id) | {
                "id": "backup-1",
                "name": "Contract backup",
            }
            return httpx.Response(200, json=payload)
        if request.url.path == "/v1/documents/backup-1":
            return httpx.Response(200, json=_document("backup-1"))
        if request.url.path == "/drive/v3/files/source-a/permissions":
            return httpx.Response(200, json={"permissions": [owner]})
        if request.url.path == "/drive/v3/files/backup-1/permissions":
            permissions = [owner]
            if broader_acl:
                permissions.append({"id": "anyone", "type": "anyone", "role": "reader"})
            return httpx.Response(200, json={"permissions": permissions})
        raise AssertionError(f"unexpected request: {request.url}")

    baseline_sha256 = sha256_json(canonicalize_google_document(_document("source-a")))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        verification = await GoogleWriteHTTPClient(
            http=http, access_token=SecretStr("secret-token")
        ).verify_backup(
            source_file_id="source-a",
            backup_file_id="backup-1",
            expected_parent_id="parent-a",
            expected_baseline_sha256=baseline_sha256,
        )

    assert verification.independently_readable
    assert verification.separate_file
    assert verification.expected_mime_type
    assert verification.content_matches_baseline
    assert verification.expected_location is location_ok
    assert verification.acl_not_broader is acl_ok
    assert requests == [
        "/drive/v3/files/backup-1",
        "/v1/documents/backup-1",
        "/drive/v3/files/source-a/permissions",
        "/drive/v3/files/backup-1/permissions",
    ]


async def test_shared_drive_source_fails_closed_before_parent_or_copy() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=_source_metadata(drive_id="shared-drive-a"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleWriteHTTPClient(http=http, access_token=SecretStr("secret-token"))
        with pytest.raises(GoogleIntegrationError) as raised:
            await client.inspect_current(file_id="source-a", destination_parent_id="parent-a")

    assert raised.value.code is GoogleErrorCode.UNSUPPORTED_BACKUP_LOCATION
    assert requests == ["/drive/v3/files/source-a"]


async def test_unreadable_parent_without_my_drive_proof_has_typed_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files/source-a":
            return httpx.Response(200, json=_source_metadata() | {"isAppAuthorized": False})
        if request.url.path == "/drive/v3/files/parent-a":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
        raise AssertionError(f"unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleWriteHTTPClient(http=http, access_token=SecretStr("secret-token"))
        with pytest.raises(GoogleIntegrationError) as raised:
            await client.inspect_current(file_id="source-a", destination_parent_id="parent-a")

    assert raised.value.code is GoogleErrorCode.UNSUPPORTED_BACKUP_LOCATION


def test_phase6_keeps_picker_scoped_drive_file_oauth() -> None:
    assert GOOGLE_OAUTH_SCOPES == ("openid", GOOGLE_DRIVE_FILE_SCOPE)
    assert GOOGLE_DRIVE_FILE_SCOPE == "https://www.googleapis.com/auth/drive.file"


async def test_guarded_batch_payload_is_exact_and_never_uses_target_revision() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"writeControl": {"requiredRevisionId": "revision-B"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await GoogleWriteHTTPClient(
            http=http, access_token=SecretStr("secret-token")
        ).commit_guarded(file_id="source-a", operation=_operation())

    assert result.classification is CommitClassification.SUCCEEDED
    assert captured == [_operation().provider_payload()]
    assert "targetRevisionId" not in str(captured)
    assert "replaceAllText" not in str(captured)


async def test_required_revision_400_is_conflict_and_transport_loss_is_unknown() -> None:
    def conflict(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": (
                        "The required revision ID 'revision-A' does not match the latest revision."
                    ),
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(conflict)) as http:
        result = await GoogleWriteHTTPClient(
            http=http, access_token=SecretStr("secret-token")
        ).commit_guarded(file_id="source-a", operation=_operation())
    assert result.classification is CommitClassification.CONFLICT

    def lost(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lost response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(lost)) as http:
        client = GoogleWriteHTTPClient(http=http, access_token=SecretStr("secret-token"))
        with pytest.raises(GoogleEffectOutcomeUnknown):
            await client.commit_guarded(file_id="source-a", operation=_operation())

    def unusable_copy(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unusable_copy)) as http:
        client = GoogleWriteHTTPClient(http=http, access_token=SecretStr("secret-token"))
        with pytest.raises(GoogleEffectOutcomeUnknown):
            await client.create_backup(
                file_id="source-a",
                destination_parent_id="parent-a",
                backup_name="Synthetic — DocRelay backup — time — revision",
                operation_metadata={"source_revision": "revision-A"},
            )


def test_effective_permission_comparison_fails_closed_on_new_or_elevated_access() -> None:
    source = (
        {"id": "opaque-owner", "type": "user", "role": "owner"},
        {
            "id": "opaque-reader",
            "type": "user",
            "role": "reader",
            "allowFileDiscovery": False,
        },
    )
    same = tuple(dict(item) for item in source)
    safe, evidence = compare_effective_permissions(source, same)
    assert safe
    assert evidence["backup_not_broader"] is True

    broader = (*same, {"id": "anyone", "type": "anyone", "role": "reader"})
    assert compare_effective_permissions(source, broader)[0] is False

    elevated = (source[0], source[1] | {"role": "writer"})
    assert compare_effective_permissions(source, elevated)[0] is False

    discoverable = (source[0], source[1] | {"allowFileDiscovery": True})
    assert compare_effective_permissions(source, discoverable)[0] is False

    unknown_role = (source[0], source[1] | {"role": "futureRole"})
    assert compare_effective_permissions(source, unknown_role)[0] is False

    missing_identity = (source[0], {"type": "user", "role": "reader"})
    assert compare_effective_permissions(source, missing_identity)[0] is False
