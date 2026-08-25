"""Unit tests for ClaimRepository."""
import pytest
from uuid import uuid4
from backend.repositories.review import ClaimRepository
from backend.models.claim import Claim
from backend.models.workspace import Workspace
from backend.models.workflow import Workflow, WorkflowRun


@pytest.mark.asyncio
async def test_list_by_run(db_session, test_user):
    """Test list_by_run method."""
    repo = ClaimRepository(db_session)

    # Create workspace, workflow, and workflow runs
    ws = Workspace(name="Test WS", owner_user_id=test_user.id)
    wf = Workflow(name="Tariff", slug=f"tariff-{uuid4().hex[:8]}")
    db_session.add_all([ws, wf])
    await db_session.flush()

    run_1 = WorkflowRun(
        workspace_id=ws.id,
        workflow_id=wf.id,
        workflow_version="1.0.0",
        created_by=str(test_user.id),
        status="running",
    )
    run_2 = WorkflowRun(
        workspace_id=ws.id,
        workflow_id=wf.id,
        workflow_version="1.0.0",
        created_by=str(test_user.id),
        status="running",
    )
    db_session.add_all([run_1, run_2])
    await db_session.flush()

    run_id_1 = run_1.id
    run_id_2 = run_2.id

    # Create claims for run 1
    claim1 = Claim(
        workflow_run_id=run_id_1,
        claim_type="tariff_code",
        content="1234.56.78",
        status="pending",
        source_stage="extract"
    )
    claim2 = Claim(
        workflow_run_id=run_id_1,
        claim_type="duty_rate",
        content="5%",
        status="approved",
        source_stage="extract"
    )

    # Create claim for run 2
    claim3 = Claim(
        workflow_run_id=run_id_2,
        claim_type="tariff_code",
        content="9876.54.32",
        status="pending",
        source_stage="extract"
    )

    db_session.add_all([claim1, claim2, claim3])
    await db_session.commit()

    # Test list_by_run for run 1
    claims = await repo.list_by_run(run_id_1)
    assert len(claims) == 2
    assert all(c.workflow_run_id == run_id_1 for c in claims)
    assert claims[0].created_at <= claims[1].created_at

    # Test list_by_run for run 2
    claims = await repo.list_by_run(run_id_2)
    assert len(claims) == 1
    assert claims[0].workflow_run_id == run_id_2

    # Test empty result
    claims = await repo.list_by_run(uuid4())
    assert len(claims) == 0


@pytest.mark.asyncio
async def test_bulk_approve_for_run(db_session, test_user):
    """Test bulk approving pending claims for a workflow run."""
    repo = ClaimRepository(db_session)

    ws = Workspace(name="Test WS 2", owner_user_id=test_user.id)
    wf = Workflow(name="Tariff 2", slug=f"tariff2-{uuid4().hex[:8]}")
    db_session.add_all([ws, wf])
    await db_session.flush()

    run = WorkflowRun(
        workspace_id=ws.id,
        workflow_id=wf.id,
        workflow_version="1.0.0",
        created_by=str(test_user.id),
        status="running",
    )
    db_session.add(run)
    await db_session.flush()

    run_id = run.id

    claim1 = Claim(
        workflow_run_id=run_id,
        claim_type="memo_section",
        content="section 1",
        status="pending"
    )
    claim2 = Claim(
        workflow_run_id=run_id,
        claim_type="memo_section",
        content="section 2",
        status="pending"
    )
    claim3 = Claim(
        workflow_run_id=run_id,
        claim_type="memo_section",
        content="section 3",
        status="rejected"
    )

    db_session.add_all([claim1, claim2, claim3])
    await db_session.commit()

    count = await repo.bulk_approve_for_run(run_id)
    assert count == 2

    # Fetch updated claims
    claims = await repo.list_by_run(run_id)
    statuses = {c.content: c.status for c in claims}
    assert statuses["section 1"] == "approved"
    assert statuses["section 2"] == "approved"
    assert statuses["section 3"] == "rejected"



