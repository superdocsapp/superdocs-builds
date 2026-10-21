"""Unit tests for ReviewRepository."""
import pytest
from uuid import uuid4
from backend.repositories.review import ReviewRepository
from backend.models.review import Review
from backend.models.workspace import Workspace
from backend.models.workflow import Workflow, WorkflowRun


@pytest.mark.asyncio
async def test_review_repository_list_by_run_and_workflow_run(db_session, test_user):
    """Test ReviewRepository.list_by_run, list_by_workflow_run, and get_by_workflow_run."""
    repo = ReviewRepository(db_session)

    # Create workspace, workflow, and workflow runs
    ws = Workspace(name="Test Review WS", owner_user_id=test_user.id)
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

    # Create reviews for run 1
    rev1 = Review(
        workflow_run_id=run_1.id,
        workspace_id=ws.id,
        status="in_review",
    )
    rev2 = Review(
        workflow_run_id=run_1.id,
        workspace_id=ws.id,
        status="approved",
    )
    # Create review for run 2
    rev3 = Review(
        workflow_run_id=run_2.id,
        workspace_id=ws.id,
        status="pending",
    )
    db_session.add_all([rev1, rev2, rev3])
    await db_session.flush()

    # Test list_by_run
    run1_reviews = await repo.list_by_run(run_1.id)
    assert len(run1_reviews) == 2
    assert {r.id for r in run1_reviews} == {rev1.id, rev2.id}

    # Test list_by_workflow_run
    run1_wf_reviews = await repo.list_by_workflow_run(run_1.id)
    assert len(run1_wf_reviews) == 2

    # Test get_by_workflow_run
    latest_review = await repo.get_by_workflow_run(run_1.id)
    assert latest_review is not None
    assert latest_review.id in {rev1.id, rev2.id}

    # Test run 2 lookup
    run2_reviews = await repo.list_by_run(run_2.id)
    assert len(run2_reviews) == 1
    assert run2_reviews[0].id == rev3.id

    # Test non-existent run
    empty_reviews = await repo.list_by_run(uuid4())
    assert empty_reviews == []
