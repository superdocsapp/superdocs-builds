from typing import Any, Dict, List, Optional
from backend.core.workflow.stage import StageNode
from backend.core.llm.provider import LLMProvider
from backend.modules.screenplay.schemas import (
    ParsedScreenplay, ScreenplayElement, FormattingItem, as_state_dict,
)
from backend.modules.screenplay.formatter import format_element
from backend.modules.screenplay.validator import ContentDriftValidator
from backend.modules.screenplay.llm_config import get_screenplay_llm_provider, get_screenplay_llm_model
from backend.repositories.screenplay import FormattingItemRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class FormatStage(StageNode):
    """Apply per-element formatting rules. Persist FormattingItems to DB."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None, formatting_item_repo: Optional[FormattingItemRepository] = None,
                 model: Optional[str] = None):
        super().__init__(name="format")
        self.llm = llm_provider if llm_provider is not None else get_screenplay_llm_provider()
        self.repo = formatting_item_repo
        self.model = model if model is not None else get_screenplay_llm_model()
        self._validator = ContentDriftValidator()

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        state = as_state_dict(state)
        parsed_data = state.get("parsed_screenplay")
        if not parsed_data:
            logger.warning("format_stage_no_parsed_data")
            return {"formatting_items": []}

        if isinstance(parsed_data, dict):
            parsed = ParsedScreenplay(**parsed_data)
        else:
            parsed = parsed_data

        run_id = state.get("workflow_run_id")
        formatting_items: List[Dict[str, Any]] = []

        for element in parsed.elements:
            item = await self._format_one(element, run_id)
            formatting_items.append(item)

        logger.info("format_stage_complete", item_count=len(formatting_items))
        return {"formatting_items": formatting_items}

    async def _format_one(self, element: ScreenplayElement, run_id: str) -> Dict[str, Any]:
        try:
            formatted_text, change_type, reason = format_element(element.element_type, element.content)

            # Drift check
            drift = self._validator.has_drift(element.content, formatted_text, element.element_type)
            if drift:
                logger.warning("content_drift_detected", element_index=element.element_index,
                               element_type=element.element_type)
                formatted_text = element.content
                change_type = "no_change"
            is_change = (change_type != "no_change" and formatted_text != element.content)
            status = "pending" if is_change else "approved"
            clean_reason = reason if is_change else ""

            item = FormattingItem(
                element_index=element.element_index,
                element_type=element.element_type,
                scene_number=element.scene_number,
                character_name=element.character_name,
                original_text=element.content,
                formatted_text=formatted_text,
                change_type=change_type,
                reason=clean_reason,
                content_drift=drift,
                confidence_score=element.confidence,
                status=status,
            )

            # Persist to DB
            from uuid import UUID
            db_item = await self.repo.create(
                workflow_run_id=UUID(run_id),
                element_index=item.element_index,
                element_type=item.element_type,
                scene_number=item.scene_number,
                character_name=item.character_name,
                original_text=item.original_text,
                formatted_text=item.formatted_text,
                change_type=item.change_type,
                reason=item.reason,
                content_drift=item.content_drift,
                confidence_score=item.confidence_score,
                status=status,
            )
            item_dict = item.model_dump()
            item_dict["id"] = str(db_item.id)
            return item_dict

        except Exception as e:
            logger.error("format_one_failed", element_index=element.element_index, error=str(e))
            # Fallback: no-change item
            return FormattingItem(
                element_index=element.element_index,
                element_type=element.element_type,
                original_text=element.content,
                formatted_text=element.content,
                change_type="no_change",
                reason=f"Formatting failed: {e}",
            ).model_dump()
