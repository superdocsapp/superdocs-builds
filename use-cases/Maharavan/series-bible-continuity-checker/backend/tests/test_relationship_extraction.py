from uuid import uuid4

from series_bible.application.extraction import GroundedRuleExtractor
from series_bible.infrastructure.database import DocumentChunk


def test_extracts_conflicting_possessive_and_copula_relationships():
    document_id = uuid4()
    chunks = [
        DocumentChunk(document_id=document_id, source_chunk_id="one", text="Marcus was Elena's cousin.", content_hash="one"),
        DocumentChunk(document_id=document_id, source_chunk_id="two", text="Elena's younger brother Marcus lived in the northern wing.", content_hash="two"),
    ]
    facts = GroundedRuleExtractor().extract(chunks, {})
    assert [(fact.entity, fact.attribute, fact.value) for fact in facts] == [
        ("Elena", "relationship_marcus", "cousin"),
        ("Elena", "relationship_marcus", "younger brother"),
    ]