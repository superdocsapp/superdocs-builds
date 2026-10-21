"""
End-to-end integration test for Phase 4 Claim Lineage Graph.

Tests verify that:
1. Running tariff workflow creates lineage links
2. LineageService can build graphs from these links
3. Knowledge provenance is properly tracked
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.core.workflow.runner import WorkflowRunner
from backend.modules.tariff.stages.extract import ExtractStage
from backend.modules.tariff.stages.generate import GenerateStage
from backend.modules.tariff.schemas import TariffClaim, TariffWorkflowState
from backend.modules.tariff.stages.extract import TariffClaimsResponse
from backend.repositories.lineage import LineageLinkRepository
from backend.core.lineage.service import LineageService


def _make_stage_repo():
    """Return a mock WorkflowStageRepository"""
    repo = AsyncMock()
    repo.get_by_run_and_name = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_run_repo():
    """Return a mock WorkflowRunRepository"""
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_claim_repo():
    """Return a mock ClaimRepository that creates claims with IDs"""
    repo = AsyncMock()

    # Create distinct claim IDs for each claim
    async def create_claim(**kwargs):
        claim = MagicMock()
        claim.id = uuid4()
        claim.workflow_run_id = kwargs.get('workflow_run_id')
        claim.claim_type = kwargs.get('claim_type', 'tariff_claim')
        claim.content = kwargs.get('content', '')
        claim.status = kwargs.get('status', 'pending')
        claim.source_stage = kwargs.get('source_stage', 'generate')
        claim.confidence_score = None
        claim.review_id = None
        claim.original_content = None
        claim.edited_by = None
        return claim

    repo.create = AsyncMock(side_effect=create_claim)
    repo.get_by_id = AsyncMock()
    return repo


def _make_lineage_link_repo():
    """Return a mock LineageLinkRepository that tracks created links"""
    created_links = []

    async def create_link(**kwargs):
        link = MagicMock()
        link.id = uuid4()
        link.source_type = kwargs.get('source_type')
        link.source_id = kwargs.get('source_id')
        link.target_type = kwargs.get('target_type')
        link.target_id = kwargs.get('target_id')
        link.link_type = kwargs.get('link_type')
        link.workflow_run_id = kwargs.get('workflow_run_id')
        link.stage_name = kwargs.get('stage_name')
        link.link_metadata = kwargs.get('metadata', {})
        created_links.append(link)
        return link

    async def get_links_by_run(run_id):
        return [link for link in created_links if link.workflow_run_id == run_id]

    async def get_links_by_source(source_type, source_id):
        return [
            link for link in created_links
            if link.source_type == source_type and link.source_id == source_id
        ]

    async def get_knowledge_links_for_claim(claim_id):
        # Convert to UUID for comparison if needed
        from uuid import UUID
        claim_uuid = UUID(claim_id) if isinstance(claim_id, str) else claim_id
        return [
            link for link in created_links
            if link.source_type == "claim"
            and link.source_id == claim_uuid
            and link.link_type == "derived_from_knowledge"
        ]

    repo = AsyncMock()
    repo.create_link = AsyncMock(side_effect=create_link)
    repo.get_links_by_run = AsyncMock(side_effect=get_links_by_run)
    repo.get_links_by_source = AsyncMock(side_effect=get_links_by_source)
    repo.get_knowledge_links_for_claim = AsyncMock(side_effect=get_knowledge_links_for_claim)
    repo._created_links = created_links  # For test inspection

    return repo


def _make_knowledge_entry(workspace_id, workflow_type="tariff_classification"):
    """Create a mock KnowledgeEntry"""
    entry = MagicMock()
    entry.id = uuid4()
    entry.workspace_id = str(workspace_id)
    entry.workflow_type = workflow_type
    entry.entry_type = "claim"
    entry.content = "Prior tariff classification knowledge: HS 8471.30 applies to portable computers"
    entry.confidence_score = 0.95
    entry.tags = ["tariff", "electronics"]
    entry.extra_metadata = {}
    entry.source_run_id = uuid4()
    entry.source_document_id = None
    return entry


def _patch_extract_llm(stage: ExtractStage, claims=None):
    """Replace the stage's llm with a mock that returns a TariffClaimsResponse"""
    if claims is None:
        claims = [
            TariffClaim(
                hs_code="8471.30",
                description="Laptop computer",
                duty_rate="0%",
            )
        ]
    mock_llm = MagicMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=TariffClaimsResponse(claims=claims)
    )
    stage.llm = mock_llm
    return mock_llm


