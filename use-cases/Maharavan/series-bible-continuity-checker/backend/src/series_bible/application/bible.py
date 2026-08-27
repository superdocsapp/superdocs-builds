from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from series_bible.domain.schemas import ExtractedFact
from series_bible.application.embeddings import HashEmbeddingProvider
from series_bible.infrastructure.database import BibleFact, Evidence

class BibleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.embeddings = HashEmbeddingProvider()

    async def add_version(self, series_id: UUID, fact: ExtractedFact, supersedes: BibleFact | None = None) -> BibleFact:
        if not fact.supported:
            raise ValueError("unsupported facts cannot enter the Bible")
        version = 1
        if supersedes:
            supersedes.is_current = False
            version = supersedes.version + 1
        semantic_text = f"{fact.kind.value} {fact.entity} {fact.attribute} {fact.value}"
        record = BibleFact(series_id=series_id, kind=fact.kind.value, entity=fact.entity, attribute=fact.attribute, value=fact.value, version=version, is_current=True, supersedes_id=supersedes.id if supersedes else None, confidence=fact.confidence, embedding=self.embeddings.embed(semantic_text))
        self.session.add(record)
        await self.session.flush()
        self.session.add(Evidence(fact_id=record.id, document_id=fact.source.document_id, chapter=fact.source.chapter, section=fact.source.section, page=fact.source.page, chunk_id=fact.source.chunk_id, exact_text=fact.source.evidence_text, role="FACT"))
        return record
