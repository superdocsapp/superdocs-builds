import hashlib
import inspect
from collections import deque
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from docrelay.integrations.google.canonical import (
    CANONICALIZER_VERSION,
    canonicalize_google_document,
    sha256_bytes,
    sha256_json,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.read_only import (
    DOCS_API_BASE,
    DRIVE_API_BASE,
    GOOGLE_DOC_MIME,
    GoogleBaselineCaptureService,
    GoogleFileMetadata,
    GoogleReadCapabilities,
    GoogleReadHTTPClient,
    NativeGoogleDocument,
)


def _metadata(*, mime_type: str = GOOGLE_DOC_MIME) -> GoogleFileMetadata:
    return GoogleFileMetadata(
        file_id="file-123",
        name="Synthetic source",
        mime_type=mime_type,
        parent_ids=("folder-1",),
        capabilities=GoogleReadCapabilities(
            can_edit=True,
            can_modify_content=True,
            can_download=True,
            can_copy=True,
        ),
    )


def _document(revision: str, text: str = "Payment is due in 30 days.\n") -> dict[str, Any]:
    return {
        "documentId": "file-123",
        "revisionId": revision,
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
                                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                    "elements": [
                                        {
                                            "startIndex": 1,
                                            "endIndex": len(text) + 1,
                                            "textRun": {
                                                "content": text,
                                                "textStyle": {
                                                    "link": {"url": "https://example.test"}
                                                },
                                            },
                                        }
                                    ],
                                },
                            }
                        ]
                    },
                    "lists": {"list-1": {"listProperties": {}}},
                    "headers": {},
                    "footers": {},
                    "footnotes": {},
                },
            }
        ],
    }


class SequencedReadProvider:
    def __init__(
        self,
        revisions: list[str],
        *,
        metadata: GoogleFileMetadata | None = None,
        exports: list[bytes] | None = None,
    ) -> None:
        self.revisions = deque(revisions)
        self.metadata = metadata or _metadata()
        self.exports = deque(exports or [b"docx"] * max(1, len(revisions) // 2))
        self.export_count = 0

    async def get_file(self, _: str) -> GoogleFileMetadata:
        return self.metadata

    async def get_document(self, file_id: str) -> NativeGoogleDocument:
        revision = self.revisions.popleft()
        return NativeGoogleDocument(
            file_id=file_id,
            revision_id=revision,
            raw_payload=_document(revision),
        )

    async def export_docx(self, _: str) -> bytes:
        self.export_count += 1
        return self.exports.popleft()


async def test_revision_mismatch_discards_export_and_retries() -> None:
    provider = SequencedReadProvider(
        ["revision-A", "revision-B", "revision-C", "revision-C"],
        exports=[b"discard-this-docx", b"stable-docx"],
    )

    result = await GoogleBaselineCaptureService(provider, max_attempts=2).capture(
        connection_id=uuid4(), file_id="file-123"
    )

    assert result.revision_id == "revision-C"
    assert result.attempt_count == 2
    assert result.docx_bytes == b"stable-docx"
    assert result.exported_docx_sha256 == hashlib.sha256(b"stable-docx").hexdigest()
    assert result.exported_docx_sha256 != hashlib.sha256(b"discard-this-docx").hexdigest()
    assert provider.export_count == 2


async def test_changing_source_exhausts_bounded_policy_without_accepting() -> None:
    provider = SequencedReadProvider(["A", "B", "C", "D"])

    with pytest.raises(GoogleIntegrationError) as raised:
        await GoogleBaselineCaptureService(provider, max_attempts=2).capture(
            connection_id=uuid4(), file_id="file-123"
        )

    assert raised.value.code is GoogleErrorCode.SOURCE_CHANGED_DURING_CAPTURE
    assert raised.value.retryable
    assert raised.value.safe_details["attempt_count"] == 2


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (_metadata(mime_type="application/pdf"), GoogleErrorCode.UNSUPPORTED_SOURCE_TYPE),
        (_metadata().model_copy(update={"trashed": True}), GoogleErrorCode.SOURCE_TRASHED),
        (
            _metadata().model_copy(
                update={"capabilities": GoogleReadCapabilities(can_download=False)}
            ),
            GoogleErrorCode.PERMISSION_DENIED,
        ),
    ],
)
async def test_source_validation_fails_before_native_read_or_export(
    metadata: GoogleFileMetadata, expected: GoogleErrorCode
) -> None:
    provider = SequencedReadProvider(["unused"], metadata=metadata)

    with pytest.raises(GoogleIntegrationError) as raised:
        await GoogleBaselineCaptureService(provider).capture(
            connection_id=uuid4(), file_id="file-123"
        )

    assert raised.value.code is expected
    assert provider.export_count == 0
    assert list(provider.revisions) == ["unused"]


def test_canonical_hashing_is_deterministic_and_versioned() -> None:
    first = _document("opaque-revision")
    first["tabs"][0]["documentTab"]["body"]["content"][0]["paragraph"][
        "suggestedParagraphStyleChanges"
    ] = {"suggestion": {"paragraphStyle": {"alignment": "CENTER"}}}
    second = _document("different-revision")

    canonical_first = canonicalize_google_document(first)
    canonical_second = canonicalize_google_document(second)

    assert canonical_first["schema"] == CANONICALIZER_VERSION
    assert canonical_first == canonical_second
    assert sha256_json(canonical_first) == sha256_json(canonical_second)
    assert sha256_bytes(b"docx") == hashlib.sha256(b"docx").hexdigest()


