"""The property this build exists to demonstrate: 'never downloads the
payload to the orchestrator, and handles files far past inline limits.'

Scope, stated precisely: this proves that SuperDocsClient's own reading
of the source stream (upload_document) and the export stream
(export_to_dest_url) is chunked to `chunk_size_bytes` and never asks for
more than that at once, using a 4 MiB fixture against a 256 KiB chunk
size, and separately proves the size-based branch between the direct
multipart path (POST /v1/documents/upload) and the pre-signed path
(POST /v1/uploads -> PUT -> POST /v1/uploads/{id}/process) — the two
real, documented upload paths this build actually uses, not a single
fictional endpoint regardless of size. It does not (and cannot, from
inside a test) prove that no layer of the OS/TCP stack ever buffers a
byte anywhere; that's not a claim this build makes. It proves the
orchestrator's own code path is genuinely chunked.

All HTTP legs are backed by httpx.MockTransport, so this test makes no
network calls and needs no S3, no MinIO, and no SuperDocs API key.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.superdocs_client import SuperDocsClient

CHUNK_SIZE = 256 * 1024  # 256 KiB
DIRECT_UPLOAD_MAX = 5 * 1024 * 1024  # 5 MiB threshold for this test's client
SMALL_FILE_SIZE = 4 * 1024 * 1024  # 4 MiB — under the threshold, direct path
LARGE_FILE_SIZE = 40 * 1024 * 1024  # 40 MiB — over the threshold, pre-signed path

SMALL_PAYLOAD = bytes((i % 251) for i in range(SMALL_FILE_SIZE))
LARGE_PAYLOAD = bytes((i % 251) for i in range(LARGE_FILE_SIZE))


def _chunked_iter(payload: bytes, chunk_size: int = 64 * 1024):
    """Simulates an upstream S3 streaming GET — yields the fixture in
    small pieces rather than as one giant chunk, so the test is
    exercising real chunk-forwarding behaviour, not just re-slicing a
    single bytes object that was already whole in memory."""
    for i in range(0, len(payload), chunk_size):
        yield payload[i : i + chunk_size]


class _RecordingTransport:
    """Shared state captured by the mock transports below, for
    assertions after each call."""

    def __init__(self):
        self.uploaded_bytes: bytes | None = None
        self.presigned_put_bytes: bytes | None = None
        self.dest_put_bytes: bytes | None = None
        self.process_calls: list[dict] = []


@pytest.fixture
def recorder() -> _RecordingTransport:
    return _RecordingTransport()


def _make_superdocs_handler(recorder: _RecordingTransport):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/documents/upload":
            body = request.read()
            recorder.uploaded_bytes = body
            return httpx.Response(
                200,
                json={
                    "html": "<div data-chunk-id='x'>ok</div>",
                    "session_id": "s3-pipeline-test",
                    "filename": "large.txt",
                    "chunks_count": 1,
                    "version_id": "v1",
                },
            )
        if request.method == "POST" and request.url.path == "/v1/uploads":
            payload = json.loads(request.content)
            assert payload["purpose"]  # a purpose value must always be sent
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://fake-s3/superdocs-presigned-put",
                    "upload_id": "up_123",
                },
            )
        if request.method == "POST" and request.url.path == "/v1/uploads/up_123/process":
            recorder.process_calls.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={"session_id": "s3-pipeline-test", "chunks_count": 40, "version_id": "v2"},
            )
        if request.method == "POST" and request.url.path == "/v1/documents/export":
            payload = json.loads(request.content)
            assert payload["session_id"] and payload["format"]
            warnings = base64.b64encode(json.dumps([]).encode()).decode()
            return httpx.Response(
                200,
                content=LARGE_PAYLOAD,
                headers={"X-Export-Warnings": warnings},
            )
        raise AssertionError(f"unexpected superdocs request: {request.method} {request.url}")

    return handler


def _make_raw_handler(recorder: _RecordingTransport):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT" and "superdocs-presigned-put" in str(request.url):
            recorder.presigned_put_bytes = request.read()
            return httpx.Response(200)
        if request.method == "PUT" and "s3-dest" in str(request.url):
            recorder.dest_put_bytes = request.read()
            return httpx.Response(200)
        raise AssertionError(f"unexpected raw request: {request.method} {request.url}")

    return handler


@pytest.fixture
def client(recorder) -> SuperDocsClient:
    superdocs_http = httpx.Client(transport=httpx.MockTransport(_make_superdocs_handler(recorder)))
    raw_http = httpx.Client(transport=httpx.MockTransport(_make_raw_handler(recorder)))
    return SuperDocsClient(
        base_url="https://fake-superdocs",
        api_key="unused-in-tests",
        http_client=superdocs_http,
        raw_http_client=raw_http,
        chunk_size_bytes=CHUNK_SIZE,
        direct_upload_max_bytes=DIRECT_UPLOAD_MAX,
    )


def test_small_file_uploads_via_direct_multipart_in_bounded_chunks(client, recorder):
    result = client.upload_document(
        _chunked_iter(SMALL_PAYLOAD),
        filename="large.txt",
        session_id="s3-pipeline-test",
        size_bytes=SMALL_FILE_SIZE,
    )

    assert result.method == "direct"
    assert result.session_id == "s3-pipeline-test"

    tracker = client.last_upload_tracker
    assert tracker.total_bytes == SMALL_FILE_SIZE
    assert tracker.chunk_count >= 1
    assert tracker.max_chunk_size <= CHUNK_SIZE or tracker.max_chunk_size <= 64 * 1024, (
        f"a chunk of {tracker.max_chunk_size} bytes was read at once — this is exactly "
        f"the 'downloaded the whole payload' failure mode this build is supposed to avoid"
    )

    # The full multipart body was sent, and the file bytes are in there
    # complete and uncorrupted (they're framed by multipart boundary
    # text, so we check containment rather than exact equality).
    assert recorder.uploaded_bytes is not None
    assert SMALL_PAYLOAD in recorder.uploaded_bytes
    assert b'name="session_id"' in recorder.uploaded_bytes
    assert b'filename="large.txt"' in recorder.uploaded_bytes


def test_large_file_uploads_via_presigned_flow_not_direct_multipart(client, recorder):
    """The core claim of this build: a file well past any inline/base64
    limit takes an entirely different, still-streamed path — proving
    'handles files far past inline limits' is a real branch, not an
    assertion about a single endpoint that happens to accept anything."""
    result = client.upload_document(
        _chunked_iter(LARGE_PAYLOAD),
        filename="huge.txt",
        session_id="s3-pipeline-test",
        size_bytes=LARGE_FILE_SIZE,
    )

    assert result.method == "presigned"
    assert result.chunks_count == 40  # from the fake /process response

    # Nothing went to the direct multipart endpoint for this file.
    assert recorder.uploaded_bytes is None
    # Instead, the raw bytes went straight to SuperDocs' own pre-signed
    # PUT URL, streamed and bounded exactly like the direct path.
    assert recorder.presigned_put_bytes == LARGE_PAYLOAD

    tracker = client.last_upload_tracker
    assert tracker.total_bytes == LARGE_FILE_SIZE
    assert tracker.max_chunk_size <= 64 * 1024

    # And /v1/uploads/{upload_id}/process was called with the right
    # session/parse_mode so the file actually lands in our session.
    assert len(recorder.process_calls) == 1
    assert recorder.process_calls[0]["session_id"] == "s3-pipeline-test"
    assert recorder.process_calls[0]["parse_mode"] == "document"


def test_export_streams_to_destination_in_bounded_chunks(client, recorder):
    warnings = client.export_to_dest_url(
        "s3-pipeline-test", "pdf", "https://fake-s3/s3-dest/result.pdf"
    )

    assert warnings == []
    assert recorder.dest_put_bytes == LARGE_PAYLOAD

    tracker = client.last_export_tracker
    assert tracker.total_bytes == LARGE_FILE_SIZE
    assert tracker.max_chunk_size <= CHUNK_SIZE, (
        f"a single export chunk of {tracker.max_chunk_size} bytes was read at once"
    )
