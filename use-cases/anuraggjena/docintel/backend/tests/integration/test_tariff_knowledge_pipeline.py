import pytest
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.database import get_db
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.models.workflow import WorkflowRun
from backend.models.knowledge import KnowledgeEntry
from backend.core.knowledge.engine import KnowledgeEngine
from backend.core.knowledge.stages import KnowledgeStoreStage
from backend.repositories.knowledge import KnowledgeRepository
from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim


@pytest.mark.asyncio
async def test_tariff_knowledge_store_pipeline_integration(db_session):
    session = db_session

    user_id = uuid4()
    user = User(
        id=user_id,
        email=f"knowledge-test-{user_id}@example.com",
        password_hash="$2b$12$fakehashfakehashfakehashfakehashfakehashfakehashfake",
        name="Knowledge Test User"
    )
    session.add(user)
    await session.commit()

    workspace_id = uuid4()
    workspace = Workspace(
        id=workspace_id,
        name="Tariff Knowledge Workspace",
        owner_user_id=user_id,
        workflow_type="tariff_classification"
    )
    session.add(workspace)
    await session.commit()

    from backend.models.workflow import Workflow
    from sqlalchemy import select
    result = await session.execute(select(Workflow).where(Workflow.slug == "tariff_classification"))
    workflow = result.scalar_one_or_none()
    if not workflow:
        workflow = Workflow(
            id=uuid4(),
            name="Tariff Classification",
            slug=f"tariff_classification_{uuid4().hex[:6]}"
        )
        session.add(workflow)
        await session.commit()

    run_id = uuid4()
    workflow_run = WorkflowRun(
        id=run_id,
        workspace_id=workspace_id,
        workflow_id=workflow.id,
        workflow_version="1.0.0",
        created_by="test_user",
        status="completed"
    )
    session.add(workflow_run)
    await session.commit()

    repo = KnowledgeRepository(session)
    engine = KnowledgeEngine(repo)
    stage = KnowledgeStoreStage(engine=engine, workflow_type="tariff_classification")

    state = TariffWorkflowState(
        workspace_id=str(workspace_id),
        workflow_run_id=str(run_id),
        extracted_claims=[
            TariffClaim(
                hs_code="8517.62.00",
                description="Cellular Router / Gateway",
                duty_rate="Free",
                notes="Classified under Heading 8517 based on GRI 1 and GRI 6"
            )
        ],
        generated_sections={
            "executive_summary": "The AeroLink X7 is classified under HS code 8517.62.00 as a machine for the transmission or reception of voice, images or other data.",
            "recommended_classification": "Recommended HS code: 8517.62.00, applicable duty rate: 0% (Duty Free).",
            "classification_analysis": "Principal function is cellular routing and data transmission under Chapter 85."
        }
    )

    result = await stage.execute(state)
    assert result["knowledge_stored"] >= 3

    async def override_get_db():
        yield session

    from backend.api.deps import require_workspace_access
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_workspace_access] = lambda: workspace

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res_all = await client.get(f"/api/v1/knowledge/workspace/{workspace_id}")
            assert res_all.status_code == 200
            entries_all = res_all.json()
            assert len(entries_all) >= 3

            res_tariff = await client.get(f"/api/v1/knowledge/workspace/{workspace_id}?workflow_type=tariff_classification")
            assert res_tariff.status_code == 200
            entries_tariff = res_tariff.json()
            assert len(entries_tariff) >= 3

            claim_entries = [e for e in entries_tariff if e["entry_type"] == "claim"]
            summary_entries = [e for e in entries_tariff if e["entry_type"] == "summary"]
            full_entries = [e for e in entries_tariff if e["entry_type"] == "full_output"]

            assert len(claim_entries) >= 1
            assert "8517.62.00" in claim_entries[0]["content"]

            assert len(summary_entries) >= 1
            assert "AeroLink X7" in summary_entries[0]["content"]

            assert len(full_entries) >= 1
            assert "Executive Summary" in full_entries[0]["content"]

    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete
        await session.execute(delete(KnowledgeEntry).where(KnowledgeEntry.workspace_id == workspace_id))
        await session.delete(workflow_run)
        await session.delete(workspace)
        await session.delete(user)
        await session.commit()
