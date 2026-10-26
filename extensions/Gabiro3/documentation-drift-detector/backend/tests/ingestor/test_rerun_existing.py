"""Analysing documents that are already ingested must not re-upload them.

SuperDocs already holds the document and we already hold its chunks and their
embeddings. Re-uploading a file only to analyse it again spends a SuperDocs
operation, mints new chunk ids, and — before session-per-document — could
overwrite the document it was trying to analyse.

Documents are copied into the new run rather than shared because
`documents.run_id` is a single foreign key and retrieval is scoped by it: a run
has to own its documents to be able to search them.
"""

import pytest
from fastapi import HTTPException

import agents.ingestor.main as M


class FakeDB:
    """Captures every statement so the copy can be asserted without Postgres."""

    def __init__(self, sources):
        self.sources = sources
        self.statements: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, dict]] = []
        self.dispatched: list[tuple] = []

    async def exec(self, sql, values=None):
        self.statements.append((sql, values or {}))
        if "FROM documents" in sql and "WHERE id IN" in sql:
            return self.sources
        return []

    async def insert(self, table, data, returning="id"):
        self.inserts.append((table, data))
        return {"id": data.get("id", "new")}

    def install(self, monkeypatch):
        monkeypatch.setattr(M, "exec", self.exec)
        monkeypatch.setattr(M, "insert", self.insert)

        async def fake_dispatch(run_id, document_ids, agent="agent_2"):
            self.dispatched.append((run_id, document_ids))
            from uuid import uuid4
            return uuid4()

        monkeypatch.setattr(M.Dispatcher, "dispatch_ingestion", fake_dispatch)
        return self


def doc(name, file_hash, sd_id="sd-1", did=None):
    from uuid import uuid4
    return {
        "id": did or str(uuid4()),
        "filename": name,
        "file_hash": file_hash,
        "session_id": "base-doc-abc",
        "superdocs_doc_id": sd_id,
    }


class TestRerunReusesExistingDocuments:
    @pytest.mark.asyncio
    async def test_creates_a_new_run(self, monkeypatch):
        rows = [doc("intro.md", "h1")]
        db = FakeDB(rows).install(monkeypatch)

        out = await M.run_existing_documents(M.RerunRequest(document_ids=[rows[0]["id"]]))

        assert out["documents"] == 1
        runs = [i for i in db.inserts if i[0] == "runs"]
        assert len(runs) == 1
        assert runs[0][1]["trigger"] == "rerun"

    @pytest.mark.asyncio
    async def test_nothing_is_uploaded_to_superdocs(self, monkeypatch):
        """The whole point: the document is already there."""
        rows = [doc("intro.md", "h1")]
        FakeDB(rows).install(monkeypatch)

        called = []
        monkeypatch.setattr(
            M.Ingestor, "upload_only",
            lambda self, p: called.append(p),
        )
        monkeypatch.setattr(
            M.Ingestor, "ingest_file",
            lambda self, *a, **kw: called.append(a),
        )

        await M.run_existing_documents(M.RerunRequest(document_ids=[rows[0]["id"]]))

        assert called == []

    @pytest.mark.asyncio
    async def test_the_copy_keeps_the_same_superdocs_document(self, monkeypatch):
        """A fix approved in the new run must edit the same real document."""
        rows = [doc("intro.md", "h1", sd_id="sd-durable-42")]
        db = FakeDB(rows).install(monkeypatch)

        await M.run_existing_documents(M.RerunRequest(document_ids=[rows[0]["id"]]))

        copied = [i[1] for i in db.inserts if i[0] == "documents"][0]
        assert copied["superdocs_doc_id"] == "sd-durable-42"
        assert copied["session_id"] == "base-doc-abc"
        assert copied["id"] != rows[0]["id"], "the copy needs its own row"

    @pytest.mark.asyncio
    async def test_chunks_are_copied_with_their_embeddings(self, monkeypatch):
        """Carrying the vectors over is what makes a re-run cost no embedding
        calls; dropping them would silently re-embed unchanged text."""
        rows = [doc("intro.md", "h1")]
        db = FakeDB(rows).install(monkeypatch)

        await M.run_existing_documents(M.RerunRequest(document_ids=[rows[0]["id"]]))

        copy_sql = [s for s, _ in db.statements if "INSERT INTO chunks" in s]
        assert len(copy_sql) == 1
        assert "embedding" in copy_sql[0]
        # Order and search text must survive too, or the new run renders
        # scrambled and cannot be searched.
        assert "ordinal" in copy_sql[0]
        assert "text_content" in copy_sql[0]

    @pytest.mark.asyncio
    async def test_the_analyzer_is_woken_with_the_new_document_ids(self, monkeypatch):
        rows = [doc("a.md", "h1"), doc("b.md", "h2")]
        db = FakeDB(rows).install(monkeypatch)

        out = await M.run_existing_documents(
            M.RerunRequest(document_ids=[r["id"] for r in rows])
        )

        assert len(db.dispatched) == 1
        _, dispatched_ids = db.dispatched[0]
        assert [str(d) for d in dispatched_ids] == out["document_ids"]

    @pytest.mark.asyncio
    async def test_duplicate_files_are_skipped_not_crashed_on(self, monkeypatch):
        """documents is UNIQUE (run_id, file_hash): the same file selected from
        two earlier runs would collide when copied into one new run."""
        rows = [doc("intro.md", "same"), doc("intro.md", "same")]
        FakeDB(rows).install(monkeypatch)

        out = await M.run_existing_documents(
            M.RerunRequest(document_ids=[r["id"] for r in rows])
        )

        assert out["documents"] == 1
        assert out["skipped_duplicates"] == 1


class TestRerunRefusesBadInput:
    @pytest.mark.asyncio
    async def test_empty_selection_is_rejected(self, monkeypatch):
        FakeDB([]).install(monkeypatch)
        with pytest.raises(HTTPException) as exc:
            await M.run_existing_documents(M.RerunRequest(document_ids=[]))
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_documents_are_a_404(self, monkeypatch):
        FakeDB([]).install(monkeypatch)
        from uuid import uuid4
        with pytest.raises(HTTPException) as exc:
            await M.run_existing_documents(M.RerunRequest(document_ids=[str(uuid4())]))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_uuid_ids_are_rejected_before_touching_sql(self, monkeypatch):
        """Ids are interpolated into an IN list, so they must be validated as
        UUIDs rather than trusted."""
        db = FakeDB([]).install(monkeypatch)
        with pytest.raises(HTTPException) as exc:
            await M.run_existing_documents(
                M.RerunRequest(document_ids=["'); DROP TABLE documents; --"])
            )
        assert exc.value.status_code == 400
        assert db.statements == []
