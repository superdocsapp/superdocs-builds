from backend.core.lineage.models import (
    LineageNode,
    LineageEdge,
    LineageGraph,
    KnowledgeProvenance,
    ReplayStage,
    ReplayTimeline,
)
from uuid import uuid4


def test_lineage_models_import():
    """Test that lineage dataclasses can be imported"""
    assert LineageNode is not None
    assert LineageEdge is not None
    assert LineageGraph is not None


def test_lineage_node_creation():
    """Test creating a LineageNode"""
    node = LineageNode(
        id="claim-123",
        type="claim",
        label="Test Claim",
        metadata={"status": "approved"}
    )
    assert node.id == "claim-123"
    assert node.type == "claim"
    assert node.metadata["status"] == "approved"


def test_lineage_node_with_default_metadata():
    """Test LineageNode with default metadata"""
    node = LineageNode(id="1", type="claim", label="Test")
    assert node.metadata == {}


def test_lineage_edge_creation():
    """Test creating a LineageEdge"""
    edge = LineageEdge(
        source_id="claim-1",
        target_id="evidence-1",
        edge_type="cited_by",
        metadata={"relevance_score": 0.95}
    )
    assert edge.source_id == "claim-1"
    assert edge.target_id == "evidence-1"
    assert edge.edge_type == "cited_by"
    assert edge.metadata["relevance_score"] == 0.95


def test_lineage_edge_with_default_metadata():
    """Test LineageEdge with default metadata"""
    edge = LineageEdge(source_id="1", target_id="2", edge_type="derived_from")
    assert edge.metadata == {}


def test_lineage_graph_creation():
    """Test creating a LineageGraph"""
    nodes = [
        LineageNode(id="1", type="claim", label="Claim 1"),
        LineageNode(id="2", type="evidence", label="Evidence 1")
    ]
    edges = [
        LineageEdge(source_id="1", target_id="2", edge_type="cited_by")
    ]
    graph = LineageGraph(nodes=nodes, edges=edges, root_node_id="1")

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.root_node_id == "1"


def test_knowledge_provenance_creation():
    """Test creating a KnowledgeProvenance"""
    knowledge_id = uuid4()
    source_run_id = uuid4()

    provenance = KnowledgeProvenance(
        knowledge_entry_id=knowledge_id,
        source_run_id=source_run_id,
        content="Prior knowledge content",
        relevance_score=0.95,
        adoption_reason="High relevance to current claim",
        created_at="2026-01-01T00:00:00"
    )

    assert provenance.knowledge_entry_id == knowledge_id
    assert provenance.source_run_id == source_run_id
    assert provenance.content == "Prior knowledge content"
    assert provenance.relevance_score == 0.95
    assert provenance.adoption_reason == "High relevance to current claim"


def test_knowledge_provenance_with_optional_fields():
    """Test KnowledgeProvenance with optional fields as None"""
    knowledge_id = uuid4()

    provenance = KnowledgeProvenance(
        knowledge_entry_id=knowledge_id,
        source_run_id=None,
        content="Content without source",
        relevance_score=None,
        adoption_reason=None,
        created_at="2026-01-01T00:00:00"
    )

    assert provenance.source_run_id is None
    assert provenance.relevance_score is None
    assert provenance.adoption_reason is None


def test_replay_stage_creation():
    """Test creating a ReplayStage"""
    stage = ReplayStage(
        stage_name="generate",
        status="completed",
        started_at="2026-01-01T00:00:00",
        completed_at="2026-01-01T00:01:00",
        execution_time_ms=60000,
        inputs={"document_id": "123"},
        outputs={"claim_ids": ["claim-1", "claim-2"]},
        contributed_to_claim=True
    )

    assert stage.stage_name == "generate"
    assert stage.status == "completed"
    assert stage.execution_time_ms == 60000
    assert stage.contributed_to_claim is True


def test_replay_stage_with_defaults():
    """Test ReplayStage with default contributed_to_claim"""
    stage = ReplayStage(
        stage_name="extract",
        status="completed",
        started_at="2026-01-01T00:00:00",
        completed_at="2026-01-01T00:01:00",
        execution_time_ms=30000,
        inputs={},
        outputs={}
    )

    assert stage.contributed_to_claim is False


def test_replay_timeline_creation():
    """Test creating a ReplayTimeline"""
    run_id = uuid4()

    stages = [
        ReplayStage(
            stage_name="extract",
            status="completed",
            started_at="2026-01-01T00:00:00",
            completed_at="2026-01-01T00:01:00",
            execution_time_ms=60000,
            inputs={},
            outputs={"evidence_count": 5}
        ),
        ReplayStage(
            stage_name="generate",
            status="completed",
            started_at="2026-01-01T00:01:00",
            completed_at="2026-01-01T00:02:00",
            execution_time_ms=45000,
            inputs={"evidence_count": 5},
            outputs={"claim_ids": ["claim-1"]}
        )
    ]

    knowledge_reused = [
        {"knowledge_id": "k1", "content": "Prior knowledge 1"},
        {"knowledge_id": "k2", "content": "Prior knowledge 2"}
    ]

    review_decisions = [
        {"claim_id": "claim-1", "status": "approved"}
    ]

    timeline = ReplayTimeline(
        run_id=run_id,
        stages=stages,
        knowledge_reused=knowledge_reused,
        review_decisions=review_decisions
    )

    assert timeline.run_id == run_id
    assert len(timeline.stages) == 2
    assert len(timeline.knowledge_reused) == 2
    assert len(timeline.review_decisions) == 1


def test_replay_timeline_with_default_lists():
    """Test ReplayTimeline with default empty lists"""
    run_id = uuid4()

    timeline = ReplayTimeline(
        run_id=run_id,
        stages=[]
    )

    assert timeline.knowledge_reused == []
    assert timeline.review_decisions == []