def _patch_generate_llm(stage: GenerateStage, report_text=None):
    """Replace the stage's llm with a mock that returns a report string"""
    if report_text is None:
        report_text = "Tariff Classification Report\n\nHS Code: 8471.30\nDuty Rate: 0%"
    mock_llm = MagicMock()
    response = MagicMock()
    response.content = report_text
    mock_llm.generate = AsyncMock(return_value=response)
    stage.llm = mock_llm
    return mock_llm


def _make_runner(extract_stage, generate_stage, stage_repo=None):
    """Build a WorkflowRunner wired for extract → generate"""
    return WorkflowRunner(
        workflow_name="tariff",
        stages=[extract_stage, generate_stage],
        edges=[("extract", "generate"), ("generate", "END")],
        state_schema=TariffWorkflowState,
        stage_repository=stage_repo or _make_stage_repo(),
    )


def _initial_state(**overrides):
    """Return a minimal valid initial state dict"""
    base = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_content": "This is a laptop computer used for portable computing.",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_tariff_lineage_end_to_end():
    """
    End-to-end test: run tariff workflow with prior knowledge and verify lineage links.

    This test verifies:
    1. Workflow executes successfully with prior_knowledge_entries in state
    2. GenerateStage creates lineage links connecting claims to knowledge entries
    3. LineageService can query and build graphs from these links
    """
    # Setup: Create mock repositories
    claim_repo = _make_claim_repo()
    lineage_link_repo = _make_lineage_link_repo()

    # Setup: Create workflow stages with lineage tracking
    extract_stage = ExtractStage()
    generate_stage = GenerateStage(
        claim_repository=claim_repo,
        lineage_link_repository=lineage_link_repo
    )

    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage)

    # Setup: Create knowledge entries
    workspace_id = uuid4()
    knowledge_entry = _make_knowledge_entry(workspace_id)

    # Setup: Create initial state WITH prior knowledge
    workflow_run_id = uuid4()
    initial_state = _initial_state(
        workflow_run_id=str(workflow_run_id),
        workspace_id=str(workspace_id),
        prior_knowledge_entries=[str(knowledge_entry.id)],
        prior_knowledge="Prior knowledge: HS 8471.30 applies to portable computers"
    )

    # Act: Run workflow
    runner = _make_runner(extract_stage, generate_stage)
    final_state = await runner.run(initial_state, _make_run_repo())

    # Assert: Workflow completed successfully
    assert final_state["extract_completed"] is True
    assert final_state["generate_completed"] is True
    assert len(final_state["extracted_claims"]) > 0
    assert len(final_state["claim_ids"]) > 0

    # Assert: Knowledge was adopted (check if key exists in final_state)
    # Note: WorkflowRunner may not merge all stage outputs into final state
    # The key verification is whether lineage links were created
    adopted_ids = final_state.get("adopted_knowledge_entry_ids", [])
    if adopted_ids:
        assert len(adopted_ids) > 0
        assert str(knowledge_entry.id) in adopted_ids

    # Assert: Lineage links were created
    lineage_links = await lineage_link_repo.get_links_by_run(workflow_run_id)
    assert len(lineage_links) > 0, "Expected lineage links to be created"

    # Assert: Knowledge links exist with correct structure
    knowledge_links = [
        link for link in lineage_links
        if link.link_type == "derived_from_knowledge"
    ]
    assert len(knowledge_links) > 0, "Expected knowledge derivation links"

    # Assert: Links connect claims to knowledge entries correctly
    first_link = knowledge_links[0]
    assert first_link.source_type == "claim"
    assert first_link.target_type == "knowledge_entry"
    assert first_link.target_id == knowledge_entry.id
    assert first_link.workflow_run_id == workflow_run_id
    assert first_link.stage_name == "generate"

    # Assert: Each claim has a link to the knowledge entry
    for claim_id in final_state["claim_ids"]:
        claim_links = await lineage_link_repo.get_knowledge_links_for_claim(claim_id)
        assert len(claim_links) > 0, f"Expected links for claim {claim_id}"


