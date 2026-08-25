from typing import Dict, Any

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import ProductFacts
from backend.modules.tariff.prompts_memo import EXTRACT_PRODUCT_PROMPT
from backend.modules.tariff.llm_config import get_tariff_llm_model, get_tariff_llm_provider
from backend.core.llm.provider import LLMMessage
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ExtractProductFactsStage(StageNode[TariffWorkflowState]):
    """Extract structured product facts from document content."""

    def __init__(self):
        super().__init__("extract_product_facts")
        self.llm = get_tariff_llm_provider()

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        # Use product_spec_content if available, otherwise fall back to document_content
        content = state.product_spec_content or state.document_content

        if not content:
            raise ValueError("No document content provided for product fact extraction")

        prompt = EXTRACT_PRODUCT_PROMPT.format(document_content=content)
        if state.prior_knowledge:
            prompt += f"\n\nPrior knowledge context:\n{state.prior_knowledge}"

        messages = [
            LLMMessage(role="system", content="You extract grounded product facts. Never fabricate data."),
            LLMMessage(role="user", content=prompt),
        ]
        facts = await self.llm.generate_structured(
            messages=messages,
            model=get_tariff_llm_model(),
            response_schema=ProductFacts,
            temperature=0.2,
            max_tokens=3000,
        )
        logger.info("product_facts_extracted", product_name=facts.product_name)
        return {"product_facts": facts, "extract_product_completed": True}
