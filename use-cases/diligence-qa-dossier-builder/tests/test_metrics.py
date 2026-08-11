import pytest
import base64
import uuid
import json
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from datetime import datetime, timezone

from backend.app.models import Dossier, DossierFinding, WorkflowExecutionMetric
from backend.app.services.workflow import compile_diligence_workflow
from backend.app.schemas import DossierMetricsResponse
from tests.test_integration import AsyncTestSession

def test_workflow_metrics_instrumentation():
    """
    Verifies that running the LangGraph workflow properly creates execution metrics,
    timing summaries, token counts, and estimates. Tests aggregation and isolation.
    """
    with AsyncTestSession() as ts:
        # 1. Setup Test Dossier and Finding
        async def create_dossier():
            async with ts.SessionLocal() as session:
                d = Dossier(name="Metrics Target Dossier", status="pending")
                session.add(d)
                await session.flush()
                
                f = DossierFinding(
                    dossier_id=d.id,
                    question="Standard cap table?",
                    status="pending",
                    review_status="not_required",
                    workflow_thread_id=str(uuid.uuid4())
                )
                session.add(f)
                
                # Ingest a sample document chunk to satisfy retrieval
                from backend.app.services.ingestion import IngestionService
                ingest = IngestionService(session)
                await ingest.ingest_document("test_cap.txt", b"Standard cap table information: John Doe owns 52% of Acme.")
                
                # Ingest a sample document containing malformed_json_trigger to trigger failing LLM run
                await ingest.ingest_document("test_fail.txt", b"This is a malformed_json_trigger mock document text context details.")
                
                await session.commit()
                return str(d.id), str(f.id)

        d_id, f_id = ts.run(create_dossier())

        # 2. Run Workflow and Verify Metrics
        async def run_workflow_and_verify():
            async with ts.SessionLocal() as session:
                # Retrieve finding
                res = await session.execute(
                    select(DossierFinding).where(DossierFinding.id == uuid.UUID(f_id))
                )
                finding = res.scalar()
                
                # Execute compiled workflow
                workflow = compile_diligence_workflow(session.bind)
                config = {
                    "configurable": {
                        "thread_id": finding.workflow_thread_id,
                        "db": session,
                        "dossier_id": uuid.UUID(d_id),
                        "finding_id": finding.id
                    }
                }
                initial_state = {
                    "question": finding.question,
                    "normalized_question": "",
                    "retrieved_evidence": [],
                    "supporting_evidence": [],
                    "contradicting_evidence": [],
                    "status": "pending",
                    "draft_answer": "",
                    "citations": [],
                    "confidence": 0.0,
                    "reasoning_summary": "",
                    "review_required": False,
                    "errors": None
                }
                
                await workflow.ainvoke(initial_state, config)
                await session.commit()

                # Verify metrics exist in the DB
                res_m = await session.execute(
                    select(WorkflowExecutionMetric)
                    .where(WorkflowExecutionMetric.finding_id == finding.id)
                )
                metrics = res_m.scalars().all()
                assert len(metrics) > 0
                
                # Check properties on query_analysis stage
                qa_metric = next((m for m in metrics if m.stage_name == "query_analysis"), None)
                assert qa_metric is not None
                assert qa_metric.status == "success"
                assert qa_metric.duration_ms >= 0
                assert qa_metric.error_message is None
                
                # Check token and cost estimates on answer_generation stage
                ag_metric = next((m for m in metrics if m.stage_name == "answer_generation"), None)
                assert ag_metric is not None
                assert ag_metric.status == "success"
                assert ag_metric.input_tokens > 0
                assert ag_metric.output_tokens > 0
                assert ag_metric.model_name == "mock-model"
                assert ag_metric.provider_name == "mock-provider"
                assert ag_metric.estimated_cost is not None
                assert ag_metric.estimated_cost >= 0.0

        ts.run(run_workflow_and_verify())

        # 3. Test failed node logging
        async def run_failing_workflow_and_verify():
            async with ts.SessionLocal() as session:
                f_fail = DossierFinding(
                    dossier_id=uuid.UUID(d_id),
                    question="malformed_json_trigger",
                    status="pending",
                    review_status="not_required",
                    workflow_thread_id=str(uuid.uuid4())  # unique thread ID
                )
                session.add(f_fail)
                await session.flush()

                workflow = compile_diligence_workflow(session.bind)
                config = {
                    "configurable": {
                        "thread_id": f_fail.workflow_thread_id,
                        "db": session,
                        "dossier_id": uuid.UUID(d_id),
                        "finding_id": f_fail.id
                    }
                }
                initial_state = {
                    "question": "malformed_json_trigger",
                    "normalized_question": "malformed_json_trigger",
                    "retrieved_evidence": [],
                    "supporting_evidence": [],
                    "contradicting_evidence": [],
                    "status": "pending",
                    "draft_answer": "",
                    "citations": [],
                    "confidence": 0.0,
                    "reasoning_summary": "",
                    "review_required": False,
                    "errors": None
                }
                
                await workflow.ainvoke(initial_state, config)
                await session.commit()

                res_m = await session.execute(
                    select(WorkflowExecutionMetric)
                    .where(WorkflowExecutionMetric.finding_id == f_fail.id)
                )
                metrics = res_m.scalars().all()
                fail_metric = next((m for m in metrics if m.stage_name == "answer_generation"), None)
                assert fail_metric is not None
                assert fail_metric.status == "failed"
                assert "LLM returned non-JSON string" in fail_metric.error_message

        ts.run(run_failing_workflow_and_verify())

        # 4. Test GET Metrics API and cross-dossier isolation
        def verify_api_and_isolation():
            # Setup Dossier B (isolated)
            async def setup_b():
                async with ts.SessionLocal() as session:
                    db = Dossier(name="Metrics Isolated Dossier B", status="pending")
                    session.add(db)
                    await session.flush()
                    
                    fb = DossierFinding(
                        dossier_id=db.id,
                        question="Isolated question?",
                        status="pending",
                        review_status="not_required",
                        workflow_thread_id=str(uuid.uuid4())
                    )
                    session.add(fb)
                    await session.flush()
                    
                    # Insert a metric for Dossier B
                    mb = WorkflowExecutionMetric(
                        dossier_id=db.id,
                        finding_id=fb.id,
                        run_id="run-b",
                        stage_name="query_analysis",
                        status="success",
                        start_time=datetime.now(timezone.utc),
                        end_time=datetime.now(timezone.utc),
                        duration_ms=150,
                        input_tokens=10,
                        output_tokens=20,
                        estimated_cost=0.0001
                    )
                    session.add(mb)
                    await session.commit()
                    return str(db.id)
            
            db_id = ts.run(setup_b())
            
            # Request Dossier A metrics using fastapi test client
            from fastapi.testclient import TestClient
            from backend.app.main import app
            from backend.app.database import get_db
            
            async def override_get_db():
                async with ts.SessionLocal() as session:
                    yield session
            app.dependency_overrides[get_db] = override_get_db
            
            client = TestClient(app)
            
            resp = client.get(f"/api/v1/dossiers/{d_id}/metrics")
            assert resp.status_code == 200
            data = resp.json()
            
            # Aggregation checks
            assert data["dossier_id"] == d_id
            assert data["total_duration_ms"] > 0
            assert data["total_input_tokens"] > 0
            assert data["total_output_tokens"] > 0
            assert len(data["stages"]) > 0
            
            # Cross-dossier isolation checks
            stage_names = [s["stage_name"] for s in data["stages"]]
            assert "run-b" not in [s.get("run_id") for s in data["stages"]]
            
            # Request non-existent dossier metrics
            fake_id = str(uuid.uuid4())
            resp_bad = client.get(f"/api/v1/dossiers/{fake_id}/metrics")
            assert resp_bad.status_code == 404
            
        verify_api_and_isolation()

        # 5. Test instrumentation failure bypass (does not crash the workflow)
        async def verify_bypass():
            async with ts.SessionLocal() as session:
                workflow = compile_diligence_workflow(session.bind)
                
                config_empty = {"configurable": {"thread_id": "bypass_thread"}}
                initial_state = {
                    "question": "Bypass question?",
                    "normalized_question": "",
                    "retrieved_evidence": [],
                    "supporting_evidence": [],
                    "contradicting_evidence": [],
                    "status": "pending",
                    "draft_answer": "",
                    "citations": [],
                    "confidence": 0.0,
                    "reasoning_summary": "",
                    "review_required": False,
                    "errors": None
                }
                
                await workflow.ainvoke(initial_state, config_empty)
                
        ts.run(verify_bypass())
