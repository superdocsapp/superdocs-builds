import pytest
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy import select

from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import Dossier, DossierFinding, DocumentChunk
from backend.app.services.ingestion import IngestionService
from backend.app.services.llm import MockLLMService, LLMResponse
from tests.test_integration import AsyncTestSession

def test_investor_mode_and_export_features():
    """
    Verifies Investor Mode behavior, separation of evidence gaps vs pending review,
    export formatting, and cross-dossier data leakage prevention.
    """
    with AsyncTestSession() as ts:
        # Override db session dependency
        async def override_get_db():
            async with ts.SessionLocal() as session:
                yield session
        app.dependency_overrides[get_db] = override_get_db

        client = TestClient(app)

        # Ingest one document with facts to allow reference citations
        ingestion = IngestionService(ts.session)
        ts.run(ingestion.ingest_document(
            "compliance_doc.txt",
            b"SuperDocs compliance framework implements robust data protection standard policies."
        ))
        
        # Get a chunk ID to cite in the mock responses
        async def get_chunk_info():
            async with ts.SessionLocal() as session:
                res = await session.execute(select(DocumentChunk))
                chunk = res.scalars().first()
                return str(chunk.id), str(chunk.document_id)
        chunk_id, doc_id = ts.run(get_chunk_info())

        # Create Dossier A (Target Acme)
        resp = client.post("/api/v1/dossiers", json={"name": "Dossier A Acme Acquisition"})
        assert resp.status_code == 201
        dossier_a = resp.json()
        d_a_id = dossier_a["id"]

        # Create Dossier B (Target Beta)
        resp = client.post("/api/v1/dossiers", json={"name": "Dossier B Beta Merger"})
        assert resp.status_code == 201
        dossier_b = resp.json()
        d_b_id = dossier_b["id"]

        # Add questions for Dossier A
        resp = client.post(
            f"/api/v1/dossiers/{d_a_id}/questions",
            json={
                "questions": [
                    "What is target SOC2 compliance posture?",  # will get answered & pending review
                    "What is target company's 2025 revenue ARR?",  # will get insufficient_evidence
                    "Are there IP assignment conflicts?"  # will get answered & approved
                ]
            }
        )
        assert resp.status_code == 200
        dossier_a = resp.json()
        assert len(dossier_a["findings"]) == 3

        # Add question for Dossier B (to verify cross-dossier isolation)
        resp = client.post(
            f"/api/v1/dossiers/{d_b_id}/questions",
            json={"questions": ["What is BetaCorp secret sauce?"]}
        )
        assert resp.status_code == 200
        dossier_b = resp.json()
        assert len(dossier_b["findings"]) == 1

        # We will mock the LLM responses for the runs to transition them into the exact target states:
        # Question 1: answered & pending review (low confidence)
        # Question 2: insufficient_evidence
        # Question 3: answered & approved
        # Question B1: answered & rejected
        
        # Run Dossier A
        f_q1_id = dossier_a["findings"][0]["id"]
        f_q2_id = dossier_a["findings"][1]["id"]
        f_q3_id = dossier_a["findings"][2]["id"]
        f_qb_id = dossier_b["findings"][0]["id"]

        # 1. Run Finding Q1 with low confidence to keep it 'pending' review
        with patch.object(MockLLMService, "generate_structured_response", return_value=LLMResponse(
            answer="SOC2 compliance is in progress.",
            confidence=0.40,
            supporting_evidence_ids=[chunk_id],
            contradicting_evidence_ids=[],
            reasoning_summary="Limited documentation found."
        )):
            resp = client.post(f"/api/v1/dossiers/{d_a_id}/run")
            assert resp.status_code == 200

        # 2. To simulate Question 2 getting insufficient_evidence, we can update it in the database directly
        async def force_db_states():
            async with ts.SessionLocal() as session:
                # Finding 1: answered & pending review
                res = await session.execute(select(DossierFinding).where(DossierFinding.id == f_q1_id))
                f1 = res.scalar()
                f1.status = "answered"
                f1.answer = "SOC2 compliance is in progress."
                f1.review_status = "pending"
                f1.confidence = 0.40
                f1.citations = [{
                    "document_id": doc_id,
                    "chunk_id": chunk_id,
                    "filename": "compliance_doc.txt",
                    "section": "1.1",
                    "page_number": 1,
                    "excerpt": "SuperDocs compliance framework implements"
                }]
                f1.reasoning_summary = "Limited documentation found."

                # Finding 2: insufficient_evidence
                res = await session.execute(select(DossierFinding).where(DossierFinding.id == f_q2_id))
                f2 = res.scalar()
                f2.status = "insufficient_evidence"
                f2.answer = ""
                f2.citations = []
                f2.reasoning_summary = "No documents found containing target financial details."

                # Finding 3: answered & approved
                res = await session.execute(select(DossierFinding).where(DossierFinding.id == f_q3_id))
                f3 = res.scalar()
                f3.status = "answered"
                f3.answer = "IP assignments are fully executed."
                f3.citations = [{
                    "document_id": doc_id,
                    "chunk_id": chunk_id,
                    "filename": "compliance_doc.txt",
                    "section": "1.2",
                    "page_number": 1,
                    "excerpt": "framework implements robust data protection"
                }]
                f3.review_status = "pending"
                f3.confidence = 0.95
                f3.reasoning_summary = "All signatures present."
                
                # Dossier B Finding: answered & rejected
                res = await session.execute(select(DossierFinding).where(DossierFinding.id == f_qb_id))
                fb = res.scalar()
                fb.status = "answered"
                fb.answer = "Secret sauce details leaked."
                fb.review_status = "pending"
                fb.confidence = 0.85
                fb.reasoning_summary = "Proprietary recipes found."

                await session.commit()

        ts.run(force_db_states())

        # Approve Finding 3 via endpoint to set review_status to "approved"
        resp = client.post(f"/api/v1/dossiers/{d_a_id}/findings/{f_q3_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "approved"

        # Reject Dossier B Finding via endpoint to set review_status to "rejected"
        resp = client.post(
            f"/api/v1/dossiers/{d_b_id}/findings/{f_qb_id}/reject",
            json={"reason": "Contains trade secret secrets."}
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "rejected"

        # Fetch latest dossiers to verify states
        resp = client.get(f"/api/v1/dossiers/{d_a_id}")
        d_a_latest = resp.json()
        findings_map = {f["id"]: f for f in d_a_latest["findings"]}

        assert findings_map[f_q1_id]["status"] == "answered"
        assert findings_map[f_q1_id]["review_status"] == "pending"

        assert findings_map[f_q2_id]["status"] == "insufficient_evidence"
        assert findings_map[f_q2_id]["review_status"] == "not_required"

        assert findings_map[f_q3_id]["status"] == "answered"
        assert findings_map[f_q3_id]["review_status"] == "approved"

        # Verification 1: Export Endpoint returns correct Markdown content
        resp = client.get(f"/api/v1/dossiers/{d_a_id}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        
        md_content = resp.text
        
        # Verification 2: Dossier name appears
        assert "# Diligence Dossier Report: Dossier A Acme Acquisition" in md_content
        assert d_a_id in md_content

        # Verification 3: Questions/answers appear
        assert "What is target SOC2 compliance posture?" in md_content
        assert "SOC2 compliance is in progress." in md_content
        assert "Are there IP assignment conflicts?" in md_content
        assert "IP assignments are fully executed." in md_content

        # Verification 4: Finding statuses and review statuses appear
        assert "Workflow Status**: ANSWERED" in md_content
        assert "Governance Status**: PENDING" in md_content
        assert "Governance Status**: APPROVED" in md_content
        assert "Workflow Status**: INSUFFICIENT EVIDENCE" in md_content

        # Verification 5: Citations appear
        assert "compliance_doc.txt" in md_content
        assert "Section**: `1.2`" in md_content
        assert "Page**: `1`" in md_content
        assert "Excerpt" in md_content

        # Verification 6: Evidence gaps are correctly identified
        assert "Unresolved Diligence Gap" in md_content
        assert "Evidence was found to be insufficient to answer this question." in md_content

        # Verification 7: Empty evidence is handled honestly (honest statement)
        assert "Evidence was not found in the data room documents." in md_content

        # Verification 8: Cross-dossier export isolation (Dossier A export does NOT contain Dossier B data)
        assert "BetaCorp" not in md_content
        assert "Secret sauce" not in md_content
        assert d_b_id not in md_content

        # Export Dossier B to confirm it gets its own details
        resp_b = client.get(f"/api/v1/dossiers/{d_b_id}/export")
        assert resp_b.status_code == 200
        md_b = resp_b.text
        assert "Dossier B Beta Merger" in md_b
        assert "Secret sauce" in md_b
        assert "Governance Status**: REJECTED" in md_b
        assert "Contains trade secret secrets." in md_b  # reviewer notes
        # No Dossier A data leaks into B
        assert "Acme Acquisition" not in md_b
        assert d_a_id not in md_b
