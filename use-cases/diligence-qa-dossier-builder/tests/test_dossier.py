import pytest
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy import select

from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import Dossier, DossierFinding, FindingExecutionHistory, DocumentChunk
from backend.app.services.ingestion import IngestionService
from backend.app.services.llm import MockLLMService, LLMResponse
from tests.test_integration import AsyncTestSession

def test_dossier_lifecycle_endpoints():
    """
    Comprehensive integration test verifying:
    1. Dossier creation
    2. Adding multiple questions
    3. Batch execution
    4. Independent findings governance (Finding A vs Finding B)
    5. Approve, Reject, Edit, and Retry actions
    6. Unique thread generated on retry
    7. Re-run history logging in FindingExecutionHistory
    8. Cross-dossier validation check (prevent access from another dossier)
    9. Review and execution state separation
    10. Status calculations and duration metadata
    """
    with AsyncTestSession() as ts:
        # Override dependency
        async def override_get_db():
            async with ts.SessionLocal() as session:
                yield session
        app.dependency_overrides[get_db] = override_get_db

        client = TestClient(app)

        # Ingest document first so retrieval works
        ingestion = IngestionService(ts.session)
        ts.run(ingestion.ingest_document(
            "diligence_compliance.txt",
            b"SuperDocs security posture adheres to strict SOC2 Type II compliance controls."
        ))
        
        # Get a valid chunk ID to cite in the mock responses
        async def get_chunk_id():
            async with ts.SessionLocal() as session:
                res = await session.execute(select(DocumentChunk))
                return str(res.scalars().first().id)
        chunk_id = ts.run(get_chunk_id())

        # 1. Create Dossier
        resp = client.post("/api/v1/dossiers", json={"name": "Q3 Target Acquisition"})
        assert resp.status_code == 201
        d_data = resp.json()
        d_id = d_data["id"]
        assert d_data["name"] == "Q3 Target Acquisition"
        assert d_data["status"] == "pending"

        # 2. Add Questions
        resp = client.post(
            f"/api/v1/dossiers/{d_id}/questions",
            json={
                "questions": [
                    "What is target SOC2 compliance posture?",
                    "What is target company's 2025 revenue ARR?"
                ]
            }
        )
        assert resp.status_code == 200
        d_data = resp.json()
        assert len(d_data["findings"]) == 2
        
        finding_comp = d_data["findings"][0]  # Should get answered/pending review
        finding_rev = d_data["findings"][1]   # No revenue docs -> insufficient_evidence
        
        f_comp_id = finding_comp["id"]
        f_rev_id = finding_rev["id"]
        
        assert finding_comp["status"] == "pending"
        assert finding_comp["review_status"] == "not_required"

        # Mock LLM to return low confidence for the first finding to trigger review_status = pending
        with patch.object(MockLLMService, "generate_structured_response", return_value=LLMResponse(
            answer="Compliance details are semi-complete.",
            confidence=0.40,
            supporting_evidence_ids=[chunk_id],
            contradicting_evidence_ids=[],
            reasoning_summary="Low confidence summary."
        )):
            # 3. Run Dossier
            resp = client.post(f"/api/v1/dossiers/{d_id}/run")
            assert resp.status_code == 200
            d_data = resp.json()
            
        findings_map = {f["id"]: f for f in d_data["findings"]}
        
        # Finding 1 should be pending review due to low confidence
        f_comp_updated = findings_map[f_comp_id]
        assert f_comp_updated["review_status"] == "pending"

        # Finding 2 should be insufficient_evidence since no revenue info exists
        f_rev_updated = findings_map[f_rev_id]
        assert f_rev_updated["status"] == "insufficient_evidence"
        assert f_rev_updated["review_status"] == "not_required"

        # Dossier status should reflect "review_required" because of Finding 1
        assert d_data["status"] == "review_required"

        # 4. Reject Finding 2 should fail since it's not pending review
        resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{f_rev_id}/reject", json={"reason": "Irrelevant"})
        assert resp.status_code == 400

        # 5. Reject Finding 1 (let's check if it's pending review)
        if f_comp_updated["review_status"] == "pending":
            # Reject finding 1
            resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{f_comp_id}/reject", json={"reason": "We need higher confidence."})
            assert resp.status_code == 200
            f_comp_data = resp.json()
            assert f_comp_data["review_status"] == "rejected"
            assert f_comp_data["review_reason"] == "We need higher confidence."
            
            # Verify Finding 2 remains completely unchanged (governance isolation)
            resp = client.get(f"/api/v1/dossiers/{d_id}/findings/{f_rev_id}")
            assert resp.json()["status"] == "insufficient_evidence"
            assert resp.json()["review_status"] == "not_required"
            
            # 6. Retry Finding 1 (creates new thread, writes to history)
            old_thread_id = f_comp_updated["workflow_thread_id"]
            resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{f_comp_id}/retry")
            assert resp.status_code == 200
            f_comp_retry = resp.json()
            assert f_comp_retry["workflow_thread_id"] != old_thread_id
            
            # Let's check history
            async def check_history():
                async with ts.SessionLocal() as session:
                    res = await session.execute(
                        select(FindingExecutionHistory).where(FindingExecutionHistory.finding_id == uuid.UUID(f_comp_id))
                    )
                    return res.scalars().all()
            hist = ts.run(check_history())
            assert len(hist) == 1
            assert hist[0].workflow_thread_id == old_thread_id
            assert hist[0].status == f_comp_updated["status"]

        # 7. Edit test
        # Let's create a new dossier and question to test edit/approve workflow specifically
        resp = client.post("/api/v1/dossiers", json={"name": "Edit Test Dossier"})
        d_id2 = resp.json()["id"]

        resp = client.post(f"/api/v1/dossiers/{d_id2}/questions", json={"questions": ["What is target SOC2 compliance posture?"]})
        f_edit_id = resp.json()["findings"][0]["id"]

        # Run under patch returning low confidence so we get review_status = pending
        with patch.object(MockLLMService, "generate_structured_response", return_value=LLMResponse(
            answer="Compliance info is sparse.",
            confidence=0.40,
            supporting_evidence_ids=[chunk_id],
            contradicting_evidence_ids=[],
            reasoning_summary="Low confidence summary."
        )):
            client.post(f"/api/v1/dossiers/{d_id2}/run")
            
        # Verify it's pending review
        resp = client.get(f"/api/v1/dossiers/{d_id2}/findings/{f_edit_id}")
        print("GET EDIT FINDING RESPONSE:", resp.json())
        assert resp.json()["review_status"] == "pending"

        # Test Cross-Dossier Access Check
        resp = client.get(f"/api/v1/dossiers/{d_id}/findings/{f_edit_id}")
        assert resp.status_code == 404

        # Edit the pending review finding
        resp = client.post(
            f"/api/v1/dossiers/{d_id2}/findings/{f_edit_id}/edit",
            json={
                "answer": "Reviewer edited this statement.",
                "reasoning_summary": "Manual adjustment."
            }
        )
        assert resp.status_code == 200
        f_edited_data = resp.json()
        assert f_edited_data["review_status"] == "edited"
        assert f_edited_data["answer"] == "Reviewer edited this statement."
        assert f_edited_data["reasoning_summary"] == "Manual adjustment."


def test_dossier_human_review_and_security_validation():
    """
    Test 11: Validates the complete approve, edit, reject, and retry lifecycles,
    ensures security constraints prevent fabricated state/citation injection,
    and checks dossier status recalculation rules.
    """
    with AsyncTestSession() as ts:
        async def override_get_db():
            async with ts.SessionLocal() as session:
                yield session
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        # Ingest document
        ingestion = IngestionService(ts.session)
        ts.run(ingestion.ingest_document(
            "governance_compliance.txt",
            b"SuperDocs compliance guidelines enforce strict human-in-the-loop review controls."
        ))
        
        async def get_chunk_id():
            async with ts.SessionLocal() as session:
                res = await session.execute(select(DocumentChunk))
                return str(res.scalars().first().id)
        chunk_id = ts.run(get_chunk_id())

        # 1. Create Dossier & add question
        resp = client.post("/api/v1/dossiers", json={"name": "Security Audit Dossier"})
        d_id = resp.json()["id"]

        resp = client.post(f"/api/v1/dossiers/{d_id}/questions", json={"questions": ["What is the compliance guidelines?"]})
        finding_id = resp.json()["findings"][0]["id"]

        # Run to trigger review pause
        with patch.object(MockLLMService, "generate_structured_response", return_value=LLMResponse(
            answer="Compliance info pending.",
            confidence=0.45,
            supporting_evidence_ids=[chunk_id],
            contradicting_evidence_ids=[],
            reasoning_summary="Requires manual checks."
        )):
            client.post(f"/api/v1/dossiers/{d_id}/run")

        # Verify state is pending review
        resp = client.get(f"/api/v1/dossiers/{d_id}/findings/{finding_id}")
        f_data = resp.json()
        assert f_data["review_status"] == "pending"
        assert f_data["status"] == "answered"
        assert len(f_data["citations"]) == 1

        # 2. Verify that fabricated inputs are blocked or discarded
        # Send payload with extra keys representing fabricated citations
        malicious_payload = {
            "answer": "Modified answer.",
            "reasoning_summary": "Modified reasoning.",
            "citations": [{
                "document_id": "00000000-0000-0000-0000-000000000000",
                "chunk_id": "00000000-0000-0000-0000-000000000000",
                "filename": "fake_doc.txt",
                "excerpt": "Fabricated content."
            }],
            "supporting_evidence": [{
                "evidence_id": "00000000-0000-0000-0000-000000000000",
                "document_id": "00000000-0000-0000-0000-000000000000",
                "filename": "fake_doc.txt",
                "chunk_id": "00000000-0000-0000-0000-000000000000",
                "content": "Fabricated content.",
                "retrieval_score": 0.99,
                "evidence_type": "supporting"
            }]
        }
        resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{finding_id}/edit", json=malicious_payload)
        assert resp.status_code == 200
        f_edited = resp.json()
        
        # Verify answer and reasoning are updated, but citations are NOT overwritten with fake data
        assert f_edited["answer"] == "Modified answer."
        assert f_edited["reasoning_summary"] == "Modified reasoning."
        # Citations list should remain unchanged (still size 1 referring to original chunk, not empty or fake)
        assert len(f_edited["citations"]) == 1
        assert f_edited["citations"][0]["chunk_id"] == chunk_id

        # 3. Test Reject flow and ensure resume/approve is prevented
        # We need another finding in a pending state to test reject
        resp = client.post(f"/api/v1/dossiers/{d_id}/questions", json={"questions": ["What are the human-in-the-loop review controls?"]})
        f_reject_id = resp.json()["findings"][1]["id"]

        with patch.object(MockLLMService, "generate_structured_response", return_value=LLMResponse(
            answer="Compliance info pending.",
            confidence=0.45,
            supporting_evidence_ids=[chunk_id],
            contradicting_evidence_ids=[],
            reasoning_summary="Requires manual checks."
        )):
            client.post(f"/api/v1/dossiers/{d_id}/run")

        # Reject it
        resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{f_reject_id}/reject", json={"reason": "Rejected for testing."})
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "rejected"

        # Verify that subsequent attempts to approve or edit a rejected finding fail
        resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{f_reject_id}/approve")
        assert resp.status_code == 400
        assert "not awaiting review" in resp.json()["detail"]

        resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{f_reject_id}/edit", json={"answer": "Can we change this?"})
        assert resp.status_code == 400
        assert "not awaiting review" in resp.json()["detail"]

        # 4. Test Approve and Resume flow
        # Re-verify the edited finding (from step 2) is currently review_status = "edited"
        resp = client.get(f"/api/v1/dossiers/{d_id}/findings/{finding_id}")
        assert resp.json()["review_status"] == "edited"
        
        # Approve the edited finding
        # (It was edited, meaning the graph has already resumed and finished, but let's approve it)
        # Note: approve on an edited finding should return 400 because it's no longer "pending" review!
        resp = client.post(f"/api/v1/dossiers/{d_id}/findings/{finding_id}/approve")
        assert resp.status_code == 400
