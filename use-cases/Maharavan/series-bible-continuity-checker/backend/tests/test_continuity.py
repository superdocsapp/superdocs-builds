from uuid import uuid4
import pytest
from pydantic import ValidationError
from series_bible.domain.continuity import ContinuityService
from series_bible.domain.schemas import ExtractedFact, FactKind, FindingType, SourceRef

def fact(value: str, confidence: float = .95) -> ExtractedFact:
    return ExtractedFact(kind=FactKind.CHARACTER, entity="Elena", attribute="eye_color", value=value, confidence=confidence, source=SourceRef(document_id=uuid4(), chapter="Chapter 1", chunk_id="chunk-1", evidence_text=f"Elena has {value} eyes."))

def test_detects_grounded_contradiction():
    result = ContinuityService().compare(fact("blue"), fact("green"))
    assert result.type is FindingType.CONTRADICTION
    assert result.severity == "HIGH"

def test_same_value_is_compatible():
    assert ContinuityService().compare(fact("blue"), fact("BLUE")).type is FindingType.COMPATIBLE_UPDATE

def test_ungrounded_fact_is_rejected_by_strict_schema():
    with pytest.raises(ValidationError):
        SourceRef(document_id=uuid4(), chapter="Chapter 1", chunk_id="x", evidence_text="")
