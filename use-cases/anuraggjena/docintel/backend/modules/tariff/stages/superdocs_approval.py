"""
SuperDocs Approval Stage.

Handles the approval flow for SuperDocs proposed changes in Tariff workflow.

Safety guarantee: the workflow NEVER advances to export while unresolved
pending_changes exist in SuperDocs or unresolved claims exist in DocIntel.

Conditional HITL behavior (both signals checked):
  CASE A: completed + no pending_changes, no claims  → skip HITL entirely (after stabilization check)
  CASE B: awaiting_approval + pending_changes        → sync claims, pause for review
  CASE C: completed + pending_changes                → sync claims, pause for review
  CASE D: claims exist but all resolved              → apply approvals, continue to reconciliation
  CASE E: claims exist, some still pending           → re-raise escalation (resume gate)
  CASE F: failed/cancelled/unknown                   → raise, never silently continue
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.core.workflow.runner import WorkflowEscalatedException
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.integrations.superdocs.client import SuperDocsClient, JobStatus, JobStatusResult
from backend.integrations.superdocs.session_manager import SessionManager
from backend.integrations.superdocs.approval_handler import ApprovalHandler
from backend.repositories.review import ClaimRepository
from backend.database import async_session_maker
from backend.logging_config import get_logger

logger = get_logger(__name__)

# Single-flight lock coordinator per SuperDocs job
_job_locks: Dict[str, asyncio.Lock] = {}
_job_locks_guard = asyncio.Lock()


async def _get_job_lock(job_id: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock specific to a SuperDocs job_id."""
    async with _job_locks_guard:
        if job_id not in _job_locks:
            _job_locks[job_id] = asyncio.Lock()
        return _job_locks[job_id]


