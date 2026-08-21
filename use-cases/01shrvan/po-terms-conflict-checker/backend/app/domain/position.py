"""A single document's position on a single clause area."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.citation import Citation
from app.domain.clause import ClauseArea, Party


class Position(BaseModel):
    """What one document says about one clause area.

    A position always carries at least one citation (INVARIANTS.md I2). The absence of a position is
    represented by there being no `Position` at all — never by a `Position` with an empty summary or
    a "not mentioned" placeholder. That distinction is what lets the reconciler tell silence from a
    weakly-worded agreement without asking a model.
    """

    model_config = ConfigDict(frozen=True)

    party: Party
    document_id: str = Field(min_length=1)
    area: ClauseArea
    summary: str = Field(min_length=1)
    citations: tuple[Citation, ...]

    @field_validator("citations")
    @classmethod
    def _must_be_cited(cls, citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
        if not citations:
            raise ValueError(
                "a position must cite at least one span of its source document; "
                "an uncited position is a claim the system cannot stand behind"
            )
        return citations

    @field_validator("citations")
    @classmethod
    def _citations_must_match_the_document(
        cls, citations: tuple[Citation, ...], info
    ) -> tuple[Citation, ...]:
        document_id = info.data.get("document_id")
        if document_id is None:
            return citations
        strays = {c.document_id for c in citations} - {document_id}
        if strays:
            raise ValueError(
                f"position on document {document_id!r} cites other documents: {sorted(strays)}"
            )
        return citations

    def verify_against(self, source_text: str) -> None:
        """Re-check every citation against the document text. Raises on the first failure."""
        for citation in self.citations:
            citation.verify(source_text)
