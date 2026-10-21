from typing import Dict, Any

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import RulingFactsList
from backend.modules.tariff.prompts_memo import EXTRACT_RULING_PROMPT
from backend.modules.tariff.llm_config import get_tariff_llm_model, get_tariff_llm_provider
from backend.core.llm.provider import LLMMessage
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ExtractRulingFactsStage(StageNode[TariffWorkflowState]):
    """Extract structured ruling facts from ruling documents."""

    def __init__(self):
        super().__init__("extract_ruling_facts")
        self.llm = get_tariff_llm_provider()

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        if not state.has_ruling_documents:
            logger.info("extract_ruling_skipped", reason="no_ruling_documents")
            return {"ruling_facts": [], "extract_ruling_completed": True}

        # Use loaded ruling content from ruling_content_map
        ruling_content_map = state.ruling_content_map
        if not ruling_content_map:
            logger.info("extract_ruling_skipped", reason="no_ruling_content")
            return {"ruling_facts": [], "extract_ruling_completed": True}

        all_ruling_facts = []

        # Extract facts from each ruling document separately
        for ruling_id, content in ruling_content_map.items():
            if not content.strip():
                continue

            logger.info("extracting_ruling_facts", ruling_id=ruling_id)

            prompt = EXTRACT_RULING_PROMPT.format(document_content=content)
            messages = [
                LLMMessage(role="system", content="Extract grounded ruling facts only."),
                LLMMessage(role="user", content=prompt),
            ]
            result = await self.llm.generate_structured(
                messages=messages,
                model=get_tariff_llm_model(),
                response_schema=RulingFactsList,
                temperature=0.2,
                max_tokens=4096,
            )

            # Tag each ruling fact with source document_id
            for ruling_fact in result.rulings:
                ruling_fact.document_id = ruling_id
                all_ruling_facts.append(ruling_fact)

            logger.info(
                "ruling_facts_extracted_from_document",
                ruling_id=ruling_id,
                count=len(result.rulings),
            )

        logger.info("all_ruling_facts_extracted", total_count=len(all_ruling_facts))
        return {"ruling_facts": all_ruling_facts, "extract_ruling_completed": True}
