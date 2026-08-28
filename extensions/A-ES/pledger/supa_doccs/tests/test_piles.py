"""Tests for piles: creation, multi-doc upload, run with pile, pile isolation.

These tests hit the real Postgres database (requires the piles migration applied).
Each test creates its own pile and cleans up after itself.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.database import SessionLocal
from src.main import app
from src.models.documents import Document, DocumentVersion
from src.models.piles import Pile, PileDocument
from src.models.runs import Run


client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_run_dependents(session, run_ids: list[str]) -> None:
    """Delete claims/source_locations for runs before deleting the runs.

    Since extract_claims persists its durable record at node completion
    (claims.run_id FK is ON DELETE RESTRICT), runs can no longer be
    deleted while their claim rows exist.
    """
    if not run_ids:
        return
    from sqlalchemy import text

    session.execute(
        text(
            "DELETE FROM source_locations WHERE claim_id IN "
            "(SELECT id FROM claims WHERE run_id::text = ANY(:rids))"
        ),
        {"rids": run_ids},
    )
    session.execute(
        text("DELETE FROM claims WHERE run_id::text = ANY(:rids)"),
        {"rids": run_ids},
    )


def _cleanup_pile(pile_id: str) -> None:
    """Remove pile, pile_documents, documents, versions, and runs created by a test."""
    session = SessionLocal()
    try:
        pid = uuid.UUID(pile_id)

        # Delete runs linked to this pile (steps first — RESTRICT FK)
        from sqlalchemy import delete

        run_id_rows = session.execute(
            select(Run.id).where(Run.pile_id == pid)
        ).fetchall()
        _delete_run_dependents(session, [str(r[0]) for r in run_id_rows])
        from src.models.runs import RunStep
        session.execute(
            delete(RunStep).where(
                RunStep.run_id.in_([r[0] for r in run_id_rows])
            )
        )
        session.execute(delete(Run).where(Run.pile_id == pid))

        # Get document IDs from pile_documents
        pile_docs = session.execute(
            PileDocument.__table__.select().where(PileDocument.pile_id == pid)
        ).fetchall()
        doc_ids = [row.document_id for row in pile_docs]

        # Delete pile_documents
        session.execute(delete(PileDocument).where(PileDocument.pile_id == pid))

        # Delete document_versions and documents
        for doc_id in doc_ids:
            session.execute(
                delete(DocumentVersion).where(DocumentVersion.document_id == doc_id)
            )
            session.execute(delete(Document).where(Document.id == doc_id))

        # Delete pile
        session.execute(delete(Pile).where(Pile.id == pid))
        session.commit()
    finally:
        session.close()


def _make_text_file(name: str, content: str = "hello world") -> tuple[str, io.BytesIO, str]:
    """Create an in-memory text file tuple for upload: (filename, file_obj, content_type)."""
    return (name, io.BytesIO(content.encode()), "text/plain")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPileCreation:
    """Test pile CRUD operations."""

    def test_create_pile(self):
        """POST /piles creates a pile and returns its ID."""
        resp = client.post("/piles", json={"name": "Test Pile"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "Test Pile"
        assert "id" in data

        # Cleanup
        _cleanup_pile(data["id"])

    def test_list_piles_includes_new_pile(self):
        """GET /piles returns the newly created pile."""
        resp = client.post("/piles", json={"name": "List Test"})
        pile_id = resp.json()["id"]

        try:
            resp = client.get("/piles")
            assert resp.status_code == 200
            pile_ids = [p["id"] for p in resp.json()]
            assert pile_id in pile_ids
        finally:
            _cleanup_pile(pile_id)

    def test_get_pile_returns_details(self):
        """GET /piles/{id} returns pile with empty documents list."""
        resp = client.post("/piles", json={"name": "Detail Test"})
        pile_id = resp.json()["id"]

        try:
            resp = client.get(f"/piles/{pile_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Detail Test"
            assert data["documents"] == []
        finally:
            _cleanup_pile(pile_id)

    def test_get_nonexistent_pile_returns_404(self):
        """GET /piles/{id} returns 404 for unknown pile."""
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/piles/{fake_id}")
        assert resp.status_code == 404


class TestMultiDocUpload:
    """Test uploading multiple documents into a pile."""

    def test_upload_single_file_to_pile(self):
        """POST /piles/{id}/documents with one file works."""
        resp = client.post("/piles", json={"name": "Single Upload"})
        pile_id = resp.json()["id"]

        try:
            files = [("files", ("doc1.txt", io.BytesIO(b"content one"), "text/plain"))]
            resp = client.post(f"/piles/{pile_id}/documents", files=files)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["pile_id"] == pile_id
            assert len(data["uploaded"]) == 1
            assert data["uploaded"][0]["filename"] == "doc1.txt"
            assert data["uploaded"][0]["size_bytes"] == len(b"content one")
        finally:
            _cleanup_pile(pile_id)

    def test_upload_multiple_files_to_pile(self):
        """POST /piles/{id}/documents with multiple files uploads all."""
        resp = client.post("/piles", json={"name": "Multi Upload"})
        pile_id = resp.json()["id"]

        try:
            files = [
                ("files", ("loan.txt", io.BytesIO(b"loan agreement"), "text/plain")),
                ("files", ("policy.txt", io.BytesIO(b"policy doc"), "text/plain")),
                ("files", ("disclosure.txt", io.BytesIO(b"disclosure"), "text/plain")),
            ]
            resp = client.post(f"/piles/{pile_id}/documents", files=files)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert len(data["uploaded"]) == 3

            filenames = [u["filename"] for u in data["uploaded"]]
            assert "loan.txt" in filenames
            assert "policy.txt" in filenames
            assert "disclosure.txt" in filenames

            # Verify pile detail shows all 3
            detail = client.get(f"/piles/{pile_id}").json()
            assert len(detail["documents"]) == 3
        finally:
            _cleanup_pile(pile_id)

    def test_upload_to_nonexistent_pile_returns_404(self):
        """POST /piles/{id}/documents returns 404 for unknown pile."""
        fake_id = str(uuid.uuid4())
        files = [("files", ("test.txt", io.BytesIO(b"data"), "text/plain"))]
        resp = client.post(f"/piles/{fake_id}/documents", files=files)
        assert resp.status_code == 404


class TestRunWithPile:
    """Test starting a run against a pile."""

    def test_start_run_with_pile_id(self):
        """POST /runs/start with pile_id snapshots all pile docs."""
        # Create pile + upload 2 docs
        resp = client.post("/piles", json={"name": "Run Pile"})
        pile_id = resp.json()["id"]

        try:
            files = [
                ("files", ("doc_a.txt", io.BytesIO(b"document A content"), "text/plain")),
                ("files", ("doc_b.txt", io.BytesIO(b"document B content here"), "text/plain")),
            ]
            upload_resp = client.post(f"/piles/{pile_id}/documents", files=files)
            assert upload_resp.status_code == 200

            # Start a run against the pile
            run_resp = client.post("/runs/start", json={"pile_id": pile_id})
            assert run_resp.status_code == 200, run_resp.text
            run_data = run_resp.json()
            assert run_data["status"] == "started"
            run_id = run_data["run_id"]

            # Verify the run has pile_id and pile_document_ids in config_snapshot
            session = SessionLocal()
            try:
                run = session.execute(
                    Run.__table__.select().where(Run.__table__.c.id == uuid.UUID(run_id))
                ).fetchone()
                assert run is not None
                assert str(run.pile_id) == pile_id
                config = run.config_snapshot
                assert "pile_document_ids" in config
                assert len(config["pile_document_ids"]) == 2
            finally:
                session.close()

            # Cleanup run
            session = SessionLocal()
            try:
                from sqlalchemy import delete
                from src.models.runs import RunStep
                _delete_run_dependents(session, [run_id])
                session.execute(delete(RunStep).where(RunStep.run_id == uuid.UUID(run_id)))
                session.execute(delete(Run).where(Run.id == uuid.UUID(run_id)))
                session.commit()
            finally:
                session.close()
        finally:
            _cleanup_pile(pile_id)

    def test_start_run_with_empty_pile_returns_422(self):
        """POST /runs/start with an empty pile returns 422."""
        resp = client.post("/piles", json={"name": "Empty Pile"})
        pile_id = resp.json()["id"]

        try:
            run_resp = client.post("/runs/start", json={"pile_id": pile_id})
            assert run_resp.status_code == 422
            assert "no documents" in run_resp.json()["detail"].lower()
        finally:
            _cleanup_pile(pile_id)

    def test_all_pile_docs_visible_to_run(self):
        """Run config_snapshot.pile_document_ids contains all pile docs at start time."""
        resp = client.post("/piles", json={"name": "Visibility Pile"})
        pile_id = resp.json()["id"]

        try:
            files = [
                ("files", ("f1.txt", io.BytesIO(b"file 1"), "text/plain")),
                ("files", ("f2.txt", io.BytesIO(b"file 2"), "text/plain")),
                ("files", ("f3.txt", io.BytesIO(b"file 3"), "text/plain")),
            ]
            client.post(f"/piles/{pile_id}/documents", files=files)

            run_resp = client.post("/runs/start", json={"pile_id": pile_id})
            assert run_resp.status_code == 200
            run_id = run_resp.json()["run_id"]

            session = SessionLocal()
            try:
                run = session.execute(
                    Run.__table__.select().where(Run.__table__.c.id == uuid.UUID(run_id))
                ).fetchone()
                pile_doc_ids = run.config_snapshot["pile_document_ids"]
                assert len(pile_doc_ids) == 3

                # Verify each doc_id actually exists
                for doc_id in pile_doc_ids:
                    doc = session.execute(
                        Document.__table__.select().where(
                            Document.__table__.c.id == uuid.UUID(doc_id)
                        )
                    ).fetchone()
                    assert doc is not None
            finally:
                session.close()

            # Cleanup run
            session = SessionLocal()
            try:
                from sqlalchemy import delete
                from src.models.runs import RunStep
                _delete_run_dependents(session, [run_id])
                session.execute(delete(RunStep).where(RunStep.run_id == uuid.UUID(run_id)))
                session.execute(delete(Run).where(Run.id == uuid.UUID(run_id)))
                session.commit()
            finally:
                session.close()
        finally:
            _cleanup_pile(pile_id)


class TestPileIsolation:
    """Test that two piles stay isolated."""

    def test_two_piles_do_not_share_documents(self):
        """Documents in pile A are not visible in pile B."""
        resp_a = client.post("/piles", json={"name": "Pile A"})
        pile_a_id = resp_a.json()["id"]

        resp_b = client.post("/piles", json={"name": "Pile B"})
        pile_b_id = resp_b.json()["id"]

        try:
            # Upload docs to pile A only
            files_a = [
                ("files", ("alpha.txt", io.BytesIO(b"alpha content"), "text/plain")),
                ("files", ("beta.txt", io.BytesIO(b"beta content"), "text/plain")),
            ]
            client.post(f"/piles/{pile_a_id}/documents", files=files_a)

            # Upload different doc to pile B
            files_b = [
                ("files", ("gamma.txt", io.BytesIO(b"gamma content"), "text/plain")),
            ]
            client.post(f"/piles/{pile_b_id}/documents", files=files_b)

            # Verify pile A has 2 docs
            detail_a = client.get(f"/piles/{pile_a_id}").json()
            assert len(detail_a["documents"]) == 2
            a_filenames = {d["filename"] for d in detail_a["documents"]}
            assert a_filenames == {"alpha.txt", "beta.txt"}

            # Verify pile B has 1 doc
            detail_b = client.get(f"/piles/{pile_b_id}").json()
            assert len(detail_b["documents"]) == 1
            assert detail_b["documents"][0]["filename"] == "gamma.txt"

            # Start runs against each pile — they should have different doc sets
            run_a = client.post("/runs/start", json={"pile_id": pile_a_id}).json()
            run_b = client.post("/runs/start", json={"pile_id": pile_b_id}).json()

            session = SessionLocal()
            try:
                row_a = session.execute(
                    Run.__table__.select().where(
                        Run.__table__.c.id == uuid.UUID(run_a["run_id"])
                    )
                ).fetchone()
                row_b = session.execute(
                    Run.__table__.select().where(
                        Run.__table__.c.id == uuid.UUID(run_b["run_id"])
                    )
                ).fetchone()

                docs_a = set(row_a.config_snapshot["pile_document_ids"])
                docs_b = set(row_b.config_snapshot["pile_document_ids"])

                # No overlap
                assert docs_a.isdisjoint(docs_b)
                assert len(docs_a) == 2
                assert len(docs_b) == 1
            finally:
                session.close()

            # Cleanup runs
            session = SessionLocal()
            try:
                from sqlalchemy import delete
                from src.models.runs import RunStep
                _delete_run_dependents(session, [run_a["run_id"], run_b["run_id"]])
                for rid in [run_a["run_id"], run_b["run_id"]]:
                    session.execute(delete(RunStep).where(RunStep.run_id == uuid.UUID(rid)))
                    session.execute(delete(Run).where(Run.id == uuid.UUID(rid)))
                session.commit()
            finally:
                session.close()
        finally:
            _cleanup_pile(pile_a_id)
            _cleanup_pile(pile_b_id)


class TestPileRunFanOut:
    """A pile start must create one run per pile document (invariant 10)."""

    def test_pile_start_creates_one_run_per_document(self):
        """POST /runs/start with a 3-doc pile returns 3 run_ids, each
        targeting a distinct pile document."""
        resp = client.post("/piles", json={"name": "Fan Out Pile"})
        pile_id = resp.json()["id"]

        try:
            files = [
                ("files", ("fan_a.txt", io.BytesIO(b"alpha content"), "text/plain")),
                ("files", ("fan_b.txt", io.BytesIO(b"beta content"), "text/plain")),
                ("files", ("fan_c.txt", io.BytesIO(b"gamma content"), "text/plain")),
            ]
            upload_resp = client.post(f"/piles/{pile_id}/documents", files=files)
            assert upload_resp.status_code == 200
            uploaded_doc_ids = {d["document_id"] for d in upload_resp.json()["uploaded"]}

            run_resp = client.post("/runs/start", json={"pile_id": pile_id})
            assert run_resp.status_code == 200, run_resp.text
            run_data = run_resp.json()

            assert run_data["status"] == "started"
            run_ids = run_data["run_ids"]
            assert len(run_ids) == 3
            assert run_data["run_id"] == run_ids[0]

            session = SessionLocal()
            try:
                rows = session.execute(
                    Run.__table__.select().where(
                        Run.__table__.c.id.in_([uuid.UUID(r) for r in run_ids])
                    )
                ).fetchall()
                assert len(rows) == 3

                target_docs = set()
                for row in rows:
                    assert str(row.pile_id) == pile_id
                    target_docs.add(row.config_snapshot["document_id"])
                    # Every run snapshots the full pile document list
                    assert set(row.config_snapshot["pile_document_ids"]) == uploaded_doc_ids

                # Each run targets a distinct document, covering the pile
                assert target_docs == uploaded_doc_ids
            finally:
                session.close()
        finally:
            _cleanup_pile(pile_id)
