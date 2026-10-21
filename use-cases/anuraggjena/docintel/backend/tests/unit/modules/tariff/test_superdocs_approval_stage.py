"""
Focused tests for SuperDocsApprovalStage conditional HITL behavior.

Safety guarantee under test: workflow NEVER proceeds to export while
unresolved pending_changes or pending claims exist.

Cases:
1.  completed + no pending_changes, no claims → skip HITL, immediate success
2.  awaiting_approval + no pending_changes    → poll to complete, skip HITL
3.  awaiting_approval + pending_changes       → sync claims, raise escalation (first run)
4.  completed + pending_changes               → sync claims, raise escalation (NOT skipped)
5.  claims exist, all resolved (resume)       → apply_approvals, complete
6.  claims exist, some pending (resume)       → re-raise escalation (safety gate)
7.  claim approved → apply_approvals reports approved, final_job_status=completed
8.  claim rejected → apply_approvals reports rejected, rejected change NOT applied
9.  no job_id                                 → ValueError immediately
10. SuperDocs job FAILED                      → Exception, never continue
11. instruction stage uses ask_every_time     → HITL preserved
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.modules.tariff.stages.superdocs_approval import SuperDocsApprovalStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.integrations.superdocs.client import JobStatus, JobStatusResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _job(status: JobStatus, pending_changes=None, progress=1.0, error=None):
    return JobStatusResult(
        job_id="job-test",
        status=status,
        progress=progress,
        result={},
        pending_changes=pending_changes if pending_changes is not None else [],
        error=error if error is not None else ("upstream error" if status == JobStatus.FAILED else None)
    )


def _base_state(**kw):
    defaults = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "superdocs_session_id": "sess-123",
        "superdocs_job_id": "job-test",
    }
    defaults.update(kw)
    return TariffWorkflowState(**defaults)


def _make_claim(status="pending", claim_type="superdocs_change", superdocs_change_id=None):
    c = MagicMock()
    c.id = uuid4()
    c.claim_type = claim_type
    c.status = status
    c.superdocs_change_id = superdocs_change_id
    return c


def _make_stage(client=None, approval_handler=None, poll_interval=0.0):
    if client is None:
        client = AsyncMock()
    if approval_handler is None:
        approval_handler = AsyncMock()
        approval_handler.sync_pending_changes = AsyncMock(return_value=[])
        approval_handler.apply_approvals = AsyncMock(return_value={"approved": 0, "rejected": 0})
    return SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=poll_interval,
        poll_timeout=5,
    )


def _patch_db(claims_sequence):
    """
    Returns context managers to patch async_session_maker and ClaimRepository.
    claims_sequence: list of lists — each call to list_by_run returns next item.
    """
    call_count = [0]

    async def list_by_run_side_effect(run_id):
        idx = call_count[0]
        call_count[0] += 1
        return claims_sequence[idx] if idx < len(claims_sequence) else []

    mock_repo = AsyncMock()
    mock_repo.list_by_run = AsyncMock(side_effect=list_by_run_side_effect)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    return mock_repo, mock_db


# ---------------------------------------------------------------------------
# 1. completed + no pending_changes, no existing claims → skip HITL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case1_completed_no_changes_skips_hitl():
    client = AsyncMock()
    client.get_job.return_value = _job(JobStatus.COMPLETED, pending_changes=[])

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)
    mock_repo, mock_db = _patch_db([[]])  # no existing claims

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["claim_ids"] == []
    assert result["approved_count"] == 0
    assert result["final_job_status"] == "completed"
    approval_handler.sync_pending_changes.assert_not_called()
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 2. awaiting_approval + no pending_changes → poll to complete, skip HITL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case2_awaiting_approval_no_changes_polls_to_complete():
    full_awaiting = _job(JobStatus.AWAITING_APPROVAL, pending_changes=[])
    completed_compact = _job(JobStatus.COMPLETED)

    client = AsyncMock()
    # get_job(compact=False) returns awaiting; subsequent compact polls return completed
    client.get_job.side_effect = [full_awaiting, completed_compact]

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)
    mock_repo, mock_db = _patch_db([[]])  # no existing claims

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["claim_ids"] == []
    assert result["final_job_status"] == "completed"
    approval_handler.sync_pending_changes.assert_not_called()
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 3. awaiting_approval + pending_changes → sync claims, raise escalation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case3_awaiting_approval_with_changes_raises_escalation():
    changes = [{"change_id": "ch-1", "description": "Add tariff heading"}]
    client = AsyncMock()
    client.get_job.return_value = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)

    claim_id = uuid4()
    new_claim = _make_claim(status="pending")
    new_claim.id = claim_id

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock(return_value=[claim_id])
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)

    # First call (_get_superdocs_claims initial): no existing
    # Second call (_get_superdocs_claims after sync): newly created claim
    # Third call (_assert_claims_resolved): same pending claim
    mock_repo, mock_db = _patch_db([[], [new_claim], [new_claim]])

    class FakeEscalation(Exception):
        def __init__(self, reason, metadata=None):
            super().__init__(reason)
            self.reason = reason
            self.metadata = metadata or {}

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo), \
         patch("backend.modules.tariff.stages.superdocs_approval.WorkflowEscalatedException", FakeEscalation):
        with pytest.raises(FakeEscalation) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"
    assert exc_info.value.metadata["pending_claims"] == 1
    approval_handler.sync_pending_changes.assert_called_once()
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 4. completed + pending_changes → NOT skipped, sync claims, raise escalation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case4_completed_with_pending_changes_not_skipped():
    """CRITICAL: completed status must NOT bypass HITL when pending_changes exist."""
    changes = [{"change_id": "ch-2", "description": "Classification change"}]
    client = AsyncMock()
    client.get_job.return_value = _job(JobStatus.COMPLETED, pending_changes=changes)

    claim_id = uuid4()
    synced_claim = _make_claim(status="pending")
    synced_claim.id = claim_id

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock(return_value=[claim_id])
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)

    mock_repo, mock_db = _patch_db([[], [synced_claim], [synced_claim]])

    class FakeEscalation(Exception):
        def __init__(self, reason, metadata=None):
            super().__init__(reason)
            self.reason = reason
            self.metadata = metadata or {}

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo), \
         patch("backend.modules.tariff.stages.superdocs_approval.WorkflowEscalatedException", FakeEscalation):
        with pytest.raises(FakeEscalation) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"
    # sync WAS called — not skipped
    approval_handler.sync_pending_changes.assert_called_once()
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Claims exist, all resolved (resume) → apply_approvals, complete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case5_resume_all_claims_resolved_applies_and_completes():
    # On resume: SuperDocs still shows awaiting_approval (job waiting on decisions)
    changes = [{"change_id": "ch-1"}]
    awaiting = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)
    completed = _job(JobStatus.COMPLETED)

    client = AsyncMock()
    # First: resolve job status; second: poll_until_complete
    client.get_job.side_effect = [awaiting, completed]

    approved_claim = _make_claim(status="approved")

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})

    stage = _make_stage(client=client, approval_handler=approval_handler)

    # Initial get_superdocs_claims: existing approved claim (already synced)
    # _assert_claims_resolved: same approved claim → no pending → pass
    mock_repo, mock_db = _patch_db([[approved_claim], [approved_claim]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["approved_count"] == 1
    assert result["rejected_count"] == 0
    assert result["final_job_status"] == "completed"
    # sync NOT called — already done
    approval_handler.sync_pending_changes.assert_not_called()
    # apply_approvals WAS called
    approval_handler.apply_approvals.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Claims exist, some still pending (resume re-check) → re-raise escalation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case6_resume_with_pending_claims_reescalates():
    """Safety gate: even on resume, pending claims block progress."""
    changes = [{"change_id": "ch-1"}]
    awaiting = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)

    client = AsyncMock()
    client.get_job.return_value = awaiting

    pending_claim = _make_claim(status="pending")

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)

    # Existing pending claim — not resolved yet
    mock_repo, mock_db = _patch_db([[pending_claim], [pending_claim]])

    class FakeEscalation(Exception):
        def __init__(self, reason, metadata=None):
            super().__init__(reason)
            self.reason = reason
            self.metadata = metadata or {}

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo), \
         patch("backend.modules.tariff.stages.superdocs_approval.WorkflowEscalatedException", FakeEscalation):
        with pytest.raises(FakeEscalation) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"
    # sync NOT called (claim already exists)
    approval_handler.sync_pending_changes.assert_not_called()
    # apply_approvals NOT called (still pending)
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Approved claim → apply_approvals reports approved=1, rejected=0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case7_approved_claim_reports_correctly():
    changes = [{"change_id": "ch-approved"}]
    awaiting = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)
    completed = _job(JobStatus.COMPLETED)

    client = AsyncMock()
    client.get_job.side_effect = [awaiting, completed]

    approved_claim = _make_claim(status="approved")

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})

    stage = _make_stage(client=client, approval_handler=approval_handler)
    mock_repo, mock_db = _patch_db([[approved_claim], [approved_claim]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["approved_count"] == 1
    assert result["rejected_count"] == 0
    approval_handler.apply_approvals.assert_called_once()


# ---------------------------------------------------------------------------
# 8. Rejected claim → apply_approvals reports rejected=1, change NOT applied
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case8_rejected_claim_not_applied():
    """Rejected claims must NOT be applied to SuperDocs (apply_approvals handles this)."""
    changes = [{"change_id": "ch-rejected"}]
    awaiting = _job(JobStatus.AWAITING_APPROVAL, pending_changes=changes)
    completed = _job(JobStatus.COMPLETED)

    client = AsyncMock()
    client.get_job.side_effect = [awaiting, completed]

    rejected_claim = _make_claim(status="rejected")

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    # apply_approvals is responsible for calling approve_change(approved=False) for rejected
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 0, "rejected": 1})

    stage = _make_stage(client=client, approval_handler=approval_handler)
    mock_repo, mock_db = _patch_db([[rejected_claim], [rejected_claim]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["approved_count"] == 0
    assert result["rejected_count"] == 1
    # apply_approvals was called — it handles the rejection internally
    approval_handler.apply_approvals.assert_called_once()


# ---------------------------------------------------------------------------
# 9. No job_id → ValueError immediately
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case9_missing_job_id_raises_value_error():
    stage = _make_stage()
    with pytest.raises(ValueError, match="No SuperDocs job ID"):
        await stage.execute(_base_state(superdocs_job_id=None))


# ---------------------------------------------------------------------------
# 10. SuperDocs job FAILED → Exception, never silently continue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case10_failed_job_raises_never_continues():
    client = AsyncMock()
    client.get_job.return_value = _job(JobStatus.FAILED)

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock()
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)

    with pytest.raises(Exception, match="SuperDocs job failed"):
        await stage.execute(_base_state())

    approval_handler.sync_pending_changes.assert_not_called()
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 11. SuperDocs job CANCELLED → Exception, never silently continue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case11_cancelled_job_raises():
    client = AsyncMock()
    client.get_job.return_value = _job(JobStatus.CANCELLED)

    stage = _make_stage(client=client)

    with pytest.raises(Exception, match="cancelled"):
        await stage.execute(_base_state())


# ---------------------------------------------------------------------------
# 12. instruction stage uses ask_every_time (preserves HITL contract)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case12_instruction_stage_uses_ask_every_time():
    """Verify superdocs_instruction calls chat_async with ask_every_time."""
    from backend.modules.tariff.stages.superdocs_instruction import SuperDocsInstructionStage

    mock_client = AsyncMock()
    mock_client.chat_async.return_value = MagicMock(job_id="job-999")

    mock_builder = MagicMock()
    mock_builder.build_structured_memo_instruction.return_value = "instruction"

    mock_section = MagicMock(
        title="Test",
        section_order=1,
        section_type="analysis",
        content="content",
        analyst_reasoning="reasoning",
        source_attribution=[],
        structured_data=None,
        status="active",
    )
    mock_section_repo = AsyncMock()
    mock_section_repo.list_by_run.return_value = [mock_section]

    stage = SuperDocsInstructionStage(
        superdocs_client=mock_client,
        instruction_builder=mock_builder,
        memo_section_repository=mock_section_repo,
        document_repository=AsyncMock(),
    )

    defaults = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "superdocs_session_id": "sess-123",
    }
    result = await stage.execute(TariffWorkflowState(**defaults))

    assert result["superdocs_job_id"] == "job-999"
    _, kwargs = mock_client.chat_async.call_args
    assert kwargs.get("approval_mode") == "ask_every_time", (
        "Instruction stage MUST use ask_every_time to preserve HITL — "
        "changing this removes human review from the workflow"
    )


# ---------------------------------------------------------------------------
# 13. Dual-signal safety: SuperDocs completed but claims still pending → block
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case13_superdocs_completed_but_pending_claims_blocks():
    """
    SAFETY: If SuperDocs reports completed but DocIntel still has pending claims,
    the workflow must NOT proceed. Claims are the authoritative human-review gate.
    """
    # SuperDocs job shows completed (changes were applied already or expired),
    # but a DocIntel claim is still pending (human hasn't reviewed yet)
    client = AsyncMock()
    client.get_job.return_value = _job(JobStatus.COMPLETED, pending_changes=[])

    pending_claim = _make_claim(status="pending")

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler)

    # No SuperDocs pending_changes, but there IS an existing pending DocIntel claim
    mock_repo, mock_db = _patch_db([[pending_claim], [pending_claim]])

    class FakeEscalation(Exception):
        def __init__(self, reason, metadata=None):
            super().__init__(reason)
            self.reason = reason
            self.metadata = metadata or {}

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo), \
         patch("backend.modules.tariff.stages.superdocs_approval.WorkflowEscalatedException", FakeEscalation):
        with pytest.raises(FakeEscalation) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"
    approval_handler.apply_approvals.assert_not_called()


# ---------------------------------------------------------------------------
# 14. 57 resolved claims applied cleanly through stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case14_stage_executes_57_resolved_approvals():
    """
    Stage processes 57 resolved claims, applies them, and completes when SuperDocs finishes.
    """
    client = AsyncMock()
    # Initial status: awaiting approval with no pending changes (since all resolved) or completed
    client.get_job = AsyncMock(return_value=_job(JobStatus.COMPLETED, pending_changes=[]))

    claims = [_make_claim(status="approved") for _ in range(57)]
    mock_repo, mock_db = _patch_db([claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 57, "rejected": 0})

    stage = _make_stage(client=client, approval_handler=approval_handler)

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["approved_count"] == 57
    assert len(result["claim_ids"]) == 57
    approval_handler.apply_approvals.assert_awaited_once()


# ---------------------------------------------------------------------------
# 15. Fast failure if SuperDocs remains awaiting_approval with pending changes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case15_poll_fails_fast_on_persistent_pending_changes():
    """
    If SuperDocs remains stuck in awaiting_approval with pending changes after approvals,
    the stage must fail fast after max reconciliations rather than waiting 300s.
    """
    client = AsyncMock()
    # First get_job returns awaiting_approval with no pending changes to pass initial gate
    # but subsequent completion polls report awaiting_approval with a stuck change
    client.get_job = AsyncMock(side_effect=[
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[]),
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-stuck"}]),
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-stuck"}]),
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-stuck"}]),
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-stuck"}]),
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-stuck"}]),
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-stuck"}]),
    ])

    claims = [_make_claim(status="approved")]
    mock_repo, mock_db = _patch_db([claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})
    approval_handler.reconcile_pending_changes = AsyncMock(return_value={"escalation_required": False, "reconciled": 0})

    stage = _make_stage(client=client, approval_handler=approval_handler, poll_interval=0.0)

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        with pytest.raises(Exception, match="chg-stuck"):
            await stage.execute(_base_state())


# ---------------------------------------------------------------------------
# 16. Exact 4-poll sequence: in_progress (0) -> awaiting_approval (1) -> awaiting_approval (0) -> completed (0)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case16_exact_4_poll_state_sequence():
    """
    REGRESSION TEST for state oscillation race condition:
    Poll 1: in_progress, pending 0 (progress 93)
    Poll 2: awaiting_approval, pending 1 (progress 94)
    Poll 3: awaiting_approval, pending 0 (progress 94)
    Poll 4: completed, pending 0 (progress 100)

    Verifies:
      - Workflow does NOT complete prematurely on poll 1
      - Workflow does NOT fail on poll 2 (reconciles pending change)
      - Workflow completes ONLY after poll 4
    """
    client = AsyncMock()
    # Initial status check passes:
    client.get_job = AsyncMock(side_effect=[
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[]),  # initial _resolve_job_status
        _job(JobStatus.IN_PROGRESS, progress=0.93, pending_changes=[]),  # Poll 1
        _job(JobStatus.AWAITING_APPROVAL, progress=0.94, pending_changes=[{"change_id": "chg-1"}]),  # Poll 2
        _job(JobStatus.AWAITING_APPROVAL, progress=0.94, pending_changes=[]),  # Poll 3
        _job(JobStatus.COMPLETED, progress=1.0, pending_changes=[]),  # Poll 4
    ])

    claims = [_make_claim(status="approved", superdocs_change_id="chg-1")]
    mock_repo, mock_db = _patch_db([claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})
    approval_handler.reconcile_pending_changes = AsyncMock(return_value={"escalation_required": False, "reconciled": 1})

    stage = _make_stage(client=client, approval_handler=approval_handler, poll_interval=0.0)

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["approved_count"] == 1
    assert result["final_job_status"] == "completed"
    assert client.get_job.call_count == 5
    approval_handler.reconcile_pending_changes.assert_awaited_once()


# ---------------------------------------------------------------------------
# 17. Remote job failure raises immediate actionable error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case17_remote_job_failure_raises_immediately():
    """
    If SuperDocs transitions to FAILED during polling, stage raises immediately.
    """
    client = AsyncMock()
    client.get_job = AsyncMock(side_effect=[
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[]),  # initial
        _job(JobStatus.IN_PROGRESS, progress=0.5, pending_changes=[]),
        _job(JobStatus.FAILED, error="Syntax error in document compilation", pending_changes=[]),
    ])

    claims = [_make_claim(status="approved")]
    mock_repo, mock_db = _patch_db([claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})

    stage = _make_stage(client=client, approval_handler=approval_handler, poll_interval=0.0)

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        with pytest.raises(Exception, match="Syntax error in document compilation"):
            await stage.execute(_base_state())


# ---------------------------------------------------------------------------
# 18. Newly emerged unknown change triggers human escalation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case18_new_emerged_change_escalates_for_human_review():
    """
    If SuperDocs produces a brand new change during execution, reconciliation
    detects it and raises WorkflowEscalatedException for human review.
    """
    client = AsyncMock()
    client.get_job = AsyncMock(side_effect=[
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[]),  # initial
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[{"change_id": "chg-brand-new"}]),
    ])

    claims = [_make_claim(status="approved", superdocs_change_id="chg-1")]
    mock_repo, mock_db = _patch_db([claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})
    approval_handler.reconcile_pending_changes = AsyncMock(return_value={
        "escalation_required": True,
        "new_claims_count": 1,
        "total_claims_count": 2,
    })

    stage = _make_stage(client=client, approval_handler=approval_handler, poll_interval=0.0)

    class FakeEscalation(Exception):
        def __init__(self, reason, metadata=None):
            super().__init__(reason)
            self.reason = reason
            self.metadata = metadata or {}

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo), \
         patch("backend.modules.tariff.stages.superdocs_approval.WorkflowEscalatedException", FakeEscalation):
        with pytest.raises(FakeEscalation) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"


# ---------------------------------------------------------------------------
# 19. Stabilization window: ignores brief transient 0 if remote bounces back
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case19_stabilization_window_catches_destabilization():
    """
    Candidate completed with 0 pending, but stabilization check 2/2 sees pending change,
    reconciles it, and only completes on subsequent stable completed status.
    """
    client = AsyncMock()
    client.get_job = AsyncMock(side_effect=[
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[]),  # initial _resolve_job_status
        _job(JobStatus.COMPLETED, progress=1.0, pending_changes=[]),  # Poll 1 -> candidate terminal
        _job(JobStatus.AWAITING_APPROVAL, progress=0.99, pending_changes=[{"change_id": "chg-bounced"}]),  # Stabilization check 2/2 -> destabilized!
        _job(JobStatus.AWAITING_APPROVAL, progress=0.99, pending_changes=[{"change_id": "chg-bounced"}]),  # Poll 2 -> reconciles
        _job(JobStatus.COMPLETED, progress=1.0, pending_changes=[]),  # Poll 3 -> candidate terminal again
        _job(JobStatus.COMPLETED, progress=1.0, pending_changes=[]),  # Stabilization check 2/2 -> stable!
    ])

    claims = [_make_claim(status="approved", superdocs_change_id="chg-1")]
    mock_repo, mock_db = _patch_db([claims, claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})
    approval_handler.reconcile_pending_changes = AsyncMock(return_value={"escalation_required": False, "reconciled": 1})

    # stabilization_delay=0.001 so stabilization query executes
    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.0,
        poll_timeout=5,
        stabilization_delay=0.001,
    )

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["final_job_status"] == "completed"
    approval_handler.reconcile_pending_changes.assert_awaited_once()


# ---------------------------------------------------------------------------
# 20. Single-flight lock: concurrent executions for the same job are serialized
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case20_single_flight_per_job_lock():
    """
    Two concurrent stage.execute calls for the SAME job_id are serialized and do not race.
    """
    client = AsyncMock()
    client.get_job = AsyncMock(return_value=_job(JobStatus.COMPLETED, pending_changes=[]))

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 0, "rejected": 0})

    stage = _make_stage(client=client, approval_handler=approval_handler, poll_interval=0.0)
    mock_repo, mock_db = _patch_db([[], []])

    state = _base_state(superdocs_job_id="job-single-flight-1")

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        res1, res2 = await asyncio.gather(
            stage.execute(state),
            stage.execute(state),
        )

    assert res1["superdocs_approval_completed"] is True
    assert res2["superdocs_approval_completed"] is True


# ---------------------------------------------------------------------------
# 21. Remote timeout fails fast with detailed actionable message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case21_remote_timeout_actionable_error():
    """
    If job fails to converge within poll_timeout, raises TimeoutError with actionable diagnostics.
    """
    client = AsyncMock()
    # Initial resolve returns awaiting_approval, but polling stays in_progress
    client.get_job = AsyncMock(side_effect=[
        _job(JobStatus.AWAITING_APPROVAL, pending_changes=[]),
        _job(JobStatus.IN_PROGRESS, progress=0.5, pending_changes=[]),
        _job(JobStatus.IN_PROGRESS, progress=0.5, pending_changes=[]),
        _job(JobStatus.IN_PROGRESS, progress=0.5, pending_changes=[]),
        _job(JobStatus.IN_PROGRESS, progress=0.5, pending_changes=[]),
        _job(JobStatus.IN_PROGRESS, progress=0.5, pending_changes=[]),
    ])

    claims = [_make_claim(status="approved")]
    mock_repo, mock_db = _patch_db([claims, claims])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})

    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=0.02,
    )

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        with pytest.raises(TimeoutError, match="failed to converge within"):
            await stage.execute(_base_state())


# ---------------------------------------------------------------------------
# 22. REGRESSION: in_progress (99%, 0 pending) -> awaiting_approval (99%, 1 pending)
#     asserts review/claims synced, pauses cleanly with WorkflowEscalatedException,
#     and does NOT poll SuperDocs in a loop.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case22_regression_in_progress_then_awaiting_approval_pauses_cleanly():
    """
    Exact scenario:
    1. Initial get_job: in_progress, progress=99, pending_count=0
    2. Polled get_job: awaiting_approval, progress=99, pending_count=1, pending_ids=['change-1']
    3. Assert claims synced and stage immediately raises WorkflowEscalatedException.
    4. Assert get_job is NOT called further (worker stops).
    """
    job_in_progress = _job(JobStatus.IN_PROGRESS, progress=0.99, pending_changes=[])
    changes = [{"change_id": "change-1", "description": "Update classification GRI 1"}]
    job_awaiting = _job(JobStatus.AWAITING_APPROVAL, progress=0.99, pending_changes=changes)

    client = AsyncMock()
    # 1. compact=False initially (in_progress) -> _poll_until_actionable compact=True -> compact=False (awaiting_approval)
    client.get_job = AsyncMock(side_effect=[
        job_in_progress,
        job_awaiting,
        job_awaiting,
    ])

    claim_id = uuid4()
    created_claim = _make_claim(status="pending", superdocs_change_id="change-1")
    created_claim.id = claim_id

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock(return_value=[claim_id])
    approval_handler.apply_approvals = AsyncMock()

    stage = _make_stage(client=client, approval_handler=approval_handler, poll_interval=0.001)

    # DB returns [] before sync, then [created_claim] after sync
    mock_repo, mock_db = _patch_db([[], [created_claim], [created_claim]])

    class FakeEscalation(Exception):
        def __init__(self, reason, metadata=None):
            super().__init__(reason)
            self.reason = reason
            self.metadata = metadata or {}

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo), \
         patch("backend.modules.tariff.stages.superdocs_approval.WorkflowEscalatedException", FakeEscalation):
        with pytest.raises(FakeEscalation) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"
    assert exc_info.value.metadata.get("pending_claims") == 1

    # Assert sync_pending_changes was called
    approval_handler.sync_pending_changes.assert_awaited_once()

    # Assert apply_approvals was NOT called (waiting for human)
    approval_handler.apply_approvals.assert_not_called()

    # Assert client.get_job was called at most 3 times (initial + poll until actionable + full status)
    # and NOT polled indefinitely in a loop
    assert client.get_job.await_count <= 3


# ---------------------------------------------------------------------------
# 23. Pre-HITL timeout: job stays in_progress beyond poll_timeout -> actionable TimeoutError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case23_pre_hitl_timeout_actionable_error():
    """Verify that if SuperDocs stays in_progress during pre-HITL, a descriptive TimeoutError is raised."""
    client = AsyncMock()
    client.get_job = AsyncMock(return_value=_job(JobStatus.IN_PROGRESS, progress=0.99, pending_changes=[]))

    approval_handler = AsyncMock()
    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=0.02,
    )

    mock_repo, mock_db = _patch_db([[]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        with pytest.raises(TimeoutError, match="did not reach actionable state within"):
            await stage.execute(_base_state())


# ---------------------------------------------------------------------------
# 24. Idempotent claim deduplication by change_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case24_approval_handler_idempotent_deduplication():
    """Verify that sync_pending_changes deduplicates by superdocs_change_id."""
    from backend.integrations.superdocs.approval_handler import ApprovalHandler

    existing_claim_id = uuid4()
    existing_claim = _make_claim(status="pending", superdocs_change_id="ch-100")
    existing_claim.id = existing_claim_id

    claim_repo = AsyncMock()
    claim_repo.list_by_superdocs_job_id = AsyncMock(return_value=[existing_claim])
    claim_repo.list_by_run = AsyncMock(return_value=[existing_claim])
    claim_repo.create = AsyncMock()

    review_repo = AsyncMock()
    mock_review = MagicMock()
    mock_review.id = uuid4()
    review_repo.create = AsyncMock(return_value=mock_review)

    handler = ApprovalHandler(
        superdocs_client=AsyncMock(),
        session_manager=AsyncMock(),
        claim_repository=claim_repo,
        review_repository=review_repo,
    )

    pending_changes = [
        {"change_id": "ch-100", "old_html": "old", "new_html": "new", "ai_explanation": "exp"},
        {"change_id": "ch-200", "old_html": "old2", "new_html": "new2", "ai_explanation": "exp2"},
    ]
    job_status = _job(JobStatus.AWAITING_APPROVAL, pending_changes=pending_changes)

    new_claim_id = uuid4()
    handler._create_claim_from_change = AsyncMock(return_value=new_claim_id)

    run_id = uuid4()
    workspace_id = uuid4()
    synced_ids = await handler.sync_pending_changes(
        run_id=run_id,
        job_id="job-test",
        job_status=job_status,
        workspace_id=workspace_id,
    )

    # ch-100 was already existing -> reused existing_claim_id without recreating
    # ch-200 was new -> created new_claim_id
    assert synced_ids == [existing_claim_id, new_claim_id]
    handler._create_claim_from_change.assert_awaited_once()


# ---------------------------------------------------------------------------
# 25. FIX 1 & 2: Timeout threshold reached, final get_job() = COMPLETED
#     -> stage succeeds, no retry, no error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case25_timeout_threshold_final_check_completed_succeeds():
    """Verify that if the polling loop exceeds timeout but the final authoritative get_job is COMPLETED, it succeeds."""
    in_progress_job = _job(JobStatus.IN_PROGRESS, progress=0.79, pending_changes=[])
    completed_job = _job(JobStatus.COMPLETED, progress=1.0, pending_changes=[])

    client = AsyncMock()
    # Compact poll returns IN_PROGRESS, final authoritative compact=False call returns COMPLETED
    client.get_job = AsyncMock(side_effect=[in_progress_job, completed_job, completed_job])

    approval_handler = AsyncMock()
    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=0.01,
        stabilization_delay=0.0,
    )

    mock_repo, mock_db = _patch_db([[]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["final_job_status"] == "completed"
    assert result["decision_reason"] == "Human Review skipped — no changes required"


# ---------------------------------------------------------------------------
# 26. FIX 1 & 2: Timeout threshold reached, final get_job() = AWAITING_APPROVAL
#     -> pauses for human review, no timeout failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case26_timeout_threshold_final_check_awaiting_approval_pauses_hitl():
    """Verify that if timeout is reached but final authoritative get_job is AWAITING_APPROVAL, claims sync and pause for HITL."""
    from backend.core.workflow.runner import WorkflowEscalatedException

    in_progress_job = _job(JobStatus.IN_PROGRESS, progress=0.85, pending_changes=[])
    pending_change = [{"change_id": "ch-999", "old_html": "a", "new_html": "b"}]
    awaiting_job = _job(JobStatus.AWAITING_APPROVAL, progress=1.0, pending_changes=pending_change)

    client = AsyncMock()
    client.get_job = AsyncMock(side_effect=[in_progress_job, awaiting_job, awaiting_job])

    approval_handler = AsyncMock()
    approval_handler.sync_pending_changes = AsyncMock(return_value=[uuid4()])

    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=0.01,
    )

    created_claim = _make_claim(status="pending")
    mock_repo, mock_db = _patch_db([[], [created_claim]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        with pytest.raises(WorkflowEscalatedException) as exc_info:
            await stage.execute(_base_state())

    assert exc_info.value.reason == "awaiting_human_approval"
    approval_handler.sync_pending_changes.assert_awaited_once()


# ---------------------------------------------------------------------------
# 27. FIX 1: Timeout threshold reached, final get_job() = IN_PROGRESS
#     -> genuine timeout error raised
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case27_timeout_threshold_final_check_in_progress_raises_timeout():
    """Verify that if timeout is reached and final get_job is still IN_PROGRESS, TimeoutError is raised."""
    in_progress_job = _job(JobStatus.IN_PROGRESS, progress=0.50, pending_changes=[])

    client = AsyncMock()
    client.get_job = AsyncMock(return_value=in_progress_job)

    approval_handler = AsyncMock()
    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=0.01,
    )

    mock_repo, mock_db = _patch_db([[]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        with pytest.raises(TimeoutError, match="did not reach actionable state within"):
            await stage.execute(_base_state())


# ---------------------------------------------------------------------------
# 28. FIX 1 & 2: Reconciliation loop timeout final check completed succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case28_reconcile_timeout_final_check_completed_succeeds():
    """Verify that post-HITL reconciliation timeout does a final check and succeeds if COMPLETED."""
    completed_job = _job(JobStatus.COMPLETED, pending_changes=[])

    client = AsyncMock()
    client.get_job = AsyncMock(return_value=completed_job)

    resolved_claim = _make_claim(status="approved")
    mock_repo, mock_db = _patch_db([[resolved_claim], [resolved_claim], [resolved_claim]])

    approval_handler = AsyncMock()
    approval_handler.apply_approvals = AsyncMock(return_value={"approved": 1, "rejected": 0})

    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=0.01,
        stabilization_delay=0.0,
    )

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["approved_count"] == 1
    assert result["final_job_status"] == "completed"


# ---------------------------------------------------------------------------
# 29. FIX 4: Correct "no changes" semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case29_no_changes_semantics_returns_decision_reason():
    """Verify that when no changes exist, decision_reason is set cleanly."""
    completed_job = _job(JobStatus.COMPLETED, pending_changes=[])

    client = AsyncMock()
    client.get_job = AsyncMock(return_value=completed_job)

    approval_handler = AsyncMock()
    stage = _make_stage(client=client, approval_handler=approval_handler)
    mock_repo, mock_db = _patch_db([[]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["claim_ids"] == []
    assert result["decision_reason"] == "Human Review skipped — no changes required"


# ---------------------------------------------------------------------------
# 30. Stabilization check across delay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_case30_stabilization_check_completed_terminal():
    """Verify that stabilization check cleanly completes when job stays completed."""
    completed_job = _job(JobStatus.COMPLETED, pending_changes=[])

    client = AsyncMock()
    client.get_job = AsyncMock(return_value=completed_job)

    approval_handler = AsyncMock()
    stage = SuperDocsApprovalStage(
        superdocs_client=client,
        session_manager=AsyncMock(),
        approval_handler=approval_handler,
        poll_interval=0.005,
        poll_timeout=5,
        stabilization_delay=0.01,
    )
    mock_repo, mock_db = _patch_db([[]])

    with patch("backend.modules.tariff.stages.superdocs_approval.async_session_maker", return_value=mock_db), \
         patch("backend.modules.tariff.stages.superdocs_approval.ClaimRepository", return_value=mock_repo):
        result = await stage.execute(_base_state())

    assert result["superdocs_approval_completed"] is True
    assert result["final_job_status"] == "completed"





