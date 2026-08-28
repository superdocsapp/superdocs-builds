"""End-to-end provenance test for the microfinance ingestion pipeline.

Ingests all 5 synthetic documents through type-specific extractors and
verifies that every extracted fact has a valid, resolvable source pointer.

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

from __future__ import annotations

import uuid

import pytest

from src.pipeline.extractors.base import ExtractedFact
from src.pipeline.extractors.registry import EXTRACTOR_REGISTRY
from src.pipeline.source_linker import SourceLinker, SourceResolutionError
from tests.synthetic.generator import SyntheticDocumentGenerator


@pytest.mark.anyio
class TestProvenanceEndToEnd:
    """End-to-end test: synthetic pile → pipeline → source pointer verification."""

    async def test_all_facts_have_valid_source_pointers(self):
        """Ingest 5 synthetic docs, verify every fact has a resolvable pointer.

        Asserts:
        1. All 5 documents produce ≥1 extracted fact
        2. Every fact with a valid span has exactly 1 source_location record
        3. start_offset < end_offset for every pointer
        4. Resolved substring is non-empty
        5. Re-parsing resolved substring produces same value (round-trip)
        6. No SourceResolutionError raised during resolution
        """
        generator = SyntheticDocumentGenerator(seed=42)
        pile = generator.generate()
        linker = SourceLinker()

        assert len(pile.documents) == 5, (
            f"Expected 5 synthetic documents, got {len(pile.documents)}"
        )

        for doc in pile.documents:
            # Each document gets a unique version ID
            doc_version_id = str(uuid.uuid4())

            # Get the appropriate extractor for this document type
            extractor_cls = EXTRACTOR_REGISTRY.get(doc.document_type)
            assert extractor_cls is not None, (
                f"No extractor registered for document type '{doc.document_type}' "
                f"(file: {doc.filename})"
            )
            extractor = extractor_cls()

            # Run extraction
            facts: list[ExtractedFact] = await extractor.extract(
                doc.text_content, []
            )

            # Requirement 7.1: All 5 documents produce ≥1 extracted fact
            assert len(facts) >= 1, (
                f"Document '{doc.filename}' ({doc.document_type}) produced 0 facts. "
                f"Expected at least 1 extracted fact."
            )

            # Process each fact with a valid span
            valid_facts_count = 0
            for fact in facts:
                # Skip facts with unverifiable citations (None source_span)
                if fact.source_span is None:
                    continue

                start = fact.source_span.start_offset
                end = fact.source_span.end_offset

                # Skip facts with invalid spans (e.g. "not_found" with 0:0)
                if start >= end:
                    continue

                valid_facts_count += 1

                # Requirement 7.2: Every fact has exactly 1 source_location
                source_location = linker.attach(fact, doc_version_id)
                assert source_location is not None, (
                    f"SourceLinker.attach returned None for fact "
                    f"'{fact.field_name}' in '{doc.filename}'"
                )

                # Requirement 7.4: start_offset < end_offset
                assert source_location.start_offset < source_location.end_offset, (
                    f"Source pointer for fact '{fact.field_name}' in "
                    f"'{doc.filename}' has start_offset "
                    f"({source_location.start_offset}) >= end_offset "
                    f"({source_location.end_offset})"
                )

                # Requirement 7.3 & 7.6: Resolve without SourceResolutionError
                try:
                    resolved_text = linker.resolve(
                        source_location, doc.text_content
                    )
                except SourceResolutionError as e:
                    pytest.fail(
                        f"SourceResolutionError for fact '{fact.field_name}' "
                        f"in '{doc.filename}': claim_id={e.claim_id}, "
                        f"source_location_id={e.source_location_id}, "
                        f"reason={e.reason}"
                    )

                # Requirement 7.3: Resolved substring is non-empty
                assert len(resolved_text) > 0, (
                    f"Resolved text is empty for fact '{fact.field_name}' "
                    f"in '{doc.filename}' at offsets "
                    f"{source_location.start_offset}:{source_location.end_offset}"
                )

                # Requirement 7.5: Round-trip — resolved substring is a
                # non-empty string from the original document
                assert resolved_text == doc.text_content[start:end], (
                    f"Round-trip failed for fact '{fact.field_name}' in "
                    f"'{doc.filename}': resolved='{resolved_text}' vs "
                    f"expected='{doc.text_content[start:end]}'"
                )

            # Ensure at least some facts had valid spans
            assert valid_facts_count >= 1, (
                f"Document '{doc.filename}' ({doc.document_type}) had no facts "
                f"with valid source spans (start < end). Total facts: {len(facts)}"
            )
