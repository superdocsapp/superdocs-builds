from typing import Any, Dict, List
from uuid import UUID
from backend.core.workflow.stage import StageNode
from backend.modules.screenplay.diff import compute_diff_tokens
from backend.modules.screenplay.schemas import as_state_dict
from backend.repositories.screenplay import FormattingItemRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class DiffStage(StageNode):
    """Compute per-element diff tokens. Create Review record. Set run awaiting_review."""

    def __init__(self, formatting_item_repo: FormattingItemRepository,
                 review_repo, run_repo):
        super().__init__(name="diff")
        self.repo = formatting_item_repo
        self.review_repo = review_repo
        self.run_repo = run_repo

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        state = as_state_dict(state)
        items: List[Dict[str, Any]] = state.get("formatting_items", [])
        run_id = state.get("workflow_run_id")
        workspace_id = state.get("workspace_id")

        updated_items = []
        for item in items:
            tokens = compute_diff_tokens(
                item.get("original_text", ""),
                item.get("formatted_text", ""),
            )
            item = dict(item)
            item["diff_tokens"] = tokens

            # Update DB record if it has an id
            item_id = item.get("id")
            if item_id and self.repo:
                try:
                    await self.repo.update(UUID(item_id), diff_tokens=tokens)
                except Exception as e:
                    logger.warning("diff_db_update_failed", item_id=item_id, error=str(e))

            updated_items.append(item)

        # Create Review record
        review_id = None
        if self.review_repo and run_id and workspace_id:
            try:
                review = await self.review_repo.create(
                    workflow_run_id=UUID(run_id),
                    workspace_id=UUID(workspace_id),
                    status="in_review",
                )
                review_id = str(review.id)
                # Attach review_id to all items
                if self.repo:
                    await self.repo.attach_review(UUID(run_id), review.id)
            except Exception as e:
                logger.error("diff_stage_review_creation_failed", error=str(e))

        # Update run status to awaiting_review
        if self.run_repo and run_id:
            try:
                await self.run_repo.update(UUID(run_id), status="awaiting_review")
            except Exception as e:
                logger.warning("diff_stage_run_status_update_failed", error=str(e))

        logger.info("diff_stage_complete", item_count=len(updated_items), review_id=review_id)
        return {
            "formatting_items": updated_items,
            "diff_available": True,
        }
