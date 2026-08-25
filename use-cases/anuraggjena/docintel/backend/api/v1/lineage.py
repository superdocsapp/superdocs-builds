"""
Lineage and Replay API endpoints.

Provides REST API for:
- Lineage graph visualization (claim → evidence → document traceability)
- Knowledge provenance tracking
- Regeneration chain history
- Workflow execution replay
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, verify_claim_workspace_access, verify_run_workspace_access
from backend.models.claim import Claim
from backend.models.workflow import WorkflowRun
from backend.core.lineage.service import LineageService
from backend.core.lineage.replay import ReplayService
from backend.repositories.lineage import LineageLinkRepository
from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.evidence import EvidenceRepository, CitationRepository
from backend.repositories.knowledge import KnowledgeRepository
from backend.repositories.audit import AuditRepository
from backend.repositories.workflow import WorkflowStageRepository, WorkflowRunRepository
from backend.repositories.document import DocumentRepository, DocumentChunkRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/lineage", tags=["lineage"])
replay_router = APIRouter(prefix="/replay", tags=["replay"])


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class LineageNodeResponse(BaseModel):
    """A node in the lineage graph"""
    id: str
    type: str
    label: str
    metadata: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True


class LineageEdgeResponse(BaseModel):
    """An edge in the lineage graph"""
    source_id: str
    target_id: str
    edge_type: str
    metadata: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True


class LineageGraphResponse(BaseModel):
    """Complete lineage graph with nodes and edges"""
    nodes: List[LineageNodeResponse]
    edges: List[LineageEdgeResponse]
    root_node_id: Optional[str]  # None for multi-root graphs (run lineage)

    class Config:
        from_attributes = True


class KnowledgeProvenanceResponse(BaseModel):
    """Provenance information for prior knowledge"""
    knowledge_entry_id: UUID
    source_run_id: Optional[UUID]
    content: str
    relevance_score: Optional[float]
    adoption_reason: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class ClaimResponse(BaseModel):
    """Claim in regeneration chain"""
    id: UUID
    workflow_run_id: UUID
    review_id: Optional[UUID]
    claim_type: str
    content: str
    status: str
    original_content: Optional[str]
    edited_by: Optional[str]
    source_stage: Optional[str]
    confidence_score: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info) -> str:
        """Serialize datetime to ISO format string"""
        return dt.isoformat()


class ReplayStageResponse(BaseModel):
    """A stage in the replay timeline"""
    stage_name: str
    status: str
    started_at: str
    completed_at: Optional[str]
    execution_time_ms: Optional[int]
    inputs: dict
    outputs: dict
    contributed_to_claim: bool = False

    class Config:
        from_attributes = True


class ReplayTimelineResponse(BaseModel):
    """Complete workflow execution replay timeline"""
    run_id: UUID
    stages: List[ReplayStageResponse]
    knowledge_reused: List[dict] = Field(default_factory=list)
    review_decisions: List[dict] = Field(default_factory=list)

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Dependency Injection
# ---------------------------------------------------------------------------

async def get_lineage_service(db: AsyncSession = Depends(get_db)) -> LineageService:
    """Dependency for lineage service"""
    lineage_link_repo = LineageLinkRepository(db)
    claim_repo = ClaimRepository(db)
    evidence_repo = EvidenceRepository(db)
    citation_repo = CitationRepository(db)
    knowledge_repo = KnowledgeRepository(db)
    audit_repo = AuditRepository(db)
    stage_repo = WorkflowStageRepository(db)
    chunk_repo = DocumentChunkRepository(db)
    document_repo = DocumentRepository(db)
    review_repo = ReviewRepository(db)

    return LineageService(
        lineage_link_repo=lineage_link_repo,
        claim_repo=claim_repo,
        evidence_repo=evidence_repo,
        citation_repo=citation_repo,
        knowledge_repo=knowledge_repo,
        audit_repo=audit_repo,
        stage_repo=stage_repo,
        chunk_repo=chunk_repo,
        document_repo=document_repo,
        review_repo=review_repo,
    )


async def get_replay_service(db: AsyncSession = Depends(get_db)) -> ReplayService:
    """Dependency for replay service"""
    stage_repo = WorkflowStageRepository(db)
    run_repo = WorkflowRunRepository(db)

    # Create lineage service for replay service
    lineage_service = await get_lineage_service(db)

    return ReplayService(
        stage_repo=stage_repo,
        lineage_service=lineage_service,
        run_repo=run_repo,
    )


# ---------------------------------------------------------------------------
# Lineage Endpoints
# ---------------------------------------------------------------------------

@router.get("/claim/{claim_id}", response_model=LineageGraphResponse)
async def get_claim_lineage(
    claim_id: UUID,
    depth: int = Query(default=3, ge=1, le=5, description="Traversal depth (1-5)"),
    claim: Claim = Depends(verify_claim_workspace_access),
    service: LineageService = Depends(get_lineage_service)
):
    """
    Get lineage graph for a specific claim.

    Traces the claim back through citations, evidence, chunks, and documents.
    Also includes knowledge derivations and regeneration history.

    Args:
        claim_id: UUID of the claim
        depth: How many relationship hops to traverse (default: 3, min: 1, max: 5)

    Returns:
        LineageGraphResponse with nodes, edges, and root node ID

    Raises:
        404: If claim not found
    """
    logger.info("api_get_claim_lineage", claim_id=str(claim_id), depth=depth)

    try:
        graph = await service.get_claim_lineage(claim_id, depth=depth)

        # Convert dataclass to Pydantic response
        return LineageGraphResponse(
            nodes=[
                LineageNodeResponse(
                    id=node.id,
                    type=node.type,
                    label=node.label,
                    metadata=node.metadata
                ) for node in graph.nodes
            ],
            edges=[
                LineageEdgeResponse(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    edge_type=edge.edge_type,
                    metadata=edge.metadata
                ) for edge in graph.edges
            ],
            root_node_id=graph.root_node_id
        )

    except ValueError as e:
        logger.warning("claim_not_found", claim_id=str(claim_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found"
        )


@router.get("/run/{run_id}", response_model=LineageGraphResponse)
async def get_run_lineage(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: LineageService = Depends(get_lineage_service)
):
    """
    Get lineage graph for entire workflow run (all claims).

    Builds a unified lineage graph showing provenance for all claims
    in the workflow run, with deduplicated nodes and edges.

    Args:
        run_id: UUID of the workflow run

    Raises:
        404: If workflow run not found
        403: If user doesn't own the workspace
    """
    logger.info("api_get_run_lineage", run_id=str(run_id))

    try:
        graph = await service.get_run_lineage(run_id)

        return LineageGraphResponse(
            nodes=[
                LineageNodeResponse(
                    id=node.id,
                    type=node.type,
                    label=node.label,
                    metadata=node.metadata or {}
                )
                for node in graph.nodes
            ],
            edges=[
                LineageEdgeResponse(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    edge_type=edge.edge_type,
                    metadata=edge.metadata or {}
                )
                for edge in graph.edges
            ],
            root_node_id=graph.root_node_id
        )
    except ValueError as e:
        logger.error("run_not_found", run_id=str(run_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/claim/{claim_id}/knowledge", response_model=List[KnowledgeProvenanceResponse])
async def get_knowledge_provenance(
    claim_id: UUID,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: LineageService = Depends(get_lineage_service)
):
    """
    Get all prior knowledge entries that influenced this claim.

    Returns structured provenance showing:
    - What knowledge was reused
    - Where it came from
    - Why it was adopted

    Args:
        claim_id: UUID of the claim

    Returns:
        List of KnowledgeProvenanceResponse entries

    Raises:
        403: If user doesn't own the workspace
        404: If claim not found
    """
    logger.info("api_get_knowledge_provenance", claim_id=str(claim_id))

    provenance = await service.get_knowledge_provenance(claim_id)

    return [
        KnowledgeProvenanceResponse(
            knowledge_entry_id=p.knowledge_entry_id,
            source_run_id=p.source_run_id,
            content=p.content,
            relevance_score=p.relevance_score,
            adoption_reason=p.adoption_reason,
            created_at=p.created_at
        ) for p in provenance
    ]


@router.get("/claim/{claim_id}/regeneration-chain", response_model=List[ClaimResponse])
async def get_regeneration_chain(
    claim_id: UUID,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: LineageService = Depends(get_lineage_service)
):
    """
    Get the full regeneration chain for a claim.

    Follows regeneration history backwards from current claim to original,
    then returns in chronological order.

    Args:
        claim_id: UUID of the claim

    Returns:
        List of claims from original to current (chronological order)

    Raises:
        403: If user doesn't own the workspace
        404: If claim not found
    """
    logger.info("api_get_regeneration_chain", claim_id=str(claim_id))

    chain = await service.get_regeneration_chain(claim_id)

    return [ClaimResponse.model_validate(claim) for claim in chain]


# ---------------------------------------------------------------------------
# Replay Endpoints
# ---------------------------------------------------------------------------

@replay_router.get("/run/{run_id}", response_model=ReplayTimelineResponse)
async def replay_run_execution(
    run_id: UUID,
    run: WorkflowRun = Depends(verify_run_workspace_access),
    service: ReplayService = Depends(get_replay_service)
):
    """
    Reconstruct workflow run execution timeline.

    Reads checkpoint data to rebuild complete execution history showing:
    - Stage execution order
    - Stage inputs/outputs
    - Execution timing
    - Knowledge reuse
    - Review decisions

    This is deterministic reconstruction from stored state, NOT re-execution.

    Args:
        run_id: UUID of the workflow run

    Returns:
        ReplayTimelineResponse with complete execution timeline

    Raises:
        403: If user doesn't own the workspace
        404: If workflow run not found
    """
    logger.info("api_replay_run_execution", run_id=str(run_id))

    try:
        timeline = await service.replay_run_execution(run_id)

        return ReplayTimelineResponse(
            run_id=timeline.run_id,
            stages=[
                ReplayStageResponse(
                    stage_name=stage.stage_name,
                    status=stage.status,
                    started_at=stage.started_at,
                    completed_at=stage.completed_at,
                    execution_time_ms=stage.execution_time_ms,
                    inputs=stage.inputs,
                    outputs=stage.outputs,
                    contributed_to_claim=stage.contributed_to_claim
                ) for stage in timeline.stages
            ],
            knowledge_reused=timeline.knowledge_reused,
            review_decisions=timeline.review_decisions
        )

    except ValueError as e:
        logger.warning("run_not_found", run_id=str(run_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"WorkflowRun {run_id} not found"
        )


@replay_router.get("/claim/{claim_id}", response_model=ReplayTimelineResponse)
async def replay_claim_execution(
    claim_id: UUID,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: ReplayService = Depends(get_replay_service)
):
    """
    Reconstruct how a specific claim was produced.

    Replays the full workflow run execution and highlights stages
    that contributed to this specific claim's creation.

    Args:
        claim_id: UUID of the claim

    Raises:
        403: If user doesn't own the workspace
        404: If claim not found
    """
    logger.info("api_replay_claim_execution", claim_id=str(claim_id))

    try:
        timeline = await service.replay_claim_execution(claim_id)

        return ReplayTimelineResponse(
            run_id=timeline.run_id,
            stages=[
                ReplayStageResponse(
                    stage_name=stage.stage_name,
                    status=stage.status,
                    started_at=stage.started_at,
                    completed_at=stage.completed_at,
                    execution_time_ms=stage.execution_time_ms,
                    inputs=stage.inputs,
                    outputs=stage.outputs,
                    contributed_to_claim=stage.contributed_to_claim
                ) for stage in timeline.stages
            ],
            knowledge_reused=timeline.knowledge_reused,
            review_decisions=timeline.review_decisions
        )

    except ValueError as e:
        logger.warning("claim_not_found", claim_id=str(claim_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found"
        )
