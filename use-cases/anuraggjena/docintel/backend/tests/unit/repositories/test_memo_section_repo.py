import pytest

from backend.repositories.memo_section import MemoSectionRepository
from backend.repositories.workflow import WorkflowRepository, WorkflowRunRepository


async def _create_workflow_run(db_session, test_workspace):
    workflow_repo = WorkflowRepository(db_session)
    workflow = await workflow_repo.get_by_slug("tariff_classification")
    if not workflow:
        workflow = await workflow_repo.create(
            name="Tariff Classification",
            slug="tariff_classification",
            description="Test workflow",
            current_version="1.0.0",
        )
    run_repo = WorkflowRunRepository(db_session)
    run = await run_repo.create(
        workspace_id=test_workspace.id,
        workflow_id=workflow.id,
        status="running",
        workflow_version="1.0.0",
        created_by="unit-test",
        version_number=1,
    )
    return run


@pytest.mark.asyncio
async def test_create_and_list_by_run(db_session, test_workspace):
    repo = MemoSectionRepository(db_session)
    run = await _create_workflow_run(db_session, test_workspace)
    await repo.create(
        workflow_run_id=run.id,
        section_type="product_overview",
        title="Product Overview",
        section_order=2,
        content="Test content",
        status="pending",
    )
    sections = await repo.list_by_run(run.id)
    assert len(sections) == 1
    assert sections[0].section_type == "product_overview"


@pytest.mark.asyncio
async def test_get_by_run_and_type(db_session, test_workspace):
    repo = MemoSectionRepository(db_session)
    run = await _create_workflow_run(db_session, test_workspace)
    await repo.create(
        workflow_run_id=run.id,
        section_type="classification_analysis",
        title="Classification Analysis",
        section_order=9,
        content="Analysis text",
    )
    found = await repo.get_by_run_and_type(run.id, "classification_analysis")
    assert found is not None
    assert found.content == "Analysis text"
