import pytest
import hashlib
import tempfile
import os
from pathlib import Path
from uuid import uuid4
from core.superdocs_client import MockSuperDocsClient


class TestIngestor:
    @pytest.fixture
    def client(self):
        return MockSuperDocsClient(session_id="test-session")

    def _temp_md(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".md")
        os.write(fd, content.encode())
        os.close(fd)
        return path

    @pytest.mark.asyncio
    async def test_ingest_new_file(self, client):
        from agents.ingestor.ingestor import Ingestor

        ing = Ingestor(client, "test-session")
        run_id = uuid4()

        path = self._temp_md("# Test doc\nContent here.")
        try:
            result = await ing.ingest_file(path, run_id, persist=False)
            assert result is not None
            expected_hash = hashlib.sha256(b"# Test doc\nContent here.").hexdigest()
            assert result.file_hash == expected_hash

            # Each document gets its OWN session, derived from the base one.
            # A SuperDocs session holds a single active document, so sharing
            # one session across a corpus made every upload overwrite the
            # document uploaded before it.
            assert result.session_id != "test-session"
            assert result.session_id.startswith("test-session-doc-")
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_ingest_duplicate_idempotent(self, client):
        from agents.ingestor.ingestor import Ingestor

        ing = Ingestor(client, "test-session")
        run_id = uuid4()

        path = self._temp_md("static content")
        try:
            first = await ing.ingest_file(path, run_id, persist=False)
            second = await ing.ingest_file(path, run_id, persist=False)
            assert first is not None
            assert second is not None
            assert second.file_hash == first.file_hash
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_ingest_preserves_filename(self, client):
        from agents.ingestor.ingestor import Ingestor

        ing = Ingestor(client, "test-session")
        run_id = uuid4()

        path = self._temp_md("some content")
        try:
            result = await ing.ingest_file(path, run_id, persist=False)
            assert result is not None
            filename = Path(path).name
            assert result.filename == filename
        finally:
            Path(path).unlink(missing_ok=True)