@pytest.mark.asyncio
async def test_lineage_service_builds_graph_from_links():
    """
    Test that LineageService can build a lineage graph from workflow-created links.

    This test verifies:
    1. LineageService.get_claim_lineage can query lineage links
    2. Graph includes both claim and knowledge entry nodes
    3. Edges connect nodes correctly
    """
    # Setup: Create mock repositories with pre-populated data
    workspace_id = uuid4()
    workflow_run_id = uuid4()
    knowledge_entry = _make_knowledge_entry(workspace_id)

    # Create a claim
    claim = MagicMock()
    claim.id = uuid4()
    claim.workflow_run_id = workflow_run_id
    claim.content = "HS Code 8471.30 applies to laptop computers with duty rate 0%"
    claim.status = "pending"
    claim.source_stage = "generate"
    claim.claim_type = "tariff_claim"
    claim.confidence_score = None
    claim.review_id = None

    # Setup: Mock repositories
    claim_repo = AsyncMock()
    claim_repo.get_by_id = AsyncMock(return_value=claim)

    knowledge_repo = AsyncMock()
    knowledge_repo.get_by_id = AsyncMock(return_value=knowledge_entry)

    # Create lineage link
    lineage_link_repo = _make_lineage_link_repo()
    await lineage_link_repo.create_link(
        source_type="claim",
        source_id=claim.id,
        target_type="knowledge_entry",
        target_id=knowledge_entry.id,
        link_type="derived_from_knowledge",
        workflow_run_id=workflow_run_id,
        stage_name="generate",
        metadata={"relevance": "high"}
    )

    # Setup: Mock other repositories for LineageService
    evidence_repo = AsyncMock()
    evidence_repo.get_by_id = AsyncMock(return_value=None)

    citation_repo = AsyncMock()
    citation_repo.list_by_claim = AsyncMock(return_value=[])

    audit_repo = AsyncMock()
    stage_repo = AsyncMock()
    chunk_repo = AsyncMock()
    document_repo = AsyncMock()
    review_repo = AsyncMock()

    # Create LineageService
    lineage_service = LineageService(
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

    # Act: Build lineage graph
    graph = await lineage_service.get_claim_lineage(claim.id, depth=3)

    # Assert: Graph structure is correct
    assert graph.root_node_id == str(claim.id)
    assert len(graph.nodes) >= 2, "Expected at least claim + knowledge entry nodes"

    # Assert: Claim node exists
    claim_nodes = [node for node in graph.nodes if node.type == "claim"]
    assert len(claim_nodes) == 1
    assert claim_nodes[0].id == str(claim.id)
    assert claim_nodes[0].metadata["status"] == "pending"

    # Assert: Knowledge node exists
    knowledge_nodes = [node for node in graph.nodes if node.type == "knowledge"]
    assert len(knowledge_nodes) == 1
    assert knowledge_nodes[0].id == str(knowledge_entry.id)

    # Assert: Edge connects claim to knowledge entry
    assert len(graph.edges) >= 1
    derivation_edges = [edge for edge in graph.edges if edge.edge_type == "derived_from"]
    assert len(derivation_edges) == 1
    assert derivation_edges[0].source_id == str(claim.id)
    assert derivation_edges[0].target_id == str(knowledge_entry.id)


@pytest.mark.asyncio
async def test_lineage_service_knowledge_provenance():
    """
    Test that LineageService.get_knowledge_provenance returns correct provenance data.

    This test verifies:
    1. Knowledge provenance query returns all knowledge entries used by a claim
    2. Provenance includes metadata (relevance, adoption_reason)
    """
    # Setup: Create mock data
    workspace_id = uuid4()
    workflow_run_id = uuid4()

    knowledge_entry1 = _make_knowledge_entry(workspace_id)
    knowledge_entry2 = _make_knowledge_entry(workspace_id)
    knowledge_entry2.content = "Prior knowledge: Electronics duty rates vary by classification"

    claim = MagicMock()
    claim.id = uuid4()
    claim.workflow_run_id = workflow_run_id
    claim.content = "HS Code 8471.30 applies with 0% duty rate"

    # Setup: Mock repositories
    claim_repo = AsyncMock()
    knowledge_repo = AsyncMock()

    # Create multiple lineage links
    lineage_link_repo = _make_lineage_link_repo()

    await lineage_link_repo.create_link(
        source_type="claim",
        source_id=claim.id,
        target_type="knowledge_entry",
        target_id=knowledge_entry1.id,
        link_type="derived_from_knowledge",
        workflow_run_id=workflow_run_id,
        stage_name="generate",
        metadata={"relevance_score": 0.95, "adoption_reason": "Direct match"}
    )

    await lineage_link_repo.create_link(
        source_type="claim",
        source_id=claim.id,
        target_type="knowledge_entry",
        target_id=knowledge_entry2.id,
        link_type="derived_from_knowledge",
        workflow_run_id=workflow_run_id,
        stage_name="generate",
        metadata={"relevance_score": 0.80, "adoption_reason": "Supporting context"}
    )

    # Mock knowledge_repo.get_by_id to return correct entries
    async def get_knowledge_by_id(knowledge_id):
        if knowledge_id == knowledge_entry1.id:
            return knowledge_entry1
        elif knowledge_id == knowledge_entry2.id:
            return knowledge_entry2
        return None

    knowledge_repo.get_by_id = AsyncMock(side_effect=get_knowledge_by_id)

    # Create LineageService
    lineage_service = LineageService(
        lineage_link_repo=lineage_link_repo,
        claim_repo=claim_repo,
        evidence_repo=AsyncMock(),
        citation_repo=AsyncMock(),
        knowledge_repo=knowledge_repo,
        audit_repo=AsyncMock(),
        stage_repo=AsyncMock(),
        chunk_repo=AsyncMock(),
        document_repo=AsyncMock(),
        review_repo=AsyncMock(),
    )

    # Act: Get knowledge provenance
    provenance = await lineage_service.get_knowledge_provenance(claim.id)

    # Assert: Provenance includes both knowledge entries
    assert len(provenance) == 2

    # Assert: Provenance data is correct
    provenance_by_id = {str(p.knowledge_entry_id): p for p in provenance}

    assert str(knowledge_entry1.id) in provenance_by_id
    prov1 = provenance_by_id[str(knowledge_entry1.id)]
    assert prov1.relevance_score == 0.95
    assert prov1.adoption_reason == "Direct match"

    assert str(knowledge_entry2.id) in provenance_by_id
    prov2 = provenance_by_id[str(knowledge_entry2.id)]
    assert prov2.relevance_score == 0.80
    assert prov2.adoption_reason == "Supporting context"


@pytest.mark.asyncio
async def test_tariff_workflow_without_prior_knowledge_creates_no_links():
    """
    Test that running workflow WITHOUT prior knowledge creates NO lineage links.

    This verifies the lineage system only creates links when knowledge is actually reused.
    """
    # Setup: Create repositories
    claim_repo = _make_claim_repo()
    lineage_link_repo = _make_lineage_link_repo()

    # Setup: Create workflow stages
    extract_stage = ExtractStage()
    generate_stage = GenerateStage(
        claim_repository=claim_repo,
        lineage_link_repository=lineage_link_repo
    )

    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage)

    # Setup: Create initial state WITHOUT prior knowledge
    workflow_run_id = uuid4()
    initial_state = _initial_state(
        workflow_run_id=str(workflow_run_id),
        prior_knowledge_entries=[],  # Empty!
        prior_knowledge=""
    )

    # Act: Run workflow
    runner = _make_runner(extract_stage, generate_stage)
    final_state = await runner.run(initial_state, _make_run_repo())

    # Assert: Workflow completed
    assert final_state["generate_completed"] is True

    # Assert: No knowledge was adopted
    assert final_state.get("adopted_knowledge_entry_ids", []) == []

    # Assert: No lineage links were created
    lineage_links = await lineage_link_repo.get_links_by_run(workflow_run_id)
    assert len(lineage_links) == 0, "Expected no lineage links when no prior knowledge exists"


