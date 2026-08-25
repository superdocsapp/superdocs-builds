"""
Lineage dataclass models for graph and replay structures.

These dataclasses represent the structure of lineage graphs and replay timelines
for visualizing claim provenance and reconstructing workflow execution.
"""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class LineageNode:
    """
    A node in the lineage graph.

    Represents an entity in the workflow (document, evidence, claim, etc.)
    """
    id: str
    type: str  # "document", "chunk", "evidence", "claim", "citation", "knowledge", "review", "stage"
    label: str
    metadata: dict = field(default_factory=dict)


@dataclass
class LineageEdge:
    """
    An edge in the lineage graph.

    Represents a relationship between two entities.
    """
    source_id: str
    target_id: str
    edge_type: str  # "extracted_from", "cited_by", "derived_from", "approved", "regenerated_from", "superdocs_edit", "reused_from_baseline", "superseded_by"
    metadata: dict = field(default_factory=dict)


@dataclass
class LineageGraph:
    """
    A complete lineage graph.

    Contains all nodes and edges for visualizing claim provenance.
    """
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    root_node_id: str


@dataclass
class KnowledgeProvenance:
    """
    Provenance information for prior knowledge.

    Tracks how prior knowledge entries influenced current claims.
    """
    knowledge_entry_id: UUID
    source_run_id: UUID | None
    content: str
    relevance_score: float | None
    adoption_reason: str | None
    created_at: str


@dataclass
class ReplayStage:
    """
    A stage in the replay timeline.

    Represents a single workflow stage execution with its inputs and outputs.
    """
    stage_name: str
    status: str
    started_at: str
    completed_at: str | None
    execution_time_ms: int | None
    inputs: dict
    outputs: dict
    contributed_to_claim: bool = False


@dataclass
class ReplayTimeline:
    """
    A complete replay timeline.

    Reconstructs the full execution history of a workflow run.
    """
    run_id: UUID
    stages: list[ReplayStage]
    knowledge_reused: list[dict] = field(default_factory=list)
    review_decisions: list[dict] = field(default_factory=list)
    phase7_events: list[dict] = field(default_factory=list)  # Phase 7: SuperDocs, baseline reuse, contradictions
