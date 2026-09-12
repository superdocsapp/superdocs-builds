from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from common.verification import quote_grounded


class Hop(BaseModel):
    claim: str
    source_doc_id: str
    evidence_quote: str
    verified: bool = True


class MultiHopAnswer(BaseModel):
    answer: str | None = None
    could_not_answer: bool = False
    hops: list[Hop] = Field(default_factory=list)

    @classmethod
    def dedupe_hops(cls, hops: list[Hop]) -> list[Hop]:
        seen: set[tuple[str, str]] = set()
        deduped: list[Hop] = []
        for hop in hops:
            key = (hop.source_doc_id, hop.evidence_quote.strip())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(hop)
        return deduped

    def validate_against_documents(self, documents: dict[str, str]) -> "MultiHopAnswer":
        for hop in self.hops:
            source_text = documents.get(hop.source_doc_id, "")
            hop.verified = quote_grounded(hop.evidence_quote, source_text)
        self.hops = self.dedupe_hops(self.hops)
        if self.could_not_answer and not self.answer:
            return self
        if self.answer and not self.hops:
            self.could_not_answer = True
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "could_not_answer": self.could_not_answer,
            "hops": [hop.model_dump() for hop in self.hops],
        }