def test_canonicalizer_preserves_provider_structures_without_generic_ast_conversion() -> None:
    document = _document("opaque-revision")
    tab = document["tabs"][0]
    document_tab = tab["documentTab"]
    paragraph = document_tab["body"]["content"][0]
    document_tab["body"]["content"].append(
        {
            "startIndex": 30,
            "endIndex": 40,
            "table": {
                "rows": 1,
                "columns": 1,
                "tableRows": [
                    {
                        "tableCells": [
                            {"content": [paragraph], "tableCellStyle": {"contentAlignment": "TOP"}}
                        ],
                        "tableRowStyle": {"minRowHeight": {"magnitude": 10}},
                    }
                ],
            },
        }
    )
    document_tab["headers"] = {
        "header-1": {"content": [paragraph]},
    }
    document_tab["documentStyle"] = {"background": {"color": {}}}
    tab["childTabs"] = [
        {
            "tabProperties": {
                "tabId": "t.1",
                "title": "Child",
                "index": 0,
                "nestingLevel": 1,
                "parentTabId": "t.0",
            },
            "documentTab": {"body": {"content": [paragraph]}},
        }
    ]

    canonical = canonicalize_google_document(document)

    canonical_tab = canonical["tabs"][0]
    assert canonical_tab["tabProperties"]["tabId"] == "t.0"
    assert canonical_tab["body"][1]["type"] == "table"
    assert canonical_tab["body"][1]["tableRows"][0]["cells"][0]["content"]
    assert canonical_tab["headers"]["header-1"]["content"]
    assert canonical_tab["documentStyle"] == {"background": {"color": {}}}
    assert canonical_tab["childTabs"][0]["tabProperties"]["parentTabId"] == "t.0"


@pytest.mark.parametrize(
    ("status", "reason", "expected", "retryable"),
    [
        (401, None, GoogleErrorCode.REAUTH_REQUIRED, False),
        (403, "appNotAuthorizedToFile", GoogleErrorCode.PERMISSION_DENIED, False),
        (403, "userRateLimitExceeded", GoogleErrorCode.RATE_LIMITED, True),
        (404, None, GoogleErrorCode.FILE_NOT_FOUND, False),
        (429, None, GoogleErrorCode.RATE_LIMITED, True),
        (503, None, GoogleErrorCode.UNAVAILABLE, True),
    ],
)
async def test_google_provider_errors_are_classified_without_response_leakage(
    status: int,
    reason: str | None,
    expected: GoogleErrorCode,
    retryable: bool,
) -> None:
    payload = {
        "error": {
            "message": "Authorization: Bearer should-never-leak",
            "errors": ([{"reason": reason}] if reason else []),
        }
    }

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleReadHTTPClient(http=http, access_token=SecretStr("access-secret"))
        with pytest.raises(GoogleIntegrationError) as raised:
            await client.get_file("file-123")

    assert raised.value.code is expected
    assert raised.value.retryable is retryable
    assert "should-never-leak" not in raised.value.safe_message
    assert "access-secret" not in raised.value.safe_message


async def test_provider_transport_surface_and_actual_requests_are_read_only() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url).startswith(f"{DOCS_API_BASE}/documents/"):
            return httpx.Response(200, json=_document("opaque-A"))
        if str(request.url).startswith(f"{DRIVE_API_BASE}/files/file-123/export"):
            return httpx.Response(200, content=b"synthetic-docx")
        return httpx.Response(
            200,
            json={
                "id": "file-123",
                "name": "Synthetic source",
                "mimeType": GOOGLE_DOC_MIME,
                "parents": ["folder-1"],
                "trashed": False,
                "capabilities": {"canDownload": True},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = GoogleReadHTTPClient(http=http, access_token=SecretStr("access-secret"))
        await provider.get_file("file-123")
        await provider.get_document("file-123")
        await provider.export_docx("file-123")

    public_provider_methods = {
        name
        for name, member in inspect.getmembers(GoogleReadHTTPClient, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_provider_methods == {
        "get_file",
        "get_document",
        "export_docx",
        "list_children",
    }
    assert {request.method for request in requests} == {"GET"}
    assert all(request.headers["authorization"] == "Bearer access-secret" for request in requests)
    source = inspect.getsource(GoogleReadHTTPClient)
    for prohibited in (
        "batchUpdate",
        "files.copy",
        "files.update",
        "files.create",
        "permissions.create",
        "permissions.update",
        "permissions.delete",
        "files.delete",
    ):
        assert prohibited not in source


async def test_folder_listing_is_parent_bounded_and_parses_pagination_metadata() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "nextPageToken": "next-page",
                "incompleteSearch": False,
                "files": [
                    {
                        "id": "doc-1",
                        "name": "Contract",
                        "mimeType": GOOGLE_DOC_MIME,
                        "parents": ["selected-root"],
                        "version": "42",
                        "modifiedTime": "2026-08-12T12:00:00Z",
                        "spaces": ["drive"],
                        "ownedByMe": True,
                        "trashed": False,
                        "isAppAuthorized": False,
                        "capabilities": {"canDownload": True},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = GoogleReadHTTPClient(http=http, access_token=SecretStr("access-secret"))
        page = await provider.list_children("selected-root")

    assert len(page.items) == 1
    assert page.items[0].provider_version == "42"
    assert page.items[0].parent_ids == ("selected-root",)
    assert page.items[0].owned_by_me is True
    assert page.next_page_token == "next-page"
    assert len(requests) == 1
    query = requests[0].url.params
    assert query["q"] == "'selected-root' in parents and trashed = false"
    assert query["spaces"] == "drive"
    assert query["corpora"] == "user"
    assert query["includeItemsFromAllDrives"] == "false"
