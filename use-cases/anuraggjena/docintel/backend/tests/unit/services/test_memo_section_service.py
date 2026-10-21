import json
import pytest

from backend.repositories.memo_section import MemoSectionRepository
from backend.repositories.review import ClaimRepository
from backend.repositories.workflow import WorkflowRepository, WorkflowRunRepository
from backend.services.memo_section import MemoSectionService


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
    return await run_repo.create(
        workspace_id=test_workspace.id,
        workflow_id=workflow.id,
        status="running",
        workflow_version="1.0.0",
        created_by="unit-test",
        version_number=1,
    )


@pytest.mark.asyncio
async def test_create_section_creates_mirrored_claim(db_session, test_workspace):
    service = MemoSectionService(
        MemoSectionRepository(db_session),
        ClaimRepository(db_session),
    )
    run = await _create_workflow_run(db_session, test_workspace)
    section, claim = await service.create_section_with_claim(
        workflow_run_id=run.id,
        section_type="product_description",
        title="Product Description",
        section_order=3,
        content="A stainless steel widget.",
        analyst_reasoning="Based on spec sheet paragraph 2.",
        source_attribution=[],
    )
    assert section.id is not None
    assert claim.claim_type == "memo_section"
    claim_data = json.loads(claim.content)
    assert claim_data["memo_section_id"] == str(section.id)
    assert claim_data["section_type"] == "product_description"
