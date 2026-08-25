from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.repositories.knowledge import KnowledgeRepository
from backend.models.knowledge import KnowledgeEntry
from backend.logging_config import get_logger

logger = get_logger(__name__)


class KnowledgeEngine:
    """Store and retrieve knowledge entries from prior workflow runs."""

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    async def store(
        self,
        workspace_id: UUID,
        workflow_type: str,
        entry_type: str,
        content: str,
        source_run_id: Optional[str] = None,
        source_document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        confidence_score: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> KnowledgeEntry:
        """Store a new knowledge entry."""
        entry = await self.repository.create(
            workspace_id=str(workspace_id),
            workflow_type=workflow_type,
            entry_type=entry_type,
            content=content,
            source_run_id=source_run_id,
            source_document_id=source_document_id,
            extra_metadata=metadata or {},
            confidence_score=confidence_score,
            tags=tags or []
        )
        logger.info("knowledge_entry_stored", entry_id=str(entry.id), workflow_type=workflow_type)
        return entry

    async def retrieve(
        self,
        workspace_id: UUID,
        workflow_type: str,
        tags: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[KnowledgeEntry]:
        """Retrieve relevant knowledge entries."""
        if tags:
            entries = await self.repository.search_by_tags(
                workspace_id=workspace_id,
                tags=tags,
                workflow_type=workflow_type,
                limit=limit
            )
        else:
            entries = await self.repository.list_by_workspace_and_type(
                workspace_id=workspace_id,
                workflow_type=workflow_type,
                limit=limit
            )
        logger.info("knowledge_entries_retrieved", count=len(entries), workflow_type=workflow_type)
        return entries

    async def retrieve_as_context(
        self,
        workspace_id: UUID,
        workflow_type: str,
        tags: Optional[List[str]] = None,
        limit: int = 5
    ) -> str:
        """Retrieve entries and format as a context string for LLM prompts."""
        entries = await self.retrieve(workspace_id, workflow_type, tags=tags, limit=limit)
        if not entries:
            return ""
        lines = ["Prior relevant knowledge:"]
        for i, entry in enumerate(entries, 1):
            lines.append(f"{i}. [{entry.entry_type}] {entry.content}")
        return "\n".join(lines)
