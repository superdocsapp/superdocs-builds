from typing import Any, Dict, List, Optional
from uuid import UUID
from backend.core.workflow.stage import StageNode
from backend.core.llm.provider import LLMProvider, LLMMessage
from backend.modules.screenplay.formatter import format_element
from backend.modules.screenplay.validator import ContentDriftValidator
from backend.modules.screenplay.diff import compute_diff_tokens
from backend.modules.screenplay.schemas import as_state_dict
from backend.modules.screenplay.llm_config import get_screenplay_llm_provider, get_screenplay_llm_model
from backend.repositories.screenplay import FormattingItemRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class RegenerateStage(StageNode):
    """Re-format rejected FormattingItems. Approved items are never touched."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None, formatting_item_repo: Optional[FormattingItemRepository] = None,
                 model: Optional[str] = None):
        super().__init__(name="regenerate")
        self.llm = llm_provider if llm_provider is not None else get_screenplay_llm_provider()
        self.repo = formatting_item_repo
        self.model = model if model is not None else get_screenplay_llm_model()
        self._validator = ContentDriftValidator()

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        state = as_state_dict(state)
        items: List[Dict[str, Any]] = state.get("formatting_items", [])
        updated: List[Dict[str, Any]] = []

        for item in items:
            if item.get("status") != "rejected":
                updated.append(item)
                continue

            regenerated = await self._regenerate_one(item)
            updated.append(regenerated)

        regeneration_count = state.get("regeneration_count", 0) + 1
        logger.info("regenerate_stage_complete",
                    total=len(items),
                    regenerated=sum(1 for i in updated if i.get("status") == "pending"))
        return {"formatting_items": updated, "regeneration_count": regeneration_count}

    async def _regenerate_one(self, item: Dict[str, Any]) -> Dict[str, Any]:
        element_type = item.get("element_type", "action")
        original_text = item.get("original_text", "")
        reviewer_comment = item.get("reviewer_comment", "")

        # For deterministically-formattable types, re-apply rules
        formatted_text, change_type, reason = format_element(element_type, original_text)

        # If reviewer left a comment, ask LLM to incorporate it
        if reviewer_comment:
            try:
                prompt = (
                    f"Reformat this screenplay {element_type} according to industry standards.\n"
                    f"Reviewer comment: {reviewer_comment}\n"
                    f"Original text: {original_text}\n"
                    f"Rules: preserve all words exactly; only change formatting/capitalisation.\n"
                    f"Return ONLY the reformatted text, nothing else."
                )
                response = await self.llm.generate(
                    messages=[LLMMessage(role="user", content=prompt)],
                    model=self.model,
                )
                candidate = response.content.strip()
                if not self._validator.has_drift(original_text, candidate, element_type):
                    formatted_text = candidate
                    reason = f"Regenerated with reviewer comment: {reviewer_comment}"
            except Exception as e:
                logger.warning("regenerate_llm_failed", element_index=item.get("element_index"), error=str(e))

        drift = self._validator.has_drift(original_text, formatted_text, element_type)
        if drift:
            formatted_text = original_text
            change_type = "no_change"

        diff_tokens = compute_diff_tokens(original_text, formatted_text)

        updated_item = dict(item)
        updated_item.update({
            "formatted_text": formatted_text,
            "change_type": change_type,
            "reason": reason,
            "diff_tokens": diff_tokens,
            "content_drift": drift,
            "status": "pending",  # reset for re-review
            "reviewer_comment": None,
        })

        # Persist
        item_id = item.get("id")
        if item_id and self.repo:
            try:
                await self.repo.update(
                    UUID(item_id),
                    formatted_text=formatted_text,
                    change_type=change_type,
                    reason=reason,
                    diff_tokens=diff_tokens,
                    content_drift=drift,
                    status="pending",
                    reviewer_comment=None,
                )
            except Exception as e:
                logger.warning("regenerate_db_update_failed", item_id=item_id, error=str(e))

        return updated_item
