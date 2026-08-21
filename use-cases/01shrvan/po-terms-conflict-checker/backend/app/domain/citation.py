"""Citations: the link between a claim and the exact place in a source that supports it.

Every claim this system makes carries one of these. See INVARIANTS.md I2 and I3.

The design point: a citation's quote is *derived* from the source, never asserted alongside it. The
canonical constructor `Citation.into()` slices the text itself, so a citation whose quote does not
match its offsets cannot be produced by the extraction path at all. `verify()` exists for the other
direction — citations loaded back from the database, where the bytes have made a round trip and the
source document may have been re-parsed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpanOutOfRange(ValueError):
    """Raised when a citation's offsets do not lie within the document it names."""


class QuoteMismatch(ValueError):
    """Raised when a citation's quote is not the text at its offsets.

    This is the error that separates a quotation from a plausible paraphrase.
    """


class Citation(BaseModel):
    """A verbatim span of a source document.

    Offsets are character positions into the document's extracted text, half-open `[start, end)`,
    matching Python slice semantics so `text[start:end]` is exactly the quote.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _span_must_be_coherent(self) -> Citation:
        if self.end <= self.start:
            raise SpanOutOfRange(
                f"citation span must be non-empty and forward: got [{self.start}, {self.end})"
            )
        if self.end - self.start != len(self.quote):
            raise QuoteMismatch(
                f"span [{self.start}, {self.end}) is {self.end - self.start} characters "
                f"but the quote is {len(self.quote)}"
            )
        return self

    @classmethod
    def into(cls, document_id: str, source_text: str, start: int, end: int) -> Citation:
        """Cut a citation out of a document's text.

        This is the only constructor the extraction path uses. The quote is taken from the source
        rather than supplied beside it, which makes a mismatched quote unrepresentable here.
        """
        if start < 0 or end > len(source_text):
            raise SpanOutOfRange(
                f"span [{start}, {end}) does not lie within document {document_id!r} "
                f"of length {len(source_text)}"
            )
        return cls(document_id=document_id, start=start, end=end, quote=source_text[start:end])

    def verify(self, source_text: str) -> None:
        """Re-check this citation against the document text. Raises if it no longer holds.

        Called on citations loaded from storage, before anything is shown to a human or written into
        a deliverable. A citation that cannot be re-verified is not downgraded to a weaker claim —
        it is an error, because the alternative is presenting an unverified quote as a verified one.
        """
        if self.end > len(source_text):
            raise SpanOutOfRange(
                f"span [{self.start}, {self.end}) runs past document {self.document_id!r} "
                f"of length {len(source_text)}"
            )
        actual = source_text[self.start : self.end]
        if actual != self.quote:
            raise QuoteMismatch(
                f"document {self.document_id!r} no longer reads {self.quote!r} "
                f"at [{self.start}, {self.end}) — found {actual!r}"
            )

    def holds_for(self, source_text: str) -> bool:
        """Non-raising form of `verify`, for reporting rather than enforcement."""
        try:
            self.verify(source_text)
        except (SpanOutOfRange, QuoteMismatch):
            return False
        return True
