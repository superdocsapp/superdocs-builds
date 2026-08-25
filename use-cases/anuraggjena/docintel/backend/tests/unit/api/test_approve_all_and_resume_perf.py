"""Unit tests verifying Tariff workflow post-approval resume performance and SSE updates."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from backend.api.v1.runs import approve_all_run_claims
from backend.services.workflow import WorkflowService
from backend.models.workflow import WorkflowRun, Workflow
from backend.models.claim import Claim
from backend.models.review import Review
from backend.models.memo_section import MemoSection
from backend.integrations.superdocs.approval_handler import ApprovalHandler
from backend.integrations.superdocs.client import JobStatus, JobStatusResult
from backend.modules.tariff.stages.superdocs_approval import SuperDocsApprovalStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.api.v1.stream import workflow_event_generator


@pytest.mark.asyncio
async def test_approve_all_run_claims_resumes_waiting_run():
    workspace_id = uuid4()
    run_id = uuid4()

    run = MagicMock(spec=WorkflowRun)
    run.id = run_id
    run.workspace_id = workspace_id
    run.status = "waiting"

    claim1 = MagicMock(spec=Claim)
    claim1.id = uuid4()
    claim1.status = "pending"

    memo1 = MagicMock(spec=MemoSection)
    memo1.id = uuid4()
    memo1.status = "pending"

    review1 = MagicMock(spec=Review)
    review1.id = uuid4()
    review1.workflow_run_id = run_id
    review1.status = "pending"

    claim_repo = AsyncMock()
    claim_repo.list_by_run = AsyncMock(return_value=[claim1])
    claim_repo.bulk_approve_for_run = AsyncMock(return_value=1)

    memo_repo = AsyncMock()
    memo_repo.list_by_run = AsyncMock(return_value=[memo1])
    memo_repo.update = AsyncMock()

    review_repo = AsyncMock()
    review_repo.list_by_workspace = AsyncMock(return_value=[review1])
    review_repo.update = AsyncMock()

    service = AsyncMock(spec=WorkflowService)
    service.get_run = AsyncMock(return_value=run)
    service.resume_run = AsyncMock(return_value=True)

    db = AsyncMock()

    with patch("backend.repositories.review.ClaimRepository", return_value=claim_repo), \
         patch("backend.repositories.memo_section.MemoSectionRepository", return_value=memo_repo), \
         patch("backend.repositories.review.ReviewRepository", return_value=review_repo):

        result = await approve_all_run_claims(
            workspace_id=workspace_id,
            run_id=run_id,
            run=run,
            service=service,
            db=db,
        )

    assert result["approved_count"] == 1
    assert result["total_claims"] == 1
    assert result["resumed"] is True
    assert result["run_id"] == str(run_id)
    db.commit.assert_awaited_once()
    service.resume_run.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
async def test_workflow_service_resume_run():
    run_id = uuid4()
    workflow_id = uuid4()

    run = MagicMock(spec=WorkflowRun)
    run.id = run_id
    run.workflow_id = workflow_id

    wf = MagicMock(spec=Workflow)
    wf.id = workflow_id
    wf.slug = "tariff_classification"

    run_repo = AsyncMock()
    run_repo.get_by_id = AsyncMock(return_value=run)

    wf_repo = AsyncMock()
    wf_repo.get_by_id = AsyncMock(return_value=wf)

    mock_tm = AsyncMock()
    mock_tm.resume_workflow = AsyncMock()

    service = WorkflowService(
        workflow_repository=wf_repo,
        run_repository=run_repo,
        stage_repository=AsyncMock(),
        document_repository=AsyncMock(),
        storage=MagicMock(),
    )

    with patch("backend.core.workflow.task_manager.get_task_manager", return_value=mock_tm):
        resumed = await service.resume_run(run_id)

    assert resumed is True
    mock_tm.resume_workflow.assert_awaited_once_with(run_id, "tariff_classification")


@pytest.mark.asyncio
async def test_approval_handler_apply_approvals_concurrent():
    run_id = uuid4()
    job_id = "job-123"
    session_id = "sess-123"

    claim1 = MagicMock(spec=Claim)
    claim1.id = uuid4()
    claim1.status = "approved"
    claim1.superdocs_change_id = "change-1"

    claim2 = MagicMock(spec=Claim)
    claim2.id = uuid4()
    claim2.status = "approved"
    claim2.superdocs_change_id = "change-2"

    claim3 = MagicMock(spec=Claim)
    claim3.id = uuid4()
    claim3.status = "rejected"
    claim3.superdocs_change_id = "change-3"

    session_mgr = AsyncMock()
    session_mgr.get_session_for_run = AsyncMock(return_value=session_id)

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[claim1, claim2, claim3])
    claim_repo.update = AsyncMock()

    client = AsyncMock()
    client.approve_change = AsyncMock()

    handler = ApprovalHandler(
        superdocs_client=client,
        session_manager=session_mgr,
        claim_repository=claim_repo,
    )

    counts = await handler.apply_approvals(run_id, job_id)

    assert counts["approved"] == 2
    assert counts["rejected"] == 1
    assert client.approve_change.await_count == 1
    call_kwargs = client.approve_change.call_args.kwargs
    assert len(call_kwargs["changes"]) == 3


@pytest.mark.asyncio
async def test_superdocs_approval_stage_completes_without_stall_on_empty_pending_changes():
    run_id = uuid4()
    job_id = "job-456"

    # Initial get_job returns awaiting_approval with changes
    initial_job = JobStatusResult(
        job_id=job_id,
        status=JobStatus.AWAITING_APPROVAL,
        progress=0.5,
        result=None,
        pending_changes=[{"id": "ch-1"}],
        error=None,
    )
    # After approvals, polling returns awaiting_approval with NO pending changes (finished)
    post_approval_job = JobStatusResult(
        job_id=job_id,
        status=JobStatus.COMPLETED,
        progress=1.0,
        result="Done",
        pending_changes=[],
        error=None,
    )

    client = AsyncMock()
    client.get_job = AsyncMock(side_effect=[initial_job, post_approval_job])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})

    existing_claim = MagicMock(spec=Claim)
    existing_claim.id = uuid4()
    existing_claim.claim_type = "superdocs_change"
    existing_claim.status = "approved"

    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.01,
        poll_timeout=2,
    )

    mock_claim_repo = AsyncMock()
    mock_claim_repo.list_by_run = AsyncMock(return_value=[existing_claim])

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_claim_repo):
        state = TariffWorkflowState(
            workflow_run_id=str(run_id),
            workspace_id=str(uuid4()),
            document_id=str(uuid4()),
            superdocs_job_id=job_id,
            superdocs_session_id="sess-456",
        )
        result = await stage.execute(state)

    assert result["superdocs_approval_completed"] is True
    assert result["approved_count"] == 1
    assert result["rejected_count"] == 0


@pytest.mark.asyncio
async def test_stream_workflow_event_generator_emits_stage_status_changes():
    run_id = uuid4()

    run_obj = MagicMock(spec=WorkflowRun)
    run_obj.id = run_id
    run_obj.status = "completed"
    run_obj.current_stage = None

    stage_obj = MagicMock()
    stage_obj.id = uuid4()
    stage_obj.stage_name = "superdocs_approval"
    stage_obj.status = "completed"
    stage_obj.started_at = datetime.now(timezone.utc)
    stage_obj.completed_at = datetime.now(timezone.utc)
    stage_obj.execution_time_ms = 120
    stage_obj.error_message = None

    mock_run_repo = AsyncMock()
    mock_run_repo.get_by_id = AsyncMock(return_value=run_obj)

    mock_stage_repo = AsyncMock()
    mock_stage_repo.list_by_run = AsyncMock(return_value=[stage_obj])

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.database.async_session_maker", return_value=mock_db), \
         patch("backend.api.v1.stream.WorkflowRunRepository", return_value=mock_run_repo), \
         patch("backend.api.v1.stream.WorkflowStageRepository", return_value=mock_stage_repo):

        events = []
        async for event in workflow_event_generator(run_id, poll_interval=0.01, timeout=1.0):
            events.append(event)

    assert any("event: stage_update" in e for e in events)
    assert any("event: run_status" in e for e in events)
    assert any("event: done" in e for e in events)
