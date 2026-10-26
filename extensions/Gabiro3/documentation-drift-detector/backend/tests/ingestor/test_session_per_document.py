"""One SuperDocs session holds one document.

Verified against the live API: uploading a second file into a session that
already had a document created no new document and instead bumped
`updated_at` on the existing one — the upload overwrote it. A shared session
therefore cannot hold a corpus, and the shared `SUPERDOCS_SESSION_ID` meant
every ingest destroyed the document ingested before it.

The same experiment showed the two other rules encoded here: an upload with no
session at all answers `persisted: false` and is never stored, and a session
roster reports the durable id under `durable_document_id` while
`document_id` is always the alias "doc_primary".
"""

import hashlib
import os
import tempfile
from uuid import uuid4

import pytest

from agents.ingestor.ingestor import Ingestor
from core.superdocs_client import MockSuperDocsClient, SuperDocsError


@pytest.fixture
def md_file():
    fd, path = tempfile.mkstemp(suffix=".md")
    os.write(fd, b"# Title\n\nRun npm install.")
    os.close(fd)
    yield path
    os.unlink(path)


class RecordingClient(MockSuperDocsClient):
    """Captures the session each upload was sent to."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.sessions: list[str] = []

    async def upload_document(self, file_path, session_id=None):
        self.sessions.append(session_id)
        return await super().upload_document(file_path, session_id=session_id)


class TestSessionPerDocument:
    @pytest.mark.asyncio
    async def test_upload_is_scoped_to_its_own_session(self, md_file):
        client = RecordingClient(session_id="base")
        await Ingestor(client, "base").ingest_file(md_file, uuid4(), persist=False)

        assert client.sessions[0] is not None
        assert client.sessions[0] != "base", "sharing the base session overwrites documents"

    @pytest.mark.asyncio
    async def test_two_documents_never_share_a_session(self):
        """The bug in one assertion: two different files must not collide."""
        client = RecordingClient(session_id="base")
        paths = []
        for body in (b"# One\n\nalpha", b"# Two\n\nbeta"):
            fd, p = tempfile.mkstemp(suffix=".md")
            os.write(fd, body)
            os.close(fd)
            paths.append(p)
        try:
            for p in paths:
                await Ingestor(client, "base").ingest_file(p, uuid4(), persist=False)
        finally:
            for p in paths:
                os.unlink(p)

        assert len(set(client.sessions)) == 2

    @pytest.mark.asyncio
    async def test_same_bytes_reuse_one_session(self, md_file):
        """Keyed by content hash, so a retry does not spawn a second document
        for the same file."""
        client = RecordingClient(session_id="base")
        await Ingestor(client, "base").ingest_file(md_file, uuid4(), persist=False)
        await Ingestor(client, "base").ingest_file(md_file, uuid4(), persist=False)

        assert client.sessions[0] == client.sessions[1]

    @pytest.mark.asyncio
    async def test_session_is_derived_from_the_configured_one(self, md_file):
        client = RecordingClient(session_id="drift-detector-main")
        await Ingestor(client, "drift-detector-main").ingest_file(
            md_file, uuid4(), persist=False
        )
        assert client.sessions[0].startswith("drift-detector-main-doc-")

    @pytest.mark.asyncio
    async def test_the_document_records_the_session_it_lives_in(self, md_file):
        """Editing is session-scoped, so the apply path needs this stored."""
        client = RecordingClient(session_id="base")
        parsed = await Ingestor(client, "base").ingest_file(md_file, uuid4(), persist=False)
        assert parsed.session_id == client.sessions[0]


class NotPersisted(MockSuperDocsClient):
    """The real response when no session is accepted."""

    async def _request(self, method, path, **kwargs):
        return {
            "filename": "x.md",
            "persisted": False,
            "how_to_persist": "send the same request with a session_id",
        }


class TestNonPersistedUploadIsRefused:
    @pytest.mark.asyncio
    async def test_persisted_false_raises_instead_of_storing_nothing(self, md_file):
        """`persisted: false` means a throwaway conversion with no document id.
        Accepting it silently is how a document reaches apply time with an id
        that names nothing."""
        from core.superdocs_client import SuperDocsClient

        client = NotPersisted(session_id="base")
        with pytest.raises(SuperDocsError) as exc:
            # The real uploader, against a mock transport: the mock overrides
            # upload_document wholesale for offline ingest tests.
            await SuperDocsClient.upload_document(client, md_file, session_id="s")
        assert "persist" in str(exc.value).lower()


class RosterClient(MockSuperDocsClient):
    """Serves a session roster in the live API's shape."""

    def __init__(self, roster, **kw):
        super().__init__(**kw)
        self.roster = roster

    async def _request(self, method, path, **kwargs):
        return {"documents": self.roster}


class TestDurableIdResolution:
    @pytest.mark.asyncio
    async def test_reads_the_durable_id_not_the_session_alias(self):
        """`document_id` is always "doc_primary"; storing it produces a 404
        from GET /v1/documents/{id} at apply time."""
        client = RosterClient([
            {"document_id": "doc_primary",
             "durable_document_id": "d-real",
             "title": "configuration"},
        ])
        assert await _real_resolve(client, "s") == "d-real"

    @pytest.mark.asyncio
    async def test_does_not_match_on_title(self):
        """Titles are not identities: several documents share one, and an
        overwritten document keeps its old title while holding new content."""
        client = RosterClient([
            {"document_id": "doc_primary",
             "durable_document_id": "d-real",
             "title": "something-entirely-different"},
        ])
        assert await _real_resolve(client, "s") == "d-real"

    @pytest.mark.asyncio
    async def test_alias_alone_resolves_to_nothing(self):
        client = RosterClient([{"document_id": "doc_primary", "title": "x"}])
        assert await _real_resolve(client, "s") is None

    @pytest.mark.asyncio
    async def test_empty_roster_resolves_to_nothing(self):
        assert await _real_resolve(RosterClient([]), "s") is None


async def _real_resolve(client, session_id):
    """Exercise the real resolver against a mock transport.

    MockSuperDocsClient stubs `_resolve_document_id` for offline ingest tests,
    so the resolution logic itself has to be reached explicitly.
    """
    from core.superdocs_client import SuperDocsClient

    return await SuperDocsClient._resolve_document_id(client, session_id)
