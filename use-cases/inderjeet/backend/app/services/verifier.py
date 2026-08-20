import re
import logging
from typing import Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

# List of common adversarial prompt injection trigger words
SUSPICIOUS_PATTERNS = [
    r"ignore\s+prior\s+instructions",
    r"ignore\s+above\s+instructions",
    r"override\s+system",
    r"system\s+administrator",
    r"you\s+must\s+now",
    r"ignore\s+all\s+constraints",
    r"bypass\s+safety"
]

class VerificationError(Exception):
    """Custom exception raised when system verification fail criteria are hit."""
    pass

class SafetyVerifier:
    """
    Validation engine to enforce groundedness, budget guardrails,
    and prompt injection resistance.
    """
    @staticmethod
    def verify_groundedness(letter_text: str, traveler_name: str, flight_numbers: List[str]) -> bool:
        """
        Groundedness Check:
        Verifies that any traveler names or flight numbers mentioned in output documents
        must exactly match database manifest records (honesty over fabrication).
        """
        # If traveler name isn't mentioned correctly, flag error
        # (Case-insensitive check for names)
        name_parts = traveler_name.lower().split()
        for part in name_parts:
            if len(part) > 2 and part not in letter_text.lower():
                logger.warning(f"Groundedness fail: Passenger name part '{part}' not found in letter output.")
                return False

        # Extract all flight-looking references in letter text (e.g. AA123, BA789)
        found_flights = re.findall(r"\b[A-Z]{2}\d{3,4}\b", letter_text.upper())
        for flight in found_flights:
            if flight not in [f.upper() for f in flight_numbers]:
                logger.warning(f"Groundedness fail: Hallucinated flight '{flight}' detected in letter output.")
                return False

        return True

    @staticmethod
    def verify_no_injection(input_text: str) -> bool:
        """
        Prompt Injection Guard:
        Inspects unstructured passenger addresses, names, or remarks for instructions
        aimed at overriding system logic.
        """
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, input_text, re.IGNORECASE):
                logger.warning(f"Safety Violation: Prompt injection pattern matches for input: {input_text}")
                return False
        return True

    @staticmethod
    def check_operation_budget(current_spent_usd: float, op_count: int) -> bool:
        """
        Budget limit check:
        Guarantees batch runs degrade gracefully when nearing max allowance boundaries.
        """
        if current_spent_usd >= settings.BUDGET_LIMIT_USD:
            logger.error("Budget limit reached: Operations blocked.")
            return False
        if op_count >= settings.STOPPING_RULE_MAX_OP:
            logger.error("Max operations budget exceeded: Operations blocked.")
            return False
        return True