class SuperDocsApprovalStage(StageNode[TariffWorkflowState]):
    """
    SuperDocs approval stage for Tariff workflow.

    Uses dual-signal safety: checks BOTH SuperDocs job state AND DocIntel claims
    before allowing the workflow to proceed. Neither signal alone is sufficient.
    """

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        session_manager: SessionManager,
        approval_handler: ApprovalHandler,
        poll_interval: float = 0.5,
        poll_timeout: int = 120,
        stabilization_delay: Optional[float] = None,
        max_reconciliations: int = 5,
    ):
        super().__init__("superdocs_approval")
        self.client = superdocs_client
        self.session_manager = session_manager
        self.approval_handler = approval_handler
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        if stabilization_delay is None:
            self.stabilization_delay = 0.0 if poll_interval <= 0.05 else 1.0
        else:
            self.stabilization_delay = stabilization_delay
        self.max_reconciliations = max_reconciliations

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Execute SuperDocs approval flow with full safety guarantees and single-flight serialization.

        First run:  poll job → sync changes to claims if any → pause for HITL.
        On resume:  claims already exist → check resolution → apply approvals.

        NEVER proceeds to export while unresolved changes or pending claims exist.
        """
        job_id = state.superdocs_job_id

        if not job_id:
            raise ValueError("No SuperDocs job ID in workflow state")

        run_id = UUID(state.workflow_run_id)

        # Single-flight serialization: exactly one reconciliation/polling loop per job_id
        job_lock = await _get_job_lock(job_id)
        async with job_lock:
            return await self._execute_stage(run_id=run_id, job_id=job_id, state=state)

    async def _execute_stage(self, run_id: UUID, job_id: str, state: TariffWorkflowState) -> Dict[str, Any]:
        logger.info("starting_superdocs_approval", job_id=job_id, run_id=str(run_id))

        # --- SIGNAL 1: Get authoritative SuperDocs job status ---
        job_status = await self._resolve_job_status(job_id)

        # --- SIGNAL 2: Get DocIntel claim state ---
        existing_claims = await self._get_superdocs_claims(run_id)
        has_existing_claims = bool(existing_claims)

        # In Phase A (no existing claims yet): if job transitioned to awaiting_approval
        # but pending_changes array has not populated yet, briefly poll for changes.
        if not has_existing_claims and job_status.status == JobStatus.AWAITING_APPROVAL and not job_status.pending_changes:
            wait_start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - wait_start < 10.0:
                await asyncio.sleep(self.poll_interval)
                check_status = await self.client.get_job(job_id, compact=False)
                if check_status.pending_changes:
                    job_status = check_status
                    break
                if check_status.status == JobStatus.COMPLETED:
                    job_status = check_status
                    break

        has_superdocs_changes = bool(job_status.pending_changes)

        logger.info(
            "superdocs_approval_signals",
            job_id=job_id,
            job_status=job_status.status.value,
            superdocs_pending_count=len(job_status.pending_changes or []),
            docIntel_claims_count=len(existing_claims),
        )

        # --- Determine path using BOTH signals ---

        # CASE A: No changes anywhere and job is completed — verify via stabilization check before clean skip
        if (
            job_status.status == JobStatus.COMPLETED
            and not has_superdocs_changes
            and not has_existing_claims
        ):
            logger.info(f"[SuperDocs] candidate_terminal_state=true")
            logger.info(f"[SuperDocs] stabilization_check=1/2")
            if self.stabilization_delay > 0:
                await asyncio.sleep(self.stabilization_delay)
                confirm_status = await self.client.get_job(job_id, compact=False)
                confirm_pending = confirm_status.pending_changes or []
                logger.info(
                    f"[SuperDocs] stabilization_check=2/2 status={confirm_status.status.value} pending_count={len(confirm_pending)}"
                )

                if confirm_status.status != JobStatus.COMPLETED or len(confirm_pending) > 0:
                    job_status = confirm_status
                    has_superdocs_changes = bool(job_status.pending_changes)
                else:
                    logger.info(f"[SuperDocs] final_remote_state={confirm_status.status.value}")
                    logger.info(f"[SuperDocs] convergence_result=success")
                    logger.info("superdocs_approval_no_changes_skip_hitl", job_id=job_id)
                    return {
                        "superdocs_approval_completed": True,
                        "claim_ids": [],
                        "approved_count": 0,
                        "rejected_count": 0,
                        "final_job_status": "completed",
                        "decision_reason": "Human Review skipped — no changes required",
                    }
            else:
                logger.info(f"[SuperDocs] stabilization_check=2/2 status={job_status.status.value} pending_count=0")
                logger.info(f"[SuperDocs] final_remote_state={job_status.status.value}")
                logger.info(f"[SuperDocs] convergence_result=success")
                logger.info("superdocs_approval_no_changes_skip_hitl", job_id=job_id)
                return {
                    "superdocs_approval_completed": True,
                    "claim_ids": [],
                    "approved_count": 0,
                    "rejected_count": 0,
                    "final_job_status": "completed",
                    "decision_reason": "Human Review skipped — no changes required",
                }

        # PHASE A: INITIAL HUMAN APPROVAL (Sync remote changes & Pause)
        # CASE B/C: SuperDocs has pending changes (first run or re-check)
        # Sync to claims if not already done (idempotent)
        if has_superdocs_changes and not has_existing_claims:
            new_claim_ids = await self.approval_handler.sync_pending_changes(
                run_id=run_id,
                job_id=job_id,
                job_status=job_status
            )
            logger.info(
                "pending_changes_synced_to_claims",
                job_id=job_id,
                claims_created=len(new_claim_ids)
            )
            # Re-fetch after creation
            existing_claims = await self._get_superdocs_claims(run_id)

        # --- DUAL-SIGNAL SAFETY GATE ---
        # At this point we have claims (either just created or pre-existing from resume).
        # Check both signals before proceeding:
        #   1. Are all DocIntel claims resolved?
        #   2. Is the SuperDocs job no longer awaiting_approval?

        await self._assert_claims_resolved(run_id, existing_claims)
        # ^ raises WorkflowEscalatedException if any claim is still pending

        # All claims resolved — apply decisions to SuperDocs
        approval_counts = await self.approval_handler.apply_approvals(
            run_id=run_id,
            job_id=job_id
        )

        logger.info(
            "approvals_applied",
            job_id=job_id,
            approved=approval_counts["approved"],
            rejected=approval_counts["rejected"]
        )

        # Poll until SuperDocs finishes processing the decisions and reaches a stable terminal state
        final_status = await self._poll_and_reconcile(run_id=run_id, job_id=job_id)

        if final_status.status == JobStatus.FAILED:
            raise Exception(f"SuperDocs job failed after approvals: {final_status.error}")

        if final_status.status == JobStatus.CANCELLED:
            raise Exception("SuperDocs job was cancelled after approvals")

        logger.info(
            "superdocs_approval_complete",
            job_id=job_id,
            final_status=final_status.status.value
        )

        all_claim_ids = [str(c.id) for c in existing_claims]
        return {
            "superdocs_approval_completed": True,
            "claim_ids": all_claim_ids,
            "approved_count": approval_counts["approved"],
            "rejected_count": approval_counts["rejected"],
            "final_job_status": final_status.status.value
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_job_status(self, job_id: str) -> JobStatusResult:
        """
        Return current job status. Polls if still in_progress/pending.
        Raises immediately for failed/cancelled.
        """
        initial = await self.client.get_job(job_id, compact=False)

        if initial.status in (JobStatus.AWAITING_APPROVAL, JobStatus.COMPLETED):
            return initial

        if initial.status == JobStatus.FAILED:
            raise Exception(f"SuperDocs job failed: {initial.error}")
        if initial.status == JobStatus.CANCELLED:
            raise Exception("SuperDocs job was cancelled")

        logger.info(
            "superdocs_job_processing_poll",
            job_id=job_id,
            status=initial.status.value
        )
        return await self._poll_until_actionable(job_id)

    async def _poll_until_actionable(self, job_id: str) -> JobStatusResult:
        """
        Poll until job reaches awaiting_approval or completed.
        Returns full JobStatusResult with pending_changes populated.
        """
        start = asyncio.get_event_loop().time()
        last_status = "unknown"
        last_progress = None

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > self.poll_timeout:
                # --- FIX 1: FINAL AUTHORITATIVE CHECK BEFORE TIMEOUT FAILURE ---
                final_status = await self.client.get_job(job_id, compact=False)
                final_pending = final_status.pending_changes or []
                logger.info(
                    f"[SuperDocs] pre_hitl_timeout_final_check job={job_id} status={final_status.status.value} "
                    f"progress={final_status.progress} pending_count={len(final_pending)}"
                )

                # Case A: status == COMPLETED and pending_count == 0 (or COMPLETED generally)
                # Case B: status == AWAITING_APPROVAL (with pending changes)
                if final_status.status in (JobStatus.AWAITING_APPROVAL, JobStatus.COMPLETED):
                    return final_status

                # Case C: status == FAILED or CANCELLED
                if final_status.status == JobStatus.FAILED:
                    raise Exception(f"SuperDocs job failed: {final_status.error}")
                if final_status.status == JobStatus.CANCELLED:
                    raise Exception("SuperDocs job was cancelled")

                # Case D: status == IN_PROGRESS / PENDING (genuine timeout)
                fail_msg = (
                    f"SuperDocs remote job {job_id} did not reach actionable state within {self.poll_timeout}s. "
                    f"Last observed state: status={final_status.status.value}, progress={final_status.progress}. "
                    f"SuperDocs service did not transition to awaiting_approval or completed."
                )
                logger.error(f"[SuperDocs] pre_hitl_timeout job={job_id} elapsed={elapsed:.1f}s error={fail_msg}")
                raise TimeoutError(fail_msg)

            status = await self.client.get_job(job_id, compact=True)
            last_status = status.status.value
            last_progress = status.progress

            logger.info(
                f"[SuperDocs] pre_hitl_processing job={job_id} status={last_status} "
                f"progress={last_progress} elapsed={elapsed:.1f}s"
            )

            if status.status in (JobStatus.AWAITING_APPROVAL, JobStatus.COMPLETED):
                return await self.client.get_job(job_id, compact=False)

            if status.status == JobStatus.FAILED:
                raise Exception(f"SuperDocs job failed: {status.error}")

            if status.status == JobStatus.CANCELLED:
                raise Exception("SuperDocs job was cancelled")

            # Conservative adaptive polling for PRE-HITL state only:
            # When progress >= 90%, poll faster (1.5s) to immediately capture the transition to awaiting_approval
            poll_sleep = 1.5 if (last_progress is not None and last_progress >= 0.90) else min(self.poll_interval, 2.5)
            await asyncio.sleep(poll_sleep)

    async def _get_superdocs_claims(self, run_id: UUID) -> List:
        """Return all superdocs_change claims for this run from DocIntel."""
        async with async_session_maker() as db:
            repo = ClaimRepository(db)
            all_claims = await repo.list_by_run(run_id)

        return [c for c in all_claims if c.claim_type == "superdocs_change"]

    async def _assert_claims_resolved(self, run_id: UUID, claims: List) -> None:
        """
        Raise WorkflowEscalatedException if any superdocs_change claim is still pending.
        This is the safety gate that prevents export while HITL is incomplete.

        On first run: raises immediately to pause workflow.
        On resume: called again; if all resolved, returns normally.
        """
        pending = [c for c in claims if c.status == "pending"]

        if not pending:
            logger.info(
                "all_superdocs_claims_resolved",
                run_id=str(run_id),
                total=len(claims)
            )
            return

        logger.info(
            "pausing_for_human_review",
            run_id=str(run_id),
            pending_count=len(pending),
            total_count=len(claims)
        )

        raise WorkflowEscalatedException(
            reason="awaiting_human_approval",
            metadata={
                "run_id": str(run_id),
                "pending_claims": len(pending),
                "total_claims": len(claims),
            }
        )

    async def _poll_until_complete(self, run_id: UUID, job_id: str) -> JobStatusResult:
        """Alias for _poll_and_reconcile for backward compatibility."""
        return await self._poll_and_reconcile(run_id=run_id, job_id=job_id)

    async def _poll_and_reconcile(self, run_id: UUID, job_id: str) -> JobStatusResult:
        """
        Authoritative single reconciliation loop for SuperDocs job.

        Guarantees:
        - Exactly ONE authoritative loop per job (caller holds job_lock).
        - Handles eventual consistency transitions (in_progress <-> awaiting_approval <-> completed).
        - Reconciles any newly appeared or lingering pending changes.
        - Verifies stable final state via bounded stabilization window check before completion.
        - Fails fast with actionable diagnostics on timeout, failure, or reconciliation limit.
        """
        start = asyncio.get_event_loop().time()
        reconciliation_cycle = 0
        last_status = "unknown"
        last_progress = None
        last_pending_ids: List[str] = []
        last_reconciliation_time = None
        last_approval_attempt = None

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > self.poll_timeout:
                # --- FIX 1: FINAL AUTHORITATIVE CHECK BEFORE TIMEOUT FAILURE ---
                final_status = await self.client.get_job(job_id, compact=False)
                final_pending = final_status.pending_changes or []
                final_pending_ids = [str(c.get("change_id")) for c in final_pending if c.get("change_id")]
                if final_status.status == JobStatus.COMPLETED and len(final_pending_ids) == 0:
                    claims = await self._get_superdocs_claims(run_id)
                    unresolved = [c for c in claims if c.status == "pending"]
                    if not unresolved:
                        logger.info(f"[SuperDocs] final_remote_state={final_status.status.value}")
                        logger.info(f"[SuperDocs] convergence_result=success (final timeout check)")
                        return final_status

                fail_msg = (
                    f"SuperDocs job {job_id} failed to converge within {self.poll_timeout}s timeout. "
                    f"status={final_status.status.value} progress={final_status.progress} pending_count={len(final_pending_ids)} "
                    f"pending_ids={final_pending_ids} last_reconciliation={last_reconciliation_time} "
                    f"last_approval_attempt={last_approval_attempt}. "
                    f"Exact reason: Remote job did not reach stable terminal completed state with 0 pending changes."
                )
                logger.error(f"[SuperDocs] job={job_id} convergence_result=failure error={fail_msg}")
                raise TimeoutError(fail_msg)

            status = await self.client.get_job(job_id, compact=False)
            current_status = status.status
            progress = status.progress
            pending_changes = status.pending_changes or []
            pending_ids = [str(c.get("change_id")) for c in pending_changes if c.get("change_id")]
            pending_count = len(pending_ids)

            last_status = current_status.value
            last_progress = progress
            last_pending_ids = pending_ids

            # Structured logging
            logger.info(
                f"[SuperDocs] job={job_id} status={last_status} progress={progress} pending_count={pending_count} pending_ids={pending_ids}"
            )

            # 1. Terminal Failures
            if current_status == JobStatus.FAILED:
                logger.error(f"[SuperDocs] job={job_id} convergence_result=failure error={status.error}")
                raise Exception(f"SuperDocs job failed: {status.error}")
            if current_status == JobStatus.CANCELLED:
                logger.error(f"[SuperDocs] job={job_id} convergence_result=failure error=cancelled")
                raise Exception("SuperDocs job was cancelled")

            # 2. Candidate Terminal Success: COMPLETED with zero pending changes
            if current_status == JobStatus.COMPLETED and pending_count == 0:
                logger.info(f"[SuperDocs] candidate_terminal_state=true")
                logger.info(f"[SuperDocs] stabilization_check=1/2")

                if self.stabilization_delay > 0:
                    # Bounded stabilization interval
                    await asyncio.sleep(self.stabilization_delay)

                    # Confirmation query
                    confirm_status = await self.client.get_job(job_id, compact=False)
                    confirm_pending = confirm_status.pending_changes or []
                    confirm_pending_ids = [str(c.get("change_id")) for c in confirm_pending if c.get("change_id")]
                    confirm_pending_count = len(confirm_pending_ids)

                    logger.info(
                        f"[SuperDocs] stabilization_check=2/2 status={confirm_status.status.value} pending_count={confirm_pending_count} pending_ids={confirm_pending_ids}"
                    )

                    if confirm_status.status != JobStatus.COMPLETED or confirm_pending_count > 0:
                        logger.warning(
                            f"[SuperDocs] Job destabilized during stabilization check: status={confirm_status.status.value}, pending_count={confirm_pending_count}"
                        )
                        status = confirm_status
                        current_status = status.status
                        pending_changes = confirm_pending
                        pending_ids = confirm_pending_ids
                        pending_count = confirm_pending_count
                        last_status = current_status.value
                        last_pending_ids = pending_ids
                        logger.info(f"[SuperDocs] candidate_terminal_state=false")
                        continue
                else:
                    logger.info(
                        f"[SuperDocs] stabilization_check=2/2 status={current_status.value} pending_count=0 pending_ids=[]"
                    )

                # Final safety check: assert all DocIntel claims are resolved
                claims = await self._get_superdocs_claims(run_id)
                unresolved = [c for c in claims if c.status == "pending"]
                if unresolved:
                    logger.warning(
                        f"[SuperDocs] Found {len(unresolved)} unresolved claims during final check, escalating"
                    )
                    raise WorkflowEscalatedException(
                        reason="awaiting_human_approval",
                        metadata={
                            "run_id": str(run_id),
                            "pending_claims": len(unresolved),
                            "total_claims": len(claims),
                        }
                    )
                logger.info(f"[SuperDocs] final_remote_state={current_status.value}")
                logger.info(f"[SuperDocs] convergence_result=success")
                return status

            # 3. Handle pending changes (awaiting_approval or unexpected pending changes)
            if pending_count > 0:
                reconciliation_cycle += 1
                logger.info(f"[SuperDocs] reconciliation_cycle={reconciliation_cycle}")
                if reconciliation_cycle > self.max_reconciliations:
                    fail_msg = (
                        f"SuperDocs job {job_id} failed to stabilize after {self.max_reconciliations} reconciliations: "
                        f"{pending_count} change(s) remain unapplied (pending IDs: {pending_ids}). "
                        f"Status: {last_status}, Progress: {progress}, Last Reconciliation: {last_reconciliation_time}, "
                        f"Last Approval Attempt: {last_approval_attempt}."
                    )
                    logger.error(f"[SuperDocs] convergence_result=failure error={fail_msg}")
                    raise Exception(fail_msg)

                last_reconciliation_time = datetime.now(timezone.utc).isoformat()
                last_approval_attempt = f"cycle_{reconciliation_cycle}"

                recon_result = await self.approval_handler.reconcile_pending_changes(
                    run_id=run_id,
                    job_id=job_id,
                    pending_changes=pending_changes
                )

                if recon_result.get("escalation_required"):
                    logger.info(f"[SuperDocs] Escalation required for new unapproved claims")
                    raise WorkflowEscalatedException(
                        reason="awaiting_human_approval",
                        metadata={
                            "run_id": str(run_id),
                            "pending_claims": recon_result.get("new_claims_count", 1),
                            "total_claims": recon_result.get("total_claims_count", 1),
                        }
                    )

            await asyncio.sleep(self.poll_interval)

