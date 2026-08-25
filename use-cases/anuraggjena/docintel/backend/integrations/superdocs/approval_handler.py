"""
SuperDocs Approval Handler.

Bridges SuperDocs pending changes with DocIntel review system.
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
from uuid import UUID

from backend.integrations.superdocs.client import SuperDocsClient, JobStatusResult
from backend.integrations.superdocs.session_manager import SessionManager
from backend.repositories.review import ClaimRepository, ReviewRepository
from backend.repositories.lineage import LineageLinkRepository
from backend.models.claim import Claim
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ApprovalHandler:
    """
    Handles approval flow between SuperDocs and DocIntel.

    Responsibilities:
    - Map SuperDocs pending_changes to DocIntel Claims (under a Review row)
    - Sync approval status from DocIntel to SuperDocs
    - Create lineage links for SuperDocs changes
    """

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        session_manager: SessionManager,
        claim_repository: ClaimRepository,
        review_repository: Optional[ReviewRepository] = None,
        lineage_repository: Optional[LineageLinkRepository] = None
    ):
        self.client = superdocs_client
        self.session_manager = session_manager
        self.claim_repo = claim_repository
        self.review_repo = review_repository
        self.lineage_repo = lineage_repository

    async def sync_pending_changes(
        self,
        run_id: UUID,
        job_id: str,
        job_status: JobStatusResult,
        workspace_id: Optional[UUID] = None,
    ) -> List[UUID]:
        """
        Create a Review row + DocIntel Claims from SuperDocs pending_changes.

        The Review must be created BEFORE any Claims so that Claims can be linked
        to it via review_id — this is what makes them visible in the UI.

        Returns:
            List of created claim IDs
        """
        pending_changes = job_status.pending_changes

        if not pending_changes:
            logger.info("no_pending_changes", job_id=job_id)
            return []

        logger.info(
            "syncing_pending_changes",
            job_id=job_id,
            changes_count=len(pending_changes),
            run_id=str(run_id),
        )

        if not self.review_repo:
            raise ValueError(
                "ApprovalHandler requires review_repository to sync pending changes"
            )

        # Create a single Review row that groups all claims for this HITL pause.
        # workspace_id is required by the Review model — fall back to looking it
        # up from the run if not passed.
        effective_workspace_id = workspace_id or await self._get_workspace_id(run_id)

        if not effective_workspace_id:
            raise ValueError(
                f"Cannot create Review for run {run_id}: workspace_id not available"
            )

        review = await self.review_repo.create(
            workflow_run_id=run_id,
            workspace_id=effective_workspace_id,
            status="in_review",
        )

        logger.info(
            "review_row_created",
            review_id=str(review.id),
            run_id=str(run_id),
            job_id=job_id,
        )

        # Check for existing claims to ensure strict idempotency on change_id
        existing_claims = await self._get_claims_for_job(run_id, job_id)
        existing_cids = {}
        for c in existing_claims:
            cid = c.superdocs_change_id
            if not cid and c.content:
                try:
                    parsed = json.loads(c.content)
                    cid = parsed.get("superdocs_change_id") or parsed.get("change_id")
                except Exception:
                    pass
            if cid:
                existing_cids[str(cid)] = c.id

        claim_ids = []

        for change in pending_changes:
            cid_str = str(change.get("change_id", ""))
            if cid_str and cid_str in existing_cids:
                claim_ids.append(existing_cids[cid_str])
                continue

            claim_id = await self._create_claim_from_change(
                change=change,
                run_id=run_id,
                job_id=job_id,
                review_id=review.id,
            )
            if claim_id:
                claim_ids.append(claim_id)
                if cid_str:
                    existing_cids[cid_str] = claim_id

        logger.info(
            "pending_changes_synced",
            job_id=job_id,
            review_id=str(review.id),
            claims_created=len(claim_ids),
        )

        return claim_ids

    async def _create_claim_from_change(
        self,
        change: Dict[str, Any],
        run_id: UUID,
        job_id: str,
        review_id: UUID,
    ) -> Optional[UUID]:
        """Create DocIntel Claim from a SuperDocs change dict.

        SuperDocs field names (from plugin SKILL.md):
            change_id, chunk_id, old_html, new_html, ai_explanation
        """
        try:
            change_id = change.get("change_id", "")
            chunk_id = change.get("chunk_id", "")
            # SuperDocs uses old_html/new_html/ai_explanation — NOT proposed/current/description
            old_html = change.get("old_html", "")
            new_html = change.get("new_html", "")
            ai_explanation = change.get("ai_explanation", "Proposed document change")

            content = json.dumps({
                "superdocs_change_id": change_id,
                "chunk_id": chunk_id,
                "ai_explanation": ai_explanation,
                "old_html": old_html,
                "new_html": new_html,
            })

            claim = await self.claim_repo.create(
                workflow_run_id=run_id,
                review_id=review_id,
                claim_type="superdocs_change",
                content=content,
                original_content=content,
                status="pending",
                source_stage="superdocs_approval",
                superdocs_change_id=change_id,
                superdocs_job_id=job_id,
            )

            logger.info(
                "claim_created_from_change",
                claim_id=str(claim.id),
                change_id=change_id,
                review_id=str(review_id),
            )

            return claim.id

        except Exception as exc:
            logger.error(
                "failed_to_create_claim_from_change",
                change_id=change.get("change_id", "unknown"),
                error=str(exc),
            )
            # Re-raise so caller knows sync failed, rather than silently skipping a change
            raise

    async def apply_approvals(
        self,
        run_id: UUID,
        job_id: str
    ) -> Dict[str, int]:
        """
        Apply DocIntel claim decisions to SuperDocs.

        Optimized to submit all decisions in a single batch MCP tool call when possible,
        falling back to bounded concurrent requests if batching is not supported.

        Returns:
            {"approved": N, "rejected": M}
        """
        session_id = await self.session_manager.get_session_for_run(run_id)

        if not session_id:
            logger.error("no_session_for_approval", run_id=str(run_id))
            return {"approved": 0, "rejected": 0}

        claims = await self._get_claims_for_job(run_id, job_id)
        logger.info(f"[Review] total_claims={len(claims)}")

        approved_claims = [c for c in claims if c.status == "approved" and c.superdocs_change_id]
        rejected_claims = [c for c in claims if c.status == "rejected" and c.superdocs_change_id]
        actionable_claims = approved_claims + rejected_claims

        if not actionable_claims:
            logger.info("no_actionable_claims_for_approval", run_id=str(run_id), job_id=job_id)
            return {"approved": 0, "rejected": 0}

        for c in actionable_claims:
            logger.info(f"[SuperDocs] approval_submitted={c.superdocs_change_id}")

        # 1. Try Batch Decision Submission (1 MCP roundtrip for all decisions)
        batch_items = []
        for c in approved_claims:
            batch_items.append({"change_id": c.superdocs_change_id, "approved": True})
        for c in rejected_claims:
            batch_items.append({
                "change_id": c.superdocs_change_id,
                "approved": False,
                "feedback": "Change rejected by reviewer"
            })

        batch_success = False
        try:
            logger.info(f"[Review] Submitting batch approval for {len(batch_items)} decisions")
            await self.client.approve_change(
                session_id=session_id,
                job_id=job_id,
                approved=True,
                changes=batch_items
            )
            batch_success = True
            logger.info(f"[Review] Batch approval successful for {len(batch_items)} decisions")
            for item in batch_items:
                logger.info(f"[SuperDocs] approval_result=success change_id={item.get('change_id')}")
        except Exception as exc:
            logger.warning(
                f"[Review] Batch approval failed ({exc}), falling back to concurrent single calls",
                error=str(exc)
            )

        # 2. Fallback: Bounded concurrent execution if batch failed
        if not batch_success:
            sem = asyncio.Semaphore(10)

            async def _call_mcp_decision(claim: Claim, action: str):
                change_id = claim.superdocs_change_id
                if not change_id:
                    logger.warning("claim_missing_change_id", claim_id=str(claim.id))
                    logger.info(f"[SuperDocs] approval_result=failure change_id=None error=missing_change_id")
                    return claim, action, False, "missing_change_id"

                max_retries = 3
                last_err = None

                for attempt in range(max_retries):
                    try:
                        async with sem:
                            if action == "approved":
                                await self.client.approve_change(
                                    session_id=session_id,
                                    job_id=job_id,
                                    change_id=change_id,
                                    approved=True,
                                )
                            else:
                                await self.client.approve_change(
                                    session_id=session_id,
                                    job_id=job_id,
                                    change_id=change_id,
                                    approved=False,
                                    feedback="Change rejected by reviewer",
                                )
                        logger.info(f"[SuperDocs] approval_result=success change_id={change_id}")
                        return claim, action, True, None
                    except Exception as exc:
                        last_err = exc
                        if attempt < max_retries - 1:
                            backoff = 0.25 * (2 ** attempt)
                            await asyncio.sleep(backoff)

                logger.error(f"[Review] approval_failed={claim.id} error={str(last_err)}")
                logger.info(f"[SuperDocs] approval_result=failure change_id={change_id} error={str(last_err)}")
                return claim, action, False, str(last_err)

            tasks = [_call_mcp_decision(c, c.status) for c in actionable_claims]
            mcp_results = await asyncio.gather(*tasks)

            failed_claims = [(c, err) for c, _, success, err in mcp_results if not success]
            if failed_claims:
                failed_cids = [c.superdocs_change_id for c, _ in failed_claims]
                raise Exception(
                    f"SuperDocs approval submission failed for {len(failed_claims)} change(s): {failed_cids}"
                )

        # 3. Update local DB records and lineage
        approved_count = len(approved_claims)
        rejected_count = len(rejected_claims)

        # Update approved claims status
        if approved_claims:
            approved_ids = [c.id for c in approved_claims]
            if hasattr(self.claim_repo, "bulk_update_status"):
                await self.claim_repo.bulk_update_status(approved_ids, "applied")
            else:
                for c in approved_claims:
                    await self.claim_repo.update(c.id, status="applied")

            if self.lineage_repo:
                await self._create_lineage_links_bulk(approved_claims, session_id=session_id)

        # Update rejected claims status
        if rejected_claims:
            rejected_ids = [c.id for c in rejected_claims]
            if hasattr(self.claim_repo, "bulk_update_status"):
                await self.claim_repo.bulk_update_status(rejected_ids, "rejected_applied")
            else:
                for c in rejected_claims:
                    await self.claim_repo.update(c.id, status="rejected_applied")

        logger.info(f"[Review] local_approved={approved_count + rejected_count}")
        logger.info(f"[Review] local_failed=0")

        logger.info(
            "approvals_applied",
            run_id=str(run_id),
            job_id=job_id,
            approved=approved_count,
            rejected=rejected_count,
        )

        return {"approved": approved_count, "rejected": rejected_count}

    async def reconcile_pending_changes(
        self,
        run_id: UUID,
        job_id: str,
        pending_changes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Reconcile remote SuperDocs pending changes that appear during or after approval.

        For known claims:
          - If claim was approved locally -> re-submits approve_change (approved=True)
          - If claim was rejected locally -> re-submits approve_change (approved=False)
          - If claim is still pending -> signals escalation required
        For unknown changes (newly emerged from SuperDocs during pipeline):
          - Creates DocIntel Claims under the run's Review
          - Returns escalation_required=True so the stage can escalate for human review
        """
        session_id = await self.session_manager.get_session_for_run(run_id)
        if not session_id:
            logger.error("no_session_for_reconciliation", run_id=str(run_id))
            return {"escalation_required": False, "reconciled": 0}

        claims = await self._get_claims_for_job(run_id, job_id)
        
        def _extract_cid(c):
            if c.superdocs_change_id:
                return str(c.superdocs_change_id)
            if c.content:
                try:
                    data = json.loads(c.content)
                    cid_val = data.get("superdocs_change_id") or data.get("change_id")
                    if cid_val:
                        return str(cid_val)
                except Exception:
                    pass
            return None

        change_to_claim = {}
        for c in claims:
            extracted = _extract_cid(c)
            if extracted:
                change_to_claim[extracted] = c

        review = None
        if self.review_repo:
            if hasattr(self.review_repo, "list_by_run"):
                reviews = await self.review_repo.list_by_run(run_id)
                review = reviews[0] if reviews else None
            elif hasattr(self.review_repo, "list_by_workflow_run"):
                reviews = await self.review_repo.list_by_workflow_run(run_id)
                review = reviews[0] if reviews else None
            elif hasattr(self.review_repo, "get_by_workflow_run"):
                review = await self.review_repo.get_by_workflow_run(run_id)

        is_review_approved = review is not None and review.status == "approved"

        reconciled_count = 0
        new_pending_count = 0
        batch_reapply_items = []
        approved_to_update = []
        rejected_to_update = []

        for change in pending_changes:
            cid = change.get("change_id")
            if not cid:
                continue
            cid_str = str(cid)

            target_claim = change_to_claim.get(cid_str)
            if target_claim:
                if target_claim.status in ("approved", "applied"):
                    batch_reapply_items.append({"change_id": cid_str, "approved": True})
                    if target_claim.status != "applied":
                        approved_to_update.append(target_claim)
                    reconciled_count += 1
                elif target_claim.status in ("rejected", "rejected_applied"):
                    batch_reapply_items.append({
                        "change_id": cid_str,
                        "approved": False,
                        "feedback": "Change rejected by reviewer"
                    })
                    if target_claim.status != "rejected_applied":
                        rejected_to_update.append(target_claim)
                    reconciled_count += 1
                elif target_claim.status == "pending":
                    if is_review_approved:
                        batch_reapply_items.append({"change_id": cid_str, "approved": True})
                        approved_to_update.append(target_claim)
                        reconciled_count += 1
                    else:
                        logger.info(f"[SuperDocs] Claim {target_claim.id} for change_id={cid_str} is still pending human review")
                        new_pending_count += 1
            else:
                # Brand new change proposed by SuperDocs that wasn't in initial sync
                logger.info(f"[SuperDocs] new_remote_change={cid_str}")
                if self.review_repo:
                    if not review:
                        review = await self.review_repo.create(
                            workflow_run_id=run_id,
                            workspace_id=await self._get_workspace_id(run_id),
                            status="in_review",
                        )

                    # Check if claim already exists to prevent duplicate creation
                    existing_claim = None
                    if hasattr(self.claim_repo, "list_by_superdocs_job_id"):
                        job_claims = await self.claim_repo.list_by_superdocs_job_id(job_id)
                        existing_claim = next((c for c in job_claims if _extract_cid(c) == cid_str), None)
                    if not existing_claim:
                        existing_claim = next((c for c in claims if _extract_cid(c) == cid_str), None)

                    if not existing_claim:
                        new_claim_id = await self._create_claim_from_change(
                            change=change,
                            run_id=run_id,
                            job_id=job_id,
                            review_id=review.id,
                        )
                        if new_claim_id:
                            created = await self.claim_repo.get_by_id(new_claim_id)
                            target_claim = created
                            if created:
                                change_to_claim[cid_str] = created
                    else:
                        target_claim = existing_claim
                        change_to_claim[cid_str] = existing_claim

                    if is_review_approved and target_claim:
                        batch_reapply_items.append({"change_id": cid_str, "approved": True})
                        approved_to_update.append(target_claim)
                        reconciled_count += 1
                    else:
                        new_pending_count += 1
                else:
                    new_pending_count += 1

        # Submit batch re-applications
        if batch_reapply_items:
            for it in batch_reapply_items:
                logger.info(f"[SuperDocs] approval_submitted={it.get('change_id')}")

            try:
                logger.info(f"[SuperDocs] Re-applying decisions in batch for {len(batch_reapply_items)} change(s)")
                await self.client.approve_change(
                    session_id=session_id,
                    job_id=job_id,
                    approved=True,
                    changes=batch_reapply_items,
                )
                for it in batch_reapply_items:
                    logger.info(f"[SuperDocs] approval_result=success change_id={it.get('change_id')}")
            except Exception as exc:
                logger.warning(f"[SuperDocs] Batch re-application failed ({exc}), falling back to individual calls")
                sem = asyncio.Semaphore(10)
                async def _reapply_one(item):
                    try:
                        async with sem:
                            await self.client.approve_change(
                                session_id=session_id,
                                job_id=job_id,
                                change_id=item["change_id"],
                                approved=item["approved"],
                                feedback=item.get("feedback"),
                            )
                        logger.info(f"[SuperDocs] approval_result=success change_id={item.get('change_id')}")
                    except Exception as err:
                        logger.error(f"[SuperDocs] Failed to re-apply decision for {item['change_id']}: {err}")
                        logger.info(f"[SuperDocs] approval_result=failure change_id={item.get('change_id')} error={err}")

                await asyncio.gather(*[_reapply_one(it) for it in batch_reapply_items])

        # DB updates for reconciled claims
        if approved_to_update:
            if hasattr(self.claim_repo, "bulk_update_status"):
                await self.claim_repo.bulk_update_status([c.id for c in approved_to_update], "applied")
            else:
                for c in approved_to_update:
                    await self.claim_repo.update(c.id, status="applied")
            if self.lineage_repo:
                await self._create_lineage_links_bulk(approved_to_update, session_id=session_id)

        if rejected_to_update:
            if hasattr(self.claim_repo, "bulk_update_status"):
                await self.claim_repo.bulk_update_status([c.id for c in rejected_to_update], "rejected_applied")
            else:
                for c in rejected_to_update:
                    await self.claim_repo.update(c.id, status="rejected_applied")

        if new_pending_count > 0:
            return {
                "escalation_required": True,
                "new_claims_count": new_pending_count,
                "total_claims_count": len(claims) + new_pending_count,
                "reconciled": reconciled_count,
            }

        return {"escalation_required": False, "reconciled": reconciled_count}

    async def _get_claims_for_job(
        self,
        run_id: UUID,
        job_id: str
    ) -> List[Claim]:
        """Get all claims associated with a SuperDocs job and workflow run."""
        logger.info("getting_claims_for_job", job_id=job_id)
        claims_by_job = []
        if hasattr(self.claim_repo, "list_by_superdocs_job_id"):
            claims_by_job = await self.claim_repo.list_by_superdocs_job_id(job_id)
        
        all_run_claims = []
        if hasattr(self.claim_repo, "list_by_run"):
            all_run_claims = await self.claim_repo.list_by_run(run_id)
        elif hasattr(self.claim_repo, "list_by_workflow_run"):
            all_run_claims = await self.claim_repo.list_by_workflow_run(run_id)

        seen_ids = set()
        combined = []
        for c in claims_by_job:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                combined.append(c)
        for c in all_run_claims:
            if c.id not in seen_ids and c.claim_type == "superdocs_change":
                seen_ids.add(c.id)
                combined.append(c)
        return combined

    async def _get_workspace_id(self, run_id: UUID) -> Optional[UUID]:
        """Look up workspace_id for a workflow run."""
        from backend.database import async_session_maker
        from sqlalchemy import text

        async with async_session_maker() as db:
            result = await db.execute(
                text("SELECT workspace_id FROM workflow_runs WHERE id = :run_id"),
                {"run_id": run_id},
            )
            row = result.fetchone()
            return row[0] if row else None

    async def _approve_change(
        self,
        session_id: str,
        job_id: str,
        claim: Claim
    ) -> None:
        """Approve SuperDocs change and mark claim applied."""
        try:
            change_id = claim.superdocs_change_id

            if not change_id:
                logger.warning("claim_missing_change_id", claim_id=str(claim.id))
                return

            await self.client.approve_change(
                session_id=session_id,
                job_id=job_id,
                change_id=change_id,
                approved=True,
            )

            await self.claim_repo.update(claim.id, status="applied")

            if self.lineage_repo:
                await self._create_lineage_link(claim, session_id=session_id)

            logger.info("change_approved", claim_id=str(claim.id), change_id=change_id)

        except Exception as exc:
            logger.error(
                "failed_to_approve_change",
                claim_id=str(claim.id),
                error=str(exc),
            )

    async def _reject_change(
        self,
        session_id: str,
        job_id: str,
        claim: Claim
    ) -> None:
        """Reject SuperDocs change and mark claim rejected_applied."""
        try:
            change_id = claim.superdocs_change_id

            if not change_id:
                logger.warning("claim_missing_change_id", claim_id=str(claim.id))
                return

            await self.client.approve_change(
                session_id=session_id,
                job_id=job_id,
                change_id=change_id,
                approved=False,
                feedback="Change rejected by reviewer",
            )

            await self.claim_repo.update(claim.id, status="rejected_applied")

            logger.info("change_rejected", claim_id=str(claim.id), change_id=change_id)

        except Exception as exc:
            logger.error(
                "failed_to_reject_change",
                claim_id=str(claim.id),
                error=str(exc),
            )

    async def _create_lineage_link(
        self,
        claim: Claim,
        session_id: Optional[str] = None
    ) -> None:
        """Create lineage link capturing the full SuperDocs edit trail."""
        if not self.lineage_repo:
            return

        try:
            content = {}
            if claim.content:
                try:
                    content = json.loads(claim.content) if isinstance(claim.content, str) else claim.content
                except json.JSONDecodeError:
                    pass

            metadata = {
                "change_approved": True,
                "job_id": claim.superdocs_job_id,
                "change_id": claim.superdocs_change_id,
                "chunk_id": content.get("chunk_id"),
                "ai_explanation": content.get("ai_explanation"),
                "timestamp": claim.updated_at.isoformat() if claim.updated_at else None,
            }

            if session_id:
                metadata["session_id"] = session_id

            await self.lineage_repo.create_link(
                source_type="claim",
                source_id=claim.id,
                target_type="superdocs_change",
                target_id=claim.id,
                link_type="superdocs_edit",
                workflow_run_id=claim.workflow_run_id,
                stage_name="superdocs_approval",
                metadata=metadata,
            )

            logger.info(
                "lineage_link_created",
                claim_id=str(claim.id),
                change_id=claim.superdocs_change_id,
            )

        except Exception as exc:
            logger.error(
                "failed_to_create_lineage_link",
                claim_id=str(claim.id),
                error=str(exc),
            )

    async def _create_lineage_links_bulk(
        self,
        claims: List[Claim],
        session_id: Optional[str] = None
    ) -> None:
        """Create lineage links in bulk for multiple approved claims."""
        if not self.lineage_repo or not claims:
            return

        links_data = []
        for claim in claims:
            try:
                content = {}
                if claim.content:
                    try:
                        content = json.loads(claim.content) if isinstance(claim.content, str) else claim.content
                    except json.JSONDecodeError:
                        pass

                metadata = {
                    "change_approved": True,
                    "job_id": claim.superdocs_job_id,
                    "change_id": claim.superdocs_change_id,
                    "chunk_id": content.get("chunk_id"),
                    "ai_explanation": content.get("ai_explanation"),
                    "timestamp": claim.updated_at.isoformat() if claim.updated_at else None,
                }
                if session_id:
                    metadata["session_id"] = session_id

                links_data.append({
                    "source_type": "claim",
                    "source_id": claim.id,
                    "target_type": "superdocs_change",
                    "target_id": claim.id,
                    "link_type": "superdocs_edit",
                    "workflow_run_id": claim.workflow_run_id,
                    "stage_name": "superdocs_approval",
                    "metadata": metadata,
                })
            except Exception as exc:
                logger.error("failed_to_prepare_lineage_link", claim_id=str(claim.id), error=str(exc))

        if links_data:
            try:
                if hasattr(self.lineage_repo, "create_links_bulk"):
                    await self.lineage_repo.create_links_bulk(links_data)
                else:
                    for link_item in links_data:
                        await self.lineage_repo.create_link(**link_item)
            except Exception as exc:
                logger.error("failed_bulk_lineage_creation", error=str(exc))
