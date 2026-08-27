from uuid import uuid4

from series_bible.application.extraction import GroundedRuleExtractor
from series_bible.infrastructure.database import DocumentChunk


def chunk(text: str) -> DocumentChunk:
    return DocumentChunk(
        document_id=uuid4(),
        chapter_id=uuid4(),
        source_chunk_id="chunk-1",
        text=text,
        content_hash="a" * 64,
    )


def test_pronoun_description_keeps_named_character_context():
    source = chunk("Elena removed her hood. Her blue eyes reflected the winter sky.")
    facts = GroundedRuleExtractor().extract([source], {source.chapter_id: "Chapter 1"})
    assert [(fact.entity, fact.attribute, fact.value) for fact in facts] == [
        ("Elena", "eye_color", "blue")
    ]
    assert facts[0].source.evidence_text == "Her blue eyes reflected the winter sky."


def test_new_chapter_extracts_green_eye_claim():
    source = chunk("Elena studied her reflection. Her green eyes looked silver.")
    facts = GroundedRuleExtractor().extract([source], {source.chapter_id: "Chapter 6"})
    assert facts[0].entity == "Elena"
    assert facts[0].value == "green"