import pytest
import uuid
import asyncio
import httpx
from httpx import ASGITransport
from sqlalchemy import select

from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import Dossier, DossierFinding, FindingExecutionHistory
from backend.app.services.ingestion import IngestionService
from tests.test_integration import AsyncTestSession

def test_concurrency_e2e():
    """
    E2E concurrency and isolation integration test.
    1. Ingests unique/disjoint document data rooms for Dossier A (AlphaCorp) and Dossier B (BetaCorp).
    2. Runs both dossier workflows concurrently using asyncio.gather over httpx.AsyncClient.
    3. Verifies that retrievals, states, and citations remain completely isolated (A only references A, B only references B).
    4. Confirms checkpoint thread/run identifier separation.
    5. Checks human review governance isolation (approving A does not affect B; rejecting B does not affect A).
    6. Verifies audit history logs are correctly associated.
    """
    with AsyncTestSession() as ts:
        # Override database dependency for the duration of the test
        async def override_get_db():
            async with ts.SessionLocal() as session:
                yield session
        app.dependency_overrides[get_db] = override_get_db

        # 1. Ingest documents for Dossier A and Dossier B
        # Use disjoint keywords ("revenue" for AlphaCorp, "ARR" for BetaCorp) to isolate semantic vector queries
        ingestion = IngestionService(ts.session)
        
        # Document A1 & A2 (AlphaCorp revenue conflict)
        doc_a1 = ts.run(ingestion.ingest_document(
            "alphacorp_financials.txt",
            b"AlphaCorp revenue was $2.4M."
        ))
        doc_a2 = ts.run(ingestion.ingest_document(
            "alphacorp_investor.txt",
            b"AlphaCorp revenue was $3.1M."
        ))
        
        # Document B1 & B2 (BetaCorp ARR conflict)
        doc_b1 = ts.run(ingestion.ingest_document(
            "betacorp_financials.txt",
            b"BetaCorp ARR was $2.4M."
        ))
        doc_b2 = ts.run(ingestion.ingest_document(
            "betacorp_investor.txt",
            b"BetaCorp ARR was $3.1M."
        ))
        
        assert doc_a1.status == "completed"
        assert doc_a2.status == "completed"
        assert doc_b1.status == "completed"
        assert doc_b2.status == "completed"

        async def run_concurrently():
            # Standard ASGI Transport for httpx 0.20+
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                # 2. Create Dossiers
                resp_a = await ac.post("/api/v1/dossiers", json={"name": "Dossier A"})
                assert resp_a.status_code == 201
                d_a = resp_a.json()
                id_a = d_a["id"]

                resp_b = await ac.post("/api/v1/dossiers", json={"name": "Dossier B"})
                assert resp_b.status_code == 201
                d_b = resp_b.json()
                id_b = d_b["id"]

                # 3. Add Questions
                q_a = "AlphaCorp revenue"
                q_b = "BetaCorp ARR"

                resp_q_a = await ac.post(f"/api/v1/dossiers/{id_a}/questions", json={"questions": [q_a]})
                assert resp_q_a.status_code == 200
                finding_a_id = resp_q_a.json()["findings"][0]["id"]
                thread_a_id = resp_q_a.json()["findings"][0]["workflow_thread_id"]

                resp_q_b = await ac.post(f"/api/v1/dossiers/{id_b}/questions", json={"questions": [q_b]})
                assert resp_q_b.status_code == 200
                finding_b_id = resp_q_b.json()["findings"][0]["id"]
                thread_b_id = resp_q_b.json()["findings"][0]["workflow_thread_id"]

                # Checkpoint thread ID isolation check
                assert thread_a_id != thread_b_id

                # 4. Trigger concurrent runs
                task_a = ac.post(f"/api/v1/dossiers/{id_a}/run")
                task_b = ac.post(f"/api/v1/dossiers/{id_b}/run")

                results = await asyncio.gather(task_a, task_b)
                assert results[0].status_code == 200
                assert results[1].status_code == 200

                # 5. Fetch findings details
                get_a = await ac.get(f"/api/v1/dossiers/{id_a}/findings/{finding_a_id}")
                assert get_a.status_code == 200
                data_a = get_a.json()

                get_b = await ac.get(f"/api/v1/dossiers/{id_b}/findings/{finding_b_id}")
                assert get_b.status_code == 200
                data_b = get_b.json()

                return data_a, data_b, id_a, id_b, finding_a_id, finding_b_id

        data_a, data_b, id_a, id_b, finding_a_id, finding_b_id = ts.run(run_concurrently())

        # --- ISOLATION ASSERTIONS ---

        # A. State separation (No cross contamination of outputs)
        assert data_a["status"] == "conflict"
        assert "Revenue conflict detected" in data_a["reasoning_summary"]
        assert "alphacorp_financials.txt" in data_a["reasoning_summary"]
        assert "betacorp_financials.txt" not in data_a["reasoning_summary"]

        assert data_b["status"] == "conflict"
        assert "Revenue conflict detected" in data_b["reasoning_summary"]
        assert "betacorp_financials.txt" in data_b["reasoning_summary"]
        assert "alphacorp_financials.txt" not in data_b["reasoning_summary"]

        # B. Document/Evidence isolation (supporting chunks only belong to respective target)
        assert len(data_a["supporting_evidence"]) > 0
        for ev in data_a["supporting_evidence"]:
            assert "AlphaCorp" in ev["content"]
            assert "BetaCorp" not in ev["content"]

        assert len(data_b["supporting_evidence"]) > 0
        for ev in data_b["supporting_evidence"]:
            assert "BetaCorp" in ev["content"]
            assert "AlphaCorp" not in ev["content"]

        # C. Citation isolation (filenames match source upload partition)
        assert len(data_a["citations"]) > 0
        for cit in data_a["citations"]:
            assert cit["filename"] in ["alphacorp_financials.txt", "alphacorp_investor.txt"]

        assert len(data_b["citations"]) > 0
        for cit in data_b["citations"]:
            assert cit["filename"] in ["betacorp_financials.txt", "betacorp_investor.txt"]

        # D. Human review state isolation (approving A does not affect B; rejecting B does not affect A)
        async def verify_governance_actions():
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                # Approve finding A
                app_a = await ac.post(f"/api/v1/dossiers/{id_a}/findings/{finding_a_id}/approve")
                assert app_a.status_code == 200
                res_a = app_a.json()
                assert res_a["review_status"] == "approved"
                
                # Verify B remains in pending status
                get_b = await ac.get(f"/api/v1/dossiers/{id_b}/findings/{finding_b_id}")
                assert get_b.json()["review_status"] == "pending"

                # Reject finding B
                rej_b = await ac.post(
                    f"/api/v1/dossiers/{id_b}/findings/{finding_b_id}/reject",
                    json={"reason": "Incorrect revenue conflict data"}
                )
                assert rej_b.status_code == 200
                res_b = rej_b.json()
                assert res_b["review_status"] == "rejected"
                assert res_b["review_reason"] == "Incorrect revenue conflict data"

                # Verify A remains approved
                get_a = await ac.get(f"/api/v1/dossiers/{id_a}/findings/{finding_a_id}")
                assert get_a.json()["review_status"] == "approved"

                # Trigger retry to test execution history isolation
                ret_a = await ac.post(f"/api/v1/dossiers/{id_a}/findings/{finding_a_id}/retry")
                assert ret_a.status_code == 200
                return ret_a.json()

        res_retry_a = ts.run(verify_governance_actions())

        # E. Database execution history isolation (check record exists and belongs to A, not B)
        async def check_history_db():
            async with ts.SessionLocal() as session:
                stmt = select(FindingExecutionHistory).where(FindingExecutionHistory.finding_id == finding_a_id)
                hist_a = (await session.execute(stmt)).scalars().all()
                
                stmt_b = select(FindingExecutionHistory).where(FindingExecutionHistory.finding_id == finding_b_id)
                hist_b = (await session.execute(stmt_b)).scalars().all()
                
                return len(hist_a), len(hist_b)

        count_hist_a, count_hist_b = ts.run(check_history_db())
        assert count_hist_a == 1
        assert count_hist_b == 0

        # Clean up dependency overrides
        app.dependency_overrides.clear()
