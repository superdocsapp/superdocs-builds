from dataclasses import dataclass
from .schemas import ExtractedFact, FindingType

@dataclass(frozen=True)
class ContinuityResult:
    type: FindingType
    explanation: str
    confidence: float
    severity: str

class ContinuityService:
    """Deterministic rules applied only to pre-retrieved candidate facts."""
    def compare(self, existing: ExtractedFact | None, new: ExtractedFact) -> ContinuityResult:
        if existing is None:
            return ContinuityResult(FindingType.NEW_INFORMATION, "No established fact conflicts.", new.confidence, "LOW")
        if existing.entity.casefold() != new.entity.casefold() or existing.attribute.casefold() != new.attribute.casefold():
            return ContinuityResult(FindingType.NEW_INFORMATION, "The facts concern different claims.", new.confidence, "LOW")
        if existing.value.casefold().strip() == new.value.casefold().strip():
            return ContinuityResult(FindingType.COMPATIBLE_UPDATE, "The new statement agrees with the Bible.", min(existing.confidence, new.confidence), "LOW")
        confidence = min(existing.confidence, new.confidence)
        if not existing.supported or not new.supported or confidence < 0.75:
            return ContinuityResult(FindingType.POSSIBLE_CONTRADICTION, "Values differ, but grounding is uncertain.", confidence, "MEDIUM")
        return ContinuityResult(FindingType.CONTRADICTION, f"Established value '{existing.value}' conflicts with new value '{new.value}'.", confidence, "HIGH")
