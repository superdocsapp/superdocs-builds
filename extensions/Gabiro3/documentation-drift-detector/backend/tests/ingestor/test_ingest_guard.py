"""An unusable parse must never be persisted.

A document stored with zero chunks renders blank, downloads as an empty
file, and gives the pipeline nothing to reason over — and because ingest is
idempotent by file hash, re-uploading the same file would not repair it.
Failing loudly at ingest is the only point where this is recoverable.
"""

import os
import tempfile
from uuid import uuid4

import pytest

from agents.ingestor.ingestor import EmptyParseError, Ingestor
from core.models import ParsedDocument
from core.superdocs_client import MockSuperDocsClient


def _doc(chunks, html=""):
    return ParsedDocument(
        document_id=uuid4(), session_id="s", superdocs_doc_id="sd-x",
        filename="x.md", file_hash="h", chunks=chunks, html=html,
    )


class NoChunks(MockSuperDocsClient):
    async def upload_document(self, file_path, session_id=None):
        return _doc([])


class BlankChunks(MockSuperDocsClient):
    async def upload_document(self, file_path, session_id=None):
        return _doc([{"chunk_id": "c1", "html": "   "},
                     {"chunk_id": "c2", "html": ""}])


class OneRealChunk(MockSuperDocsClient):
    async def upload_document(self, file_path, session_id=None):
        return _doc([{"chunk_id": "c1", "html": "<p>real</p>"},
                     {"chunk_id": "c2", "html": "  "}])


@pytest.fixture
def md_file():
    fd, path = tempfile.mkstemp(suffix=".md")
    os.write(fd, b"# Title\n\nBody text.")
    os.close(fd)
    yield path
    os.unlink(path)


class TestEmptyParseIsRejected:
    @pytest.mark.asyncio
    async def test_zero_chunks_raises(self, md_file):
        with pytest.raises(EmptyParseError):
            await Ingestor(NoChunks(), "s").ingest_file(md_file, uuid4(), persist=False)

    @pytest.mark.asyncio
    async def test_whitespace_only_chunks_raise(self, md_file):
        with pytest.raises(EmptyParseError):
            await Ingestor(BlankChunks(), "s").ingest_file(md_file, uuid4(), persist=False)

    @pytest.mark.asyncio
    async def test_error_names_the_file_and_says_it_was_not_stored(self, md_file):
        with pytest.raises(EmptyParseError) as exc:
            await Ingestor(NoChunks(), "s").ingest_file(md_file, uuid4(), persist=False)
        msg = str(exc.value)
        assert "was not stored" in msg
        assert os.path.basename(md_file) in msg

    @pytest.mark.asyncio
    async def test_partial_blank_chunks_still_ingest(self, md_file):
        # One real chunk is enough; the blank one is simply dropped.
        parsed = await Ingestor(OneRealChunk(), "s").ingest_file(
            md_file, uuid4(), persist=False
        )
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_normal_document_is_unaffected(self, md_file):
        parsed = await Ingestor(MockSuperDocsClient(), "s").ingest_file(
            md_file, uuid4(), persist=False
        )
        assert parsed is not None
        assert any(c["html"].strip() for c in parsed.chunks)


class TestIngestAtomicity:
    def test_writes_go_through_a_single_transaction(self):
        import inspect

        source = inspect.getsource(Ingestor.ingest_file)
        # Document and chunks must be handed to one transactional call, not
        # inserted one at a time.
        assert "insert_many(writes)" in source
        assert "await insert(" not in source
