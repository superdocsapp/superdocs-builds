"""
ReplayService: Reconstructs execution timelines from checkpoint data.

This service reads WorkflowStage records and their checkpoint_data to rebuild
a complete timeline showing how a workflow run or claim was executed, including
inputs, outputs, and timing information.
"""

import json
from typing import List
from uuid import UUID

from backend.core.lineage.models import ReplayTimeline, ReplayStage
from backend.repositories.base import BaseRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ReplayService:
    """Service for reconstructing execution timeline from checkpoints"""

    def __init__(
        self,
        stage_repo: BaseRepository,
        lineage_service,  # LineageService (avoid circular import)
        run_repo: BaseRepository,
    ):
        self.stage_repo = stage_repo
        self.lineage_service = lineage_service
        self.run_repo = run_repo

    async def replay_run_execution(self, run_id: UUID) -> ReplayTimeline:
        """
        Reconstruct entire workflow run execution.

        Reads all WorkflowStage records for the run and parses their
        checkpoint_data to build a complete timeline showing:
        - Stage execution order
        - Stage inputs/outputs
        - Execution timing
        - Status of each stage

        This is deterministic reconstruction from stored state, NOT
        re-execution with LLMs.

        Args:
            run_id: UUID of the workflow run to replay

        Returns:
            ReplayTimeline with all stages and their data

        Raises:
            ValueError: If the workflow run is not found
        """
        logger.info("replaying_run_execution", run_id=str(run_id))

        # Get workflow run
        run = await self.run_repo.get_by_id(run_id)
        if not run:
            raise ValueError(f"WorkflowRun {run_id} not found")

        # Get all stages for this run (ordered by created_at)
        stages = await self.stage_repo.list_by_run(run_id)

        replay_stages = []
        for stage in stages:
            # Parse checkpoint_data
            inputs = {}
            outputs = {}
            if stage.checkpoint_data:
                try:
                    # checkpoint_data may be string JSON or already a dict
                    if isinstance(stage.checkpoint_data, str):
                        checkpoint = json.loads(stage.checkpoint_data)
                    else:
                        checkpoint = stage.checkpoint_data

                    # Full checkpoint is treated as outputs
                    # (inputs would need to be explicitly stored separately)
                    outputs = checkpoint

                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        "failed_to_parse_checkpoint",
                        stage=stage.stage_name,
                        error=str(e)
                    )

            replay_stage = ReplayStage(
                stage_name=stage.stage_name,
                status=stage.status,
                started_at=stage.started_at.isoformat() if stage.started_at else None,
                completed_at=stage.completed_at.isoformat() if stage.completed_at else None,
                execution_time_ms=stage.execution_time_ms,
                inputs=inputs,
                outputs=outputs,
                contributed_to_claim=False  # Will be determined in replay_claim_execution
            )
            replay_stages.append(replay_stage)

        # Get knowledge reuse info and Phase 7 lineage (from lineage_links)
        knowledge_reused = []
        phase7_events = []
        try:
            knowledge_links = await self.lineage_service.lineage_link_repo.get_links_by_run(run_id)

            for link in knowledge_links:
                if link.link_type == "derived_from_knowledge":
                    # Resolve the knowledge entry
                    knowledge = await self.lineage_service.knowledge_repo.get_by_id(link.target_id)
                    if knowledge:
                        knowledge_reused.append({
                            "knowledge_entry_id": str(link.target_id),
                            "claim_id": str(link.source_id),
                            "stage_name": link.stage_name,
                            "content_preview": knowledge.content[:100] if knowledge.content else "",
                            "entry_type": knowledge.entry_type,
                            "source_run_id": str(knowledge.source_run_id) if knowledge.source_run_id else None,
                            "metadata": link.link_metadata or {}
                        })

                # Phase 7 events
                elif link.link_type == "reused_from_baseline":
                    phase7_events.append({
                        "type": "baseline_reuse",
                        "claim_id": str(link.source_id),
                        "baseline_claim_id": str(link.target_id),
                        "stage_name": link.stage_name,
                        "metadata": link.link_metadata or {}
                    })

                elif link.link_type == "superseded_by":
                    phase7_events.append({
                        "type": "supersession",
                        "new_claim_id": str(link.source_id),
                        "old_claim_id": str(link.target_id),
                        "stage_name": link.stage_name,
                        "metadata": link.link_metadata or {}
                    })

                elif link.link_type == "contradicts":
                    phase7_events.append({
                        "type": "contradiction",
                        "new_claim_id": str(link.source_id),
                        "baseline_claim_id": str(link.target_id),
                        "stage_name": link.stage_name,
                        "field": link.link_metadata.get("field") if link.link_metadata else None,
                        "baseline_value": link.link_metadata.get("baseline_value") if link.link_metadata else None,
                        "new_value": link.link_metadata.get("new_value") if link.link_metadata else None,
                        "metadata": link.link_metadata or {}
                    })

                elif link.link_type == "superdocs_edit":
                    phase7_events.append({
                        "type": "superdocs_edit",
                        "claim_id": str(link.source_id),
                        "stage_name": link.stage_name,
                        "change_id": link.link_metadata.get("change_id") if link.link_metadata else None,
                        "job_id": link.link_metadata.get("job_id") if link.link_metadata else None,
                        "session_id": link.link_metadata.get("session_id") if link.link_metadata else None,
                        "description": link.link_metadata.get("description") if link.link_metadata else None,
                        "metadata": link.link_metadata or {}
                    })
        except Exception as e:
            logger.warning("failed_to_get_lineage_events", run_id=str(run_id), error=str(e))

        # Get review decisions
        review_decisions = []
        try:
            # Get claims for this run to find associated reviews
            claims = await self.lineage_service.claim_repo.list_by_run(run_id)

            seen_reviews = set()
            for claim in claims:
                if claim.review_id and claim.review_id not in seen_reviews:
                    review = await self.lineage_service.review_repo.get_by_id(claim.review_id)
                    if review:
                        seen_reviews.add(claim.review_id)
                        review_decisions.append({
                            "review_id": str(review.id),
                            "status": review.status,
                            "reviewer_id": review.reviewer_id,
                            "notes": review.notes,
                            "created_at": review.created_at.isoformat() if review.created_at else None,
                            "updated_at": review.updated_at.isoformat() if review.updated_at else None
                        })

                # Add claim-level decisions
                if claim.status in ["approved", "rejected"]:
                    review_decisions.append({
                        "claim_id": str(claim.id),
                        "action": claim.status,
                        "content_preview": claim.content[:100] if claim.content else "",
                        "source_stage": claim.source_stage
                    })

        except Exception as e:
            logger.warning("failed_to_get_review_decisions", run_id=str(run_id), error=str(e))

        return ReplayTimeline(
            run_id=run_id,
            stages=replay_stages,
            knowledge_reused=knowledge_reused,
            review_decisions=review_decisions,
            phase7_events=phase7_events
        )

    async def replay_claim_execution(self, claim_id: UUID) -> ReplayTimeline:
        """
        Reconstruct how a specific claim was produced.

        Replays the full run execution and highlights stages that
        contributed to this specific claim's creation.

        Args:
            claim_id: UUID of the claim to replay

        Returns:
            ReplayTimeline with contributed stages highlighted

        Raises:
            ValueError: If the claim is not found
        """
        logger.info("replaying_claim_execution", claim_id=str(claim_id))

        # Get the claim to find its workflow_run_id
        claim = await self.lineage_service.claim_repo.get_by_id(claim_id)
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        # Replay the full run execution
        timeline = await self.replay_run_execution(claim.workflow_run_id)

        # Identify stages that contributed to this claim
        claim_id_str = str(claim_id)

        for stage in timeline.stages:
            # Check if this stage's outputs contain the claim_id
            if stage.outputs:
                claim_ids = stage.outputs.get("claim_ids", [])
                if isinstance(claim_ids, list) and claim_id_str in claim_ids:
                    stage.contributed_to_claim = True
                    logger.debug(
                        "stage_contributed_to_claim",
                        stage=stage.stage_name,
                        claim_id=claim_id_str
                    )

        logger.info(
            "claim_execution_replayed",
            claim_id=claim_id_str,
            run_id=str(claim.workflow_run_id),
            contributing_stages=sum(1 for s in timeline.stages if s.contributed_to_claim)
        )

        return timeline
