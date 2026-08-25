from typing import Dict, Any, List
from pydantic import BaseModel
from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState, TariffClaim
from backend.modules.tariff.prompts import EXTRACT_PROMPT
from backend.modules.tariff.llm_config import get_tariff_llm_model, get_tariff_llm_provider
from backend.core.llm.provider import LLMMessage
from backend.logging_config import get_logger

logger = get_logger(__name__)


class TariffClaimsResponse(BaseModel):
    """Schema for structured extraction response"""
    claims: List[TariffClaim]


class ExtractStage(StageNode[TariffWorkflowState]):
    """
    Extract tariff claims from document content using LLM.
    """

    def __init__(self):
        super().__init__("extract")
        self.llm = get_tariff_llm_provider()

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """Extract tariff claims from document"""
        logger.info("extracting_tariff_claims", document_id=state.document_id)

        if not state.document_content:
            raise ValueError("No document content provided")

        # Format prompt with document content
        prompt = EXTRACT_PROMPT.format(document_content=state.document_content)

        # Create messages for LLM
        messages = [
            LLMMessage(role="system", content="You are a tariff classification expert."),
            LLMMessage(role="user", content=prompt)
        ]

        # Call LLM with structured output
        result = await self.llm.generate_structured(
            messages=messages,
            model=get_tariff_llm_model(),
            response_schema=TariffClaimsResponse,
            temperature=0.3
        )

        # Extract claims from response
        claims = result.claims

        logger.info("extracted_claims", count=len(claims))

        return {
            "extracted_claims": claims,
            "extract_completed": True
        }