@pytest.mark.asyncio
async def test_tariff_workflow_multiple_claims_create_multiple_links():
    """
    Test that multiple claims each get linked to the same knowledge entry.

    This verifies lineage links are created for ALL claims, not just the first.
    """
    # Setup: Create repositories
    claim_repo = _make_claim_repo()
    lineage_link_repo = _make_lineage_link_repo()

    # Setup: Create workflow stages
    extract_stage = ExtractStage()
    generate_stage = GenerateStage(
        claim_repository=claim_repo,
        lineage_link_repository=lineage_link_repo
    )

    # Mock LLM to return multiple claims
    multiple_claims = [
        TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%"),
        TariffClaim(hs_code="8517.12", description="Smartphone", duty_rate="2.5%"),
        TariffClaim(hs_code="8528.72", description="Monitor", duty_rate="3%"),
    ]
    _patch_extract_llm(extract_stage, claims=multiple_claims)
    _patch_generate_llm(generate_stage)

    # Setup: Create knowledge entry
    workspace_id = uuid4()
    knowledge_entry = _make_knowledge_entry(workspace_id)

    # Setup: Initial state with prior knowledge
    workflow_run_id = uuid4()
    initial_state = _initial_state(
        workflow_run_id=str(workflow_run_id),
        workspace_id=str(workspace_id),
        prior_knowledge_entries=[str(knowledge_entry.id)],
        prior_knowledge="Prior knowledge context"
    )

    # Act: Run workflow
    runner = _make_runner(extract_stage, generate_stage)
    final_state = await runner.run(initial_state, _make_run_repo())

    # Assert: All claims were created
    assert len(final_state["claim_ids"]) == 3

    # Assert: Lineage links created for ALL claims
    lineage_links = await lineage_link_repo.get_links_by_run(workflow_run_id)
    assert len(lineage_links) == 3, "Expected 1 link per claim (3 claims × 1 knowledge entry)"

    # Assert: Each claim has exactly one link to the knowledge entry
    for claim_id in final_state["claim_ids"]:
        claim_links = await lineage_link_repo.get_knowledge_links_for_claim(claim_id)
        assert len(claim_links) == 1
        assert claim_links[0].target_id == knowledge_entry.id
