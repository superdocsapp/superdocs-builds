from __future__ import annotations

from pydantic import BaseModel


class CitationPair(BaseModel):
    claim: str
    citation_target: str
    source_doc_id: str = "document"


class EntailmentVerdict(BaseModel):
    verdict: str
    reason: str
