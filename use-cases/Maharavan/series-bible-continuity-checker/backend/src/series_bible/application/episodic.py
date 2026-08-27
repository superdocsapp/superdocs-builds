"""Episodic memory: structured, queryable narrative/process events.

Distinct from ``AuditEvent`` (technical audit log). A ``StoryEvent`` records
what happened to the story and to human decisions over time, so the agent can
answer questions like "when did Elena's eyes change" using persisted state
rather than model recollection.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from series_bible.application.embeddings import HashEmbeddingProvider
from series_bible.infrastructure.database import StoryEvent

_embeddings = HashEmbeddingProvider()


async def record_story_event(
    session: AsyncSession,
    *,
    series_id: UUID,
    event_type: str,
    description: str,
    actor: str = "workflow",
    run_id: UUID | None = None,
    document_id: UUID | None = None,
    chapter_id: UUID | None = None,
    finding_id: UUID | None = None,
    source: str | None = None,
) -> StoryEvent:
    event = StoryEvent(
        series_id=series_id,
        run_id=run_id,
        document_id=document_id,
        chapter_id=chapter_id,
        finding_id=finding_id,
        event_type=event_type,
        description=description,
        actor=actor,
        source=source,
        embedding=_embeddings.embed(description),
    )
    session.add(event)
    await session.flush()
    return event
