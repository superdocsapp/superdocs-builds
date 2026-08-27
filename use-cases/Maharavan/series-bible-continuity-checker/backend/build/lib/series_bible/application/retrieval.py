from uuid import UUID
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from series_bible.infrastructure.database import BibleFact

class FactRetriever:
    """Metadata-first retrieval, designed for optional vector reranking later."""
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def retrieve(self, series_id: UUID, entity: str, attribute: str, limit: int = 10) -> list[BibleFact]:
        query: Select[tuple[BibleFact]] = (select(BibleFact).where(
            BibleFact.series_id == series_id,
            BibleFact.is_current.is_(True),
            BibleFact.entity == entity,
            BibleFact.attribute == attribute,
        ).limit(limit))
        return list((await self.session.scalars(query)).all())
