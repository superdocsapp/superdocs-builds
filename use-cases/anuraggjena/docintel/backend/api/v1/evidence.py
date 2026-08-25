from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, verify_run_workspace_access
from backend.models.workflow import WorkflowRun
from backend.repositories.evidence import EvidenceRepository, CitationRepository

router = APIRouter(prefix="/evidence", tags=["evidence"])


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_run_id: UUID
    document_id: UUID
    chunk_id: Optional[UUID] = None
    extracted_text: str
    evidence_type: str
    page_number: Optional[str] = None
    relevance_score: Optional[float] = None
    created_at: datetime


class CitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    evidence_id: UUID
    excerpt: Optional[str] = None
    relevance_score: Optional[float] = None
    created_at: datetime


async def get_evidence_repo(db: AsyncSession = Depends(get_db)) -> EvidenceRepository:
    return EvidenceRepository(db)


async def get_citation_repo(db: AsyncSession = Depends(get_db)) -> CitationRepository:
    return CitationRepository(db)


@router.get("/run/{run_id}", response_model=List[EvidenceResponse])
async def list_evidence_for_run(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    repo: EvidenceRepository = Depends(get_evidence_repo),
):
    """
    List all evidence for a workflow run.

    Raises:
        403: If user doesn't own the workspace
        404: If workflow run not found
    """
    return await repo.list_by_run(run_id)


@router.get("/run/{run_id}/citations", response_model=List[CitationResponse])
async def list_citations_for_run(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    evidence_repo: EvidenceRepository = Depends(get_evidence_repo),
    citation_repo: CitationRepository = Depends(get_citation_repo),
):
    """
    List all citations for evidence in a workflow run.

    Raises:
        403: If user doesn't own the workspace
        404: If workflow run not found
    """
    evidence_items = await evidence_repo.list_by_run(run_id)
    all_citations: List = []
    for ev in evidence_items:
        citations = await citation_repo.list_by_evidence(ev.id)
        all_citations.extend(citations)
    return all_citations
