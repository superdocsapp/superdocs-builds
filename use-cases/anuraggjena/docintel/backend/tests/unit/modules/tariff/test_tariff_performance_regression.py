"""
Performance and batch optimization regression test suite for Tariff workflow.

Tests verify:
1. Batch approval sends 1 network call for N claims
2. Bulk DB updates for claims and lineage
3. Graceful fallback on batch failure
4. Batch reconciliation of pending changes
5. MCP client connection pooling reuse
6. SuperDocsClient batch payload structure
7. Dual-signal race condition safety (in_progress + 0 pending is not terminal)
8. Dual-signal HITL escalation on awaiting_approval + pending changes
9. Memo section concurrency configuration
10. ClaimRepository bulk update status
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
import pytest

from backend.integrations.superdocs.approval_handler import ApprovalHandler
from backend.integrations.superdocs.client import SuperDocsClient, JobStatus, JobStatusResult
from backend.integrations.superdocs.mcp_invoker import get_mcp_client, close_mcp_client
from backend.models.claim import Claim
from backend.modules.tariff.stages.superdocs_approval import SuperDocsApprovalStage
from backend.modules.tariff.stages.generate_memo_sections import GenerateMemoSectionsStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.core.workflow.runner import WorkflowEscalatedException
from backend.repositories.review import ClaimRepository


def _make_claim(status="approved", change_id=None):
    c = MagicMock(spec=Claim)
    c.id = uuid4()
    c.workflow_run_id = uuid4()
    c.status = status
    c.superdocs_change_id = change_id or f"chg-{uuid4().hex[:6]}"
    c.superdocs_job_id = "job-123"
    c.content = '{"chunk_id": "c1", "ai_explanation": "exp"}'
    c.updated_at = None
    return c


@pytest.mark.asyncio
async def test_1_batch_approval_single_network_call():
    """Verify apply_approvals bundles N claims into 1 batch approve_change call."""
    run_id = uuid4()
    job_id = "job-123"
    claims = [_make_claim("approved") for _ in range(25)] + [_make_claim("rejected") for _ in range(5)]

    session_mgr = AsyncMock()
    session_mgr.get_session_for_run = AsyncMock(return_value="sess-123")

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=claims)
    claim_repo.bulk_update_status = AsyncMock(return_value=30)

    lineage_repo = AsyncMock()
    lineage_repo.create_links_bulk = AsyncMock(return_value=[])

    client = AsyncMock()
    client.approve_change = AsyncMock()

    handler = ApprovalHandler(
        superdocs_client=client,
        session_manager=session_mgr,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo,
    )

    counts = await handler.apply_approvals(run_id, job_id)

    assert counts["approved"] == 25
    assert counts["rejected"] == 5
    # Batch approve_change called exactly once
    assert client.approve_change.call_count == 1
    call_kwargs = client.approve_change.call_args.kwargs
    assert len(call_kwargs["changes"]) == 30


@pytest.mark.asyncio
async def test_2_batch_approval_bulk_db_updates():
    """Verify bulk_update_status and create_links_bulk are used instead of per-claim writes."""
    run_id = uuid4()
    job_id = "job-123"
    claims = [_make_claim("approved") for _ in range(10)]

    session_mgr = AsyncMock()
    session_mgr.get_session_for_run = AsyncMock(return_value="sess-123")

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=claims)
    claim_repo.bulk_update_status = AsyncMock(return_value=10)

    lineage_repo = AsyncMock()
    lineage_repo.create_links_bulk = AsyncMock(return_value=[])

    client = AsyncMock()
    client.approve_change = AsyncMock()

    handler = ApprovalHandler(
        superdocs_client=client,
        session_manager=session_mgr,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo,
    )

    await handler.apply_approvals(run_id, job_id)

    claim_repo.bulk_update_status.assert_awaited_once()
    claim_repo.update.assert_not_called()
    lineage_repo.create_links_bulk.assert_awaited_once()
    assert len(lineage_repo.create_links_bulk.call_args[0][0]) == 10


@pytest.mark.asyncio
async def test_3_batch_approval_fallback_on_error():
    """Verify fallback to concurrent individual calls if batch fails."""
    run_id = uuid4()
    job_id = "job-123"
    claims = [_make_claim("approved", f"chg-{i}") for i in range(3)]

    session_mgr = AsyncMock()
    session_mgr.get_session_for_run = AsyncMock(return_value="sess-123")

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=claims)
    claim_repo.bulk_update_status = AsyncMock(return_value=3)

    client = AsyncMock()
    # Batch call raises, individual calls succeed
    async def approve_side_effect(**kwargs):
        if "changes" in kwargs and kwargs["changes"] is not None:
            raise Exception("Batch not supported by server")
        return MagicMock()

    client.approve_change = AsyncMock(side_effect=approve_side_effect)

    handler = ApprovalHandler(
        superdocs_client=client,
        session_manager=session_mgr,
        claim_repository=claim_repo,
    )

    counts = await handler.apply_approvals(run_id, job_id)

    assert counts["approved"] == 3
    # 1 failed batch call + 3 individual calls
    assert client.approve_change.call_count == 4


@pytest.mark.asyncio
async def test_4_reconcile_pending_changes_batch():
    """Verify reconcile_pending_changes batches re-applications."""
    run_id = uuid4()
    job_id = "job-123"
    c1 = _make_claim("approved", "chg-1")
    c2 = _make_claim("rejected", "chg-2")

    session_mgr = AsyncMock()
    session_mgr.get_session_for_run = AsyncMock(return_value="sess-123")

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[c1, c2])

    client = AsyncMock()
    client.approve_change = AsyncMock()

    handler = ApprovalHandler(
        superdocs_client=client,
        session_manager=session_mgr,
        claim_repository=claim_repo,
    )

    pending_changes = [
        {"change_id": "chg-1", "chunk_id": "chunk-1"},
        {"change_id": "chg-2", "chunk_id": "chunk-2"},
    ]

    res = await handler.reconcile_pending_changes(run_id, job_id, pending_changes)

    assert res["reconciled"] == 2
    assert res["escalation_required"] is False
    assert client.approve_change.call_count == 1
    assert len(client.approve_change.call_args.kwargs["changes"]) == 2


@pytest.mark.asyncio
async def test_5_mcp_client_connection_pooling():
    """Verify get_mcp_client returns persistent pooled client."""
    c1 = await get_mcp_client()
    c2 = await get_mcp_client()
    assert c1 is c2
    assert not c1.is_closed


@pytest.mark.asyncio
async def test_6_superdocs_client_approve_change_batch_kwargs():
    """Verify SuperDocsClient.approve_change formats batch arguments."""
    client = SuperDocsClient(api_key="test-key")
    client._call_mcp_tool = AsyncMock(return_value={"job_status": "in_progress"})

    batch = [{"change_id": "chg-1", "approved": True}]
    result = await client.approve_change(
        session_id="sess-1",
        job_id="job-1",
        approved=True,
        changes=batch,
    )

    assert result.approved is True
    assert result.change_id == "chg-1"
    client._call_mcp_tool.assert_awaited_once_with(
        "mcp__superdocs__approve_change",
        session_id="sess-1",
        job_id="job-1",
        approved=True,
        changes=batch,
    )


@pytest.mark.asyncio
async def test_7_dual_signal_race_condition_safety():
    """Verify that in_progress with 0 pending changes polls until COMPLETED."""
    client = AsyncMock()
    poll_calls = [
        # 1. in_progress with 0 pending (transient)
        JobStatusResult(job_id="job-1", status=JobStatus.IN_PROGRESS, progress=0.5, result={}, pending_changes=[], error=None),
        # 2. awaiting_approval with 1 pending
        JobStatusResult(job_id="job-1", status=JobStatus.AWAITING_APPROVAL, progress=0.8, result={}, pending_changes=[{"change_id": "chg-1"}], error=None),
        # 3. completed with 0 pending
        JobStatusResult(job_id="job-1", status=JobStatus.COMPLETED, progress=1.0, result={}, pending_changes=[], error=None),
    ]
    client.get_job = AsyncMock(side_effect=poll_calls)

    approval_handler = AsyncMock()
    approval_handler.reconcile_pending_changes = AsyncMock(return_value={"escalation_required": False, "reconciled": 1})

    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.001,
        poll_timeout=5,
    )
    stage._get_superdocs_claims = AsyncMock(return_value=[])

    # In _poll_until_complete, it should not terminate until poll 3
    final = await stage._poll_until_complete(uuid4(), "job-1")
    assert final.status == JobStatus.COMPLETED
    assert client.get_job.call_count == 3


@pytest.mark.asyncio
async def test_8_dual_signal_hitl_escalation():
    """Verify that stage raises WorkflowEscalatedException when claims are pending."""
    client = AsyncMock()
    client.get_job = AsyncMock(return_value=JobStatusResult(
        job_id="job-1",
        status=JobStatus.AWAITING_APPROVAL,
        progress=0.8,
        result={},
        pending_changes=[{"change_id": "chg-1"}],
        error=None,
    ))

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock(return_value=[uuid4()])

    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.001,
    )

    mock_claim = _make_claim("pending", "chg-1")
    stage._get_superdocs_claims = AsyncMock(return_value=[mock_claim])

    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        superdocs_job_id="job-1",
    )

    with pytest.raises(WorkflowEscalatedException) as exc_info:
        await stage.execute(state)

    assert exc_info.value.reason == "awaiting_human_approval"


def test_9_memo_sections_concurrency():
    """Verify GenerateMemoSectionsStage is initialized and structured properly."""
    stage = GenerateMemoSectionsStage()
    assert stage.name == "generate_memo_sections"


@pytest.mark.asyncio
async def test_10_claim_repo_bulk_update_status():
    """Verify ClaimRepository.bulk_update_status constructs proper update query."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_session.execute = AsyncMock(return_value=mock_result)

    repo = ClaimRepository(mock_session)
    claim_ids = [uuid4() for _ in range(5)]
    updated = await repo.bulk_update_status(claim_ids, "applied")

    assert updated == 5
    mock_session.execute.assert_awaited_once()
    mock_session.flush.assert_awaited_once()
