from uuid import uuid4

from series_bible.domain.continuity import ContinuityService
from series_bible.domain.schemas import ExtractedFact, FactKind, FindingType, SourceRef
from series_bible.application.run_service import WorkflowRunner


def test_conflicting_facts_from_the_same_chapter_are_detected():
    document_id = uuid4()
    source = lambda chunk, value: SourceRef(
        document_id=document_id, chapter="Chapter 1", chunk_id=chunk,
        evidence_text=f"Elena has {value} eyes.",
    )
    blue = ExtractedFact(kind=FactKind.CHARACTER, entity="Elena", attribute="eye_color", value="blue", confidence=.95, source=source("chunk-1", "blue"))
    green = ExtractedFact(kind=FactKind.CHARACTER, entity="Elena", attribute="eye_color", value="green", confidence=.95, source=source("chunk-2", "green"))
    assert ContinuityService().compare(blue, green).type is FindingType.CONTRADICTION


def test_workflow_compares_every_conflicting_pair_in_one_chapter():
    document_id = uuid4()
    def fact(value: str, chunk: str) -> ExtractedFact:
        return ExtractedFact(
            kind=FactKind.CHARACTER, entity="Elena", attribute="eye_color", value=value,
            confidence=.95, source=SourceRef(document_id=document_id, chapter="Chapter 1", chunk_id=chunk, evidence_text=f"Elena has {value} eyes."),
        )
    runner = WorkflowRunner.__new__(WorkflowRunner)
    runner.continuity = ContinuityService()
    comparisons = runner._intra_chapter_comparisons([fact("blue", "one"), fact("green", "two"), fact("brown", "three")])
    assert len(comparisons) == 3
    assert all(result.type is FindingType.CONTRADICTION for _, _, result in comparisons)