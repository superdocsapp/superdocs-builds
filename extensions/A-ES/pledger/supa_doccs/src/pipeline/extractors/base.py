"""Base data models and protocol for fact extraction."""

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class SourceSpan:
    """Character span within the source text.

    Represents a contiguous region of source text from which a fact
    was extracted. Offsets are 0-based character positions.
    """

    start_offset: int  # 0-based, inclusive
    end_offset: int  # 0-based, exclusive
    page_number: Optional[int] = None
    section_id: Optional[str] = None


@dataclass
class ExtractedFact:
    """A single extracted fact with source provenance.

    Represents a field-value pair extracted from a document, along with
    a confidence score and an optional pointer back to the source text span.

    When source_span is None, the citation is unverifiable — the fact was
    extracted but cannot be traced to a specific location in the source.
    Consumers MUST handle the None case explicitly.
    """

    field_name: str
    value: str  # normalized string representation
    confidence: float  # 0.000–1.000
    source_span: Optional[SourceSpan]  # None = citation unverifiable
    fact_group_id: Optional[str] = None  # groups multi-field records


class FactExtractor(Protocol):
    """Protocol for type-specific extraction.

    Implementors extract structured facts from document text and chunks,
    returning a list of ExtractedFact instances with source provenance.
    """

    async def extract(
        self,
        text: str,
        chunks: list[dict],
    ) -> list[ExtractedFact]: ...
