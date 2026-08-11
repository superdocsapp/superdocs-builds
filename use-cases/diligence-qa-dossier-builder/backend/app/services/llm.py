import re
import uuid
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel

from backend.app.config import settings

class LLMResponse(BaseModel):
    answer: str
    confidence: float  # LLM self-confidence (0.0 to 1.0)
    supporting_evidence_ids: List[str]  # Chunks supporting the claim
    contradicting_evidence_ids: List[str]  # Chunks contradicting the claim
    reasoning_summary: str

class LLMService(ABC):
    @abstractmethod
    async def generate_structured_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None
    ) -> LLMResponse:
        """Generate structured response from the LLM."""
        pass

class MockLLMService(LLMService):
    async def generate_structured_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None
    ) -> LLMResponse:
        """
        Mock implementation of LLM generation. Parses instructions and
        returns predictable structures based on context triggers.
        """
        # Find UUIDs in prompt to map citations
        chunk_ids = re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", prompt)

        # 1. Test malformed JSON parsing failures
        if "malformed_json_trigger" in prompt:
            raise ValueError("LLM returned non-JSON string: 'internal server error'")

        # 2. Test missing required fields validation
        if "missing_fields_trigger" in prompt:
            raise ValueError("LLM response is missing required field 'reasoning_summary'")

        # 3. Test unknown/fabricated citation IDs
        if "unknown_id_trigger" in prompt:
            fake_id = str(uuid.uuid4())
            return LLMResponse(
                answer="Mocked compliance answer with fabricated citation.",
                confidence=0.85,
                supporting_evidence_ids=[fake_id],
                contradicting_evidence_ids=[],
                reasoning_summary="Includes a random citation ID not present in retrieved context."
            )

        # 4. Test prompt injection shielding
        if any(trigger in prompt for trigger in ["Ignore previous", "override system", "say the company has $100M", "Reveal secrets"]):
            # Extract question text from prompt to identify target question intent
            q_match = re.search(r"Question:\s*([^\n]+)", prompt, re.IGNORECASE)
            question = q_match.group(1).strip().lower() if q_match else ""
            
            # Ignore the malicious instruction and answer based on real data room facts in prompt
            answer = "Grounded diligence information."
            if "john doe owns 55%" in question or "john doe" in question:
                answer = "The cap table indicates that founder John Doe owns 55% of the shares."
            elif "posture" in question:
                answer = "SuperDocs security posture relies on SOC2 Type II compliance."
            elif "revenue" in question or "arr" in question:
                answer = "Annual recurring revenue was $2.4M in FY2025."
                
            return LLMResponse(
                answer=answer,
                confidence=0.90,
                supporting_evidence_ids=chunk_ids[:1] if chunk_ids else [],
                contradicting_evidence_ids=[],
                reasoning_summary="Treated instruction override text as untrusted data context only."
            )

        # 5. Test security category
        if "SOC2" in prompt or "security" in prompt:
            return LLMResponse(
                answer="SuperDocs uses SOC2 Type II compliance, ISO 27001 audit protocols, and AES-256 data encryption.",
                confidence=0.95,
                supporting_evidence_ids=chunk_ids[:2] if chunk_ids else [],
                contradicting_evidence_ids=[],
                reasoning_summary="Security parameters verified in compliance document chunks."
            )

        # 6. Test conflict revenue category
        if "revenue" in prompt or "ARR" in prompt:
            if "$2.4M" in prompt and "$3.1M" in prompt:
                # Return conflict analysis citation mapping
                return LLMResponse(
                    answer="Contradiction identified: Financials.pdf states 2025 revenue was $2.4M while Investor_Presentation.pdf states it was $3.1M.",
                    confidence=0.50,
                    supporting_evidence_ids=[chunk_ids[0]] if len(chunk_ids) > 0 else [],
                    contradicting_evidence_ids=[chunk_ids[1]] if len(chunk_ids) > 1 else [],
                    reasoning_summary="Direct conflict on 2025 revenue figures detected between Financials.pdf and Investor_Presentation.pdf."
                )

        # Default fallback response
        return LLMResponse(
            answer="Grounded diligence details retrieved successfully.",
            confidence=0.80,
            supporting_evidence_ids=chunk_ids if chunk_ids else [],
            contradicting_evidence_ids=[],
            reasoning_summary="Extracted from source data room document chunks."
        )

def get_llm_service() -> LLMService:
    """
    Factory function loading the LLM service configuration.
    """
    # For Phase 3, default is mock
    return MockLLMService()
