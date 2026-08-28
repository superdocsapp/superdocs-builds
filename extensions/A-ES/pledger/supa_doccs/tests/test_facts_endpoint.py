"""Document fact view endpoint tests.

Every value the UI will render must come from this API: field name,
value, extraction_method, citation snippet sliced from the STORED file
by persisted offsets, and explicit not-found rows for expected fields
the extractors missed.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.database import SessionLocal
from src.main import app

UPLOAD_DIR = Path("uploads")

SOURCE_TEXT = (
    "LOAN AGREEMENT. The borrower agrees to repay the principal amount "
    "of 100000 USD over 36 months at 15% per annum. Signed by Alice "
    "Johnson and Bob Capital."
)

POS_PRINCIPAL = SOURCE_TEXT.find("principal amount of 100000 USD")
POS_RATE = SOURCE_TEXT.find("15% per annum")


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded_document():
    """Document + version + run + claims rows, plus a stored file."""
    doc_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    stored_path = UPLOAD_DIR / f"{doc_id}.txt"
    stored_path.write_text(SOURCE_TEXT, encoding="utf-8")

    session = SessionLocal()
    try:
        session.execute(text(
            "INSERT INTO documents (id, filename, mime_type) "
            "VALUES (CAST(:id AS uuid), 'factview_loan.txt', 'text/plain')"
        ), {"id": doc_id})
        session.execute(text(
            "INSERT INTO document_versions (id, document_id, content_hash, "
            "storage_ref, version_number) VALUES (CAST(:id AS uuid), "
            "CAST(:doc AS uuid), :h, :ref, 1)"
        ), {"id": version_id, "doc": doc_id, "h": "b" * 64,
            "ref": str(stored_path)})
        session.execute(text(
            "INSERT INTO runs (id, status, initiator, config_snapshot) "
            "VALUES (CAST(:id AS uuid), 'completed', 'fact-view-test', '{}'::jsonb)"
        ), {"id": run_id})
        session.execute(text(
            "INSERT INTO run_steps (run_id, step_name, step_order, status, "
            "output_state) VALUES (CAST(:rid AS uuid), 'classify_document', 3, "
            "'completed', CAST(:out AS jsonb))"
        ), {
            "rid": run_id,
            "out": (
                '{"document_version_id": "%s", '
                '"classification_label": "loan_agreement"}' % version_id
            ),
        })

        def add_claim(claim_type, text_value, method, field_name,
                      start=None, end=None):
            cid = str(uuid.uuid4())
            session.execute(text(
                "INSERT INTO claims (id, document_version_id, run_id, "
                "extracted_text, claim_type, confidence, field_name, "
                "extraction_method) VALUES (CAST(:id AS uuid), "
                "CAST(:vid AS uuid), CAST(:rid AS uuid), :txt, :ctype, "
                ":conf, :field, :method)"
            ), {"id": cid, "vid": version_id, "rid": run_id,
                "txt": text_value, "ctype": claim_type,
                "conf": 0.93, "field": field_name, "method": method})
            if start is not None:
                session.execute(text(
                    "INSERT INTO source_locations (claim_id, "
                    "document_version_id, start_offset, end_offset) VALUES "
                    "(CAST(:id AS uuid), CAST(:vid AS uuid), :s, :e)"
                ), {"id": cid, "vid": version_id, "s": start, "e": end})

        add_claim("loan_agreement.principal_amount",
                  "principal amount of 100000 USD",
                  "structured", "principal_amount", POS_PRINCIPAL, POS_PRINCIPAL + 30)
        add_claim("loan_agreement.interest_rate", "15% per annum",
                  "llm", "interest_rate", POS_RATE, POS_RATE + 13)
        # unverifiable/not-found: no source_locations row
        add_claim("loan_agreement.lender_name", "not_found", "llm_fallback",
                  "lender_name")
        session.commit()
    finally:
        session.close()

    yield {"doc_id": doc_id, "version_id": version_id, "run_id": run_id}

    session = SessionLocal()
    try:
        session.execute(text(
            "DELETE FROM source_locations WHERE document_version_id = CAST(:v AS uuid)"
        ), {"v": version_id})
        session.execute(text(
            "DELETE FROM claims WHERE document_version_id = CAST(:v AS uuid)"
        ), {"v": version_id})
        session.execute(text(
            "DELETE FROM run_steps WHERE run_id = CAST(:r AS uuid)"), {"r": run_id})
        session.execute(text(
            "DELETE FROM runs WHERE id = CAST(:r AS uuid)"), {"r": run_id})
        session.execute(text(
            "DELETE FROM document_versions WHERE id = CAST(:v AS uuid)"), {"v": version_id})
        session.execute(text(
            "DELETE FROM documents WHERE id = CAST(:d AS uuid)"), {"d": doc_id})
        session.commit()
    finally:
        session.close()
        stored_path.unlink(missing_ok=True)


class TestDocumentFactsEndpoint:
    def test_returns_every_field_with_real_resolved_spans(self, client, seeded_document):
        resp = client.get(f"/documents/{seeded_document['doc_id']}/facts")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["classification"] == "loan_agreement"
        assert data["source_text"] == SOURCE_TEXT
        assert data["filename"] == "factview_loan.txt"

        by_field = {f["field_name"]: f for f in data["facts"]}

        # Grounded structured fact: snippet sliced from STORED TEXT by offsets
        principal = by_field["principal_amount"]
        assert principal["extracted_value"] == "principal amount of 100000 USD"
        assert principal["extraction_method"] == "structured"
        span = principal["cited_span"]
        assert span is not None
        assert span["start_offset"] == POS_PRINCIPAL
        assert span["snippet"] == SOURCE_TEXT[POS_PRINCIPAL:POS_PRINCIPAL + 30]
        assert span["snippet"] in data["source_text"]

        # LLM fact with its own span
        rate = by_field["interest_rate"]
        assert rate["extraction_method"] == "llm"
        assert rate["cited_span"]["snippet"] == "15% per annum"

        # not_found from extractor → null value row, still present
        lender = by_field["lender_name"]
        assert lender["extracted_value"] is None
        assert lender["citation_status"] == "not_found"
        assert lender["cited_span"] is None

    def test_expected_fields_missing_from_claims_get_not_found_rows(
        self, client, seeded_document
    ):
        """REQUIRED_FIELDS the extractors never produced → explicit rows."""
        resp = client.get(f"/documents/{seeded_document['doc_id']}/facts")
        by_field = {f["field_name"]: f for f in resp.json()["facts"]}

        # tenure_months was never extracted but IS a REQUIRED_FIELD
        assert "tenure_months" in by_field
        assert by_field["tenure_months"]["extracted_value"] is None
        assert by_field["tenure_months"]["citation_status"] == "not_found"
        assert by_field["tenure_months"]["extraction_method"] is None

    def test_unknown_document_404(self, client):
        resp = client.get(f"/documents/{uuid.uuid4()}/facts")
        assert resp.status_code == 404

    def test_run_id_pins_the_version(self, client, seeded_document):
        resp = client.get(
            f"/documents/{seeded_document['doc_id']}/facts",
            params={"run_id": seeded_document["run_id"]},
        )
        assert resp.status_code == 200
        assert resp.json()["document_version_id"] == seeded_document["version_id"]

    def test_stale_claims_from_older_runs_are_hidden(
        self, client, seeded_document
    ):
        """The view shows the LATEST run's claims only — a pile start
        re-extracts the same document version, and stale rows from
        previous runs (e.g. unverifiable pre-fix spans) must not clutter
        the document view. Pinning the old run_id still serves it."""
        old_run_id = str(uuid.uuid4())
        session = SessionLocal()
        try:
            session.execute(text(
                "INSERT INTO runs (id, status, initiator, config_snapshot, "
                "started_at) VALUES (CAST(:id AS uuid), 'completed', "
                "'fact-view-test', '{}'::jsonb, NOW() - INTERVAL '2 hours')"
            ), {"id": old_run_id})
            session.execute(text(
                "INSERT INTO claims (id, document_version_id, run_id, "
                "extracted_text, claim_type, confidence, field_name, "
                "extraction_method, extracted_at) VALUES (CAST(:id AS uuid), "
                "CAST(:vid AS uuid), CAST(:rid AS uuid), :txt, :ctype, "
                ":conf, :field, :method, NOW() - INTERVAL '1 hour')"
            ), {
                "id": str(uuid.uuid4()),
                "vid": seeded_document["version_id"],
                "rid": old_run_id,
                "txt": "stale unverifiable claim",
                "ctype": "loan_agreement.stale_field",
                "conf": 0.5,
                "field": "stale_field",
                "method": "llm",
            })
            session.commit()
        finally:
            session.close()

        try:
            # Default view: latest run's claims only — no stale row
            resp = client.get(f"/documents/{seeded_document['doc_id']}/facts")
            fields = {f["field_name"] for f in resp.json()["facts"]}
            assert "principal_amount" in fields
            assert "stale_field" not in fields

            # Pinned to the old run: its claim is still auditable
            resp = client.get(
                f"/documents/{seeded_document['doc_id']}/facts",
                params={"run_id": old_run_id},
            )
            fields = {f["field_name"] for f in resp.json()["facts"]}
            assert "stale_field" in fields
            assert "principal_amount" not in fields
        finally:
            session = SessionLocal()
            try:
                session.execute(text(
                    "DELETE FROM claims WHERE run_id = CAST(:r AS uuid)"
                ), {"r": old_run_id})
                session.execute(text(
                    "DELETE FROM runs WHERE id = CAST(:r AS uuid)"
                ), {"r": old_run_id})
                session.commit()
            finally:
                session.close()
