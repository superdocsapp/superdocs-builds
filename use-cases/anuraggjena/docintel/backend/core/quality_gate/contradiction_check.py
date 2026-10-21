from typing import Any, Dict, List

from pydantic import BaseModel

from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus, CheckSeverity
from backend.core.llm.provider import LLMProvider, LLMMessage
from backend.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "llama3-8b-8192"


class ContradictionResult(BaseModel):
    has_contradictions: bool
    contradictions: List[Dict[str, str]]  # [{"claim_a": "...", "claim_b": "...", "reason": "..."}]
    confidence: float  # 0.0–1.0


class ContradictionCheck(BaseCheck):
    name = "contradiction_detection"
    severity = CheckSeverity.ERROR
    blocking = True

    def __init__(self, llm_provider: LLMProvider, model: str = DEFAULT_MODEL):
        self.llm = llm_provider
        self.model = model

    async def run(self, state: Dict[str, Any], config: Dict[str, Any]) -> CheckResult:
        # Support both dict and Pydantic model state
        claims = state.get("claims", []) if isinstance(state, dict) else getattr(state, "claims", [])

        # Need at least 2 claims to check for contradictions
        if len(claims) < 2:
            return self.skip(f"Only {len(claims)} claim(s); need at least 2 for contradiction detection")

        # Build prompt with claim contents
        claim_texts = []
        for i, claim in enumerate(claims):
            content = claim.get("content", "") if isinstance(claim, dict) else str(claim)
            claim_texts.append(f"Claim {i + 1}: {content}")

        claims_block = "\n".join(claim_texts)

        prompt = f"""You are a fact-checking assistant. Review these claims and identify any contradictions.

Claims:
{claims_block}

Analyze whether any claims directly contradict each other. A contradiction is when two claims make incompatible factual assertions.

Respond with JSON in this exact format:
{{
  "has_contradictions": true/false,
  "contradictions": [
    {{"claim_a": "text of first claim", "claim_b": "text of second claim", "reason": "why they contradict"}}
  ],
  "confidence": 0.0-1.0
}}

If no contradictions, return an empty contradictions array."""

        messages = [LLMMessage(role="user", content=prompt)]

        try:
            contradiction_data: ContradictionResult = await self.llm.generate_structured(
                messages=messages,
                model=self.model,
                response_schema=ContradictionResult,
            )

            if not contradiction_data.has_contradictions:
                return self.passed(
                    f"No contradictions detected across {len(claims)} claims",
                    {"claims_checked": len(claims), "confidence": contradiction_data.confidence},
                )

            return self.failed(
                f"Found {len(contradiction_data.contradictions)} contradiction(s)",
                {
                    "contradictions": contradiction_data.contradictions,
                    "claims_checked": len(claims),
                    "confidence": contradiction_data.confidence,
                },
            )

        except Exception as e:
            logger.error("contradiction_check_error", error=str(e))
            return self.warning(
                f"Contradiction check could not complete: {e}",
                {"error": str(e)},
            )
