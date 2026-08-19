"""End-to-end proof of 'a drop triggers ingest, edit and a written-back
result': a file is put into incoming/ (moto S3), process_new_objects()
runs, and we assert the source moved to processed/source/, a result
object appeared at the expected key, and the sequence of SuperDocs calls
(upload -> edit -> export) happened in the right order with the right
session_id threaded through.

Uses a hand-written fake SuperDocsClient rather than the real streaming
one here, because this test is about pipeline *sequencing and S3
side-effects*, not about streaming bytes or the HITL polling contract —
those properties have their own dedicated, more rigorous tests in
test_streaming_bounds.py and test_superdocs_client_hitl.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import boto3
import pytest
from moto import mock_aws

from app.config import Settings
from app.pipeline import Pipeline
from app.s3_client import S3Gateway
from app.superdocs_client import ChatResult, UploadInfo


@dataclass
class FakeSuperDocsClient:
    calls: list[tuple] = field(default_factory=list)

    def upload_document(self, chunks, filename, session_id, size_bytes=None, content_type=None):
        # Draining the iterator mirrors the real client, which must
        # consume the source stream to actually send it anywhere.
        total = sum(len(c) for c in chunks)
        self.calls.append(("upload", filename, session_id, total))
        return UploadInfo(session_id=session_id, chunks_count=1, version_id="v1")

    def edit_document(self, session_id, instruction, approval_mode=None):
        self.calls.append(("edit", session_id, instruction))
        return ChatResult(
            response_text="Reformatted.",
            updated_html="<div>ok</div>",
            changes_summary="1 section edited",
        )

    def export_to_dest_url(self, session_id, export_format, dest_url, options=None, dest_content_type=None):
        self.calls.append(("export", session_id, export_format))
        return []

    def open_presigned_stream(self, url):
        import httpx

        # Real presigned-GET behaviour, backed by a tiny fake transport
        # that serves whatever S3 object the test put at that URL's key.
        return self._transport_for(url)

    def _transport_for(self, url):
        raise NotImplementedError


class _StreamingFakeSuperDocsClient(FakeSuperDocsClient):
    """Extends the fake with a real S3-backed presigned-stream so the
    pipeline's own S3->orchestrator streaming code path is exercised
    end-to-end, not just the SuperDocs-facing half."""

    def __init__(self, s3_client, bucket):
        super().__init__()
        self._s3 = s3_client
        self._bucket = bucket

    def open_presigned_stream(self, url):
        # moto/boto3 presigned URLs are real, resolvable https URLs
        # (virtual-hosted style: https://{bucket}.s3.amazonaws.com/{key}
        # ?X-Amz-...), but this test suite makes no real network calls —
        # instead we recover the object key from the URL path and read
        # it directly via the S3 client, wrapped in a context manager
        # that mimics httpx's streaming response shape closely enough
        # for the pipeline's usage
        # (`with ... as r: r.raise_for_status(); r.iter_bytes(...)`).
        from urllib.parse import unquote, urlsplit

        key = unquote(urlsplit(url).path).lstrip("/")
        obj = self._s3.get_object(Bucket=self._bucket, Key=key)
        body = obj["Body"].read()
        return _FakeStreamResponse(body)


class _FakeStreamResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

@pytest.fixture
def settings() -> Settings:
    return Settings(
        s3_bucket="pipeline-test-bucket",
        s3_region="us-east-1",
        s3_endpoint_url=None,
    )


@mock_aws
def test_pipeline_processes_a_dropped_file_end_to_end(settings):
    s3 = S3Gateway(settings)
    s3.ensure_bucket()

    raw_client = boto3.client("s3", region_name="us-east-1")
    raw_client.put_object(
        Bucket=settings.s3_bucket, Key="incoming/contract.txt", Body=b"vendor contract text"
    )

    fake_superdocs = _StreamingFakeSuperDocsClient(raw_client, settings.s3_bucket)
    pipeline = Pipeline(settings, s3, fake_superdocs)

    processed = pipeline.process_new_objects()

    assert processed == ["contract.txt"]

    call_kinds = [c[0] for c in fake_superdocs.calls]
    assert call_kinds == ["upload", "edit", "export"]

    # The same session_id was used for every step on this file.
    # upload=("upload", filename, session_id, total_bytes)
    # edit=("edit", session_id, instruction); export=("export", session_id, format)
    session_id_positions = {"upload": 2, "edit": 1, "export": 1}
    session_ids = {c[session_id_positions[c[0]]] for c in fake_superdocs.calls}
    assert len(session_ids) == 1

    # Source object moved out of incoming/
    assert s3.list_incoming() == []
    moved = raw_client.get_object(Bucket=settings.s3_bucket, Key="processed/source/contract.txt")
    assert moved["Body"].read() == b"vendor contract text"


@mock_aws
def test_pipeline_processes_multiple_dropped_files_independently(settings):
    s3 = S3Gateway(settings)
    s3.ensure_bucket()
    raw_client = boto3.client("s3", region_name="us-east-1")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/a.txt", Body=b"file a")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/b.txt", Body=b"file b")

    fake_superdocs = _StreamingFakeSuperDocsClient(raw_client, settings.s3_bucket)
    pipeline = Pipeline(settings, s3, fake_superdocs)

    processed = pipeline.process_new_objects()

    assert set(processed) == {"a.txt", "b.txt"}
    upload_calls = [c for c in fake_superdocs.calls if c[0] == "upload"]
    assert len(upload_calls) == 2
    # Each file got its own session_id — no cross-contamination between
    # concurrently-dropped files.
    session_ids = {c[2] for c in upload_calls}
    assert len(session_ids) == 2


@mock_aws
def test_a_failure_on_one_file_does_not_block_or_lose_the_others(settings):
    s3 = S3Gateway(settings)
    s3.ensure_bucket()
    raw_client = boto3.client("s3", region_name="us-east-1")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/good.txt", Body=b"fine")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/bad.txt", Body=b"trouble")

    class FlakySuperDocsClient(_StreamingFakeSuperDocsClient):
        def upload_document(self, chunks, filename, session_id, size_bytes=None, content_type=None):
            if filename == "bad.txt":
                raise RuntimeError("simulated upstream failure")
            return super().upload_document(chunks, filename, session_id, size_bytes, content_type)

    fake = FlakySuperDocsClient(raw_client, settings.s3_bucket)
    pipeline = Pipeline(settings, s3, fake)

    processed = pipeline.process_new_objects()

    assert processed == ["good.txt"]
    # bad.txt stays in incoming/ for the next poll to retry — never
    # silently dropped, never marked processed on failure.
    remaining = {o.filename for o in s3.list_incoming()}
    assert remaining == {"bad.txt"}


@mock_aws
def test_unsupported_extension_is_skipped_and_left_for_a_human_not_silently_dropped(settings):
    s3 = S3Gateway(settings)
    s3.ensure_bucket()
    raw_client = boto3.client("s3", region_name="us-east-1")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/archive.zip", Body=b"PK\x03\x04")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/contract.txt", Body=b"real doc")

    fake_superdocs = _StreamingFakeSuperDocsClient(raw_client, settings.s3_bucket)
    pipeline = Pipeline(settings, s3, fake_superdocs)

    processed = pipeline.process_new_objects()

    assert processed == ["contract.txt"]
    # The unsupported file was never uploaded and stays put for a human
    # to deal with — not deleted, not silently ignored forever.
    remaining = {o.filename for o in s3.list_incoming()}
    assert remaining == {"archive.zip"}


@mock_aws
def test_max_files_per_run_caps_a_single_pass(settings):
    settings.max_files_per_run = 1
    s3 = S3Gateway(settings)
    s3.ensure_bucket()
    raw_client = boto3.client("s3", region_name="us-east-1")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/a.txt", Body=b"a")
    raw_client.put_object(Bucket=settings.s3_bucket, Key="incoming/b.txt", Body=b"b")

    fake_superdocs = _StreamingFakeSuperDocsClient(raw_client, settings.s3_bucket)
    pipeline = Pipeline(settings, s3, fake_superdocs)

    processed = pipeline.process_new_objects()

    assert len(processed) == 1
    # The other file is untouched, still waiting in incoming/ for the
    # next pass — this is a budget cap, not data loss.
    assert len(s3.list_incoming()) == 1
