import pytest

from backend.config import settings
from backend.core.workflow.registry import WorkflowRegistry
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.workflow import (
    build_registry_stages,
    register_tariff_workflow,
    _registry_stage_names,
)


@pytest.fixture
def isolated_registry(monkeypatch):
    """Use an isolated registry for tariff workflow tests."""
    registry = WorkflowRegistry()
    monkeypatch.setattr("backend.modules.tariff.workflow.workflow_registry", registry)
    return registry


def _expected_edges(has_superdocs: bool):
    if has_superdocs:
        return [
            ("superdocs_upload", "focused_update"),
            ("focused_update", "discover_documents"),
            ("discover_documents", "load_product_content"),
            ("load_product_content", "load_ruling_content"),
            ("load_ruling_content", "knowledge_retrieve"),
            ("knowledge_retrieve", "extract_product_facts"),
            ("extract_product_facts", "extract_ruling_facts"),
            ("extract_ruling_facts", "reconcile_documents"),
            ("reconcile_documents", "retrieve"),
            ("retrieve", "generate_memo_sections"),
            ("generate_memo_sections", "citations"),
            ("citations", "quality_gate"),
            ("quality_gate", "superdocs_instruction"),
            ("superdocs_instruction", "superdocs_approval"),
            ("superdocs_approval", "superdocs_export"),
            ("superdocs_export", "knowledge_store"),
            ("knowledge_store", "END"),
        ]
    return [
        ("focused_update", "discover_documents"),
        ("discover_documents", "load_product_content"),
        ("load_product_content", "load_ruling_content"),
        ("load_ruling_content", "knowledge_retrieve"),
        ("knowledge_retrieve", "extract_product_facts"),
        ("extract_product_facts", "extract_ruling_facts"),
        ("extract_ruling_facts", "reconcile_documents"),
        ("reconcile_documents", "retrieve"),
        ("retrieve", "generate_memo_sections"),
        ("generate_memo_sections", "citations"),
        ("citations", "quality_gate"),
        ("quality_gate", "knowledge_store"),
        ("knowledge_store", "END"),
    ]


def test_register_tariff_workflow(isolated_registry):
    """Test tariff workflow registration with registry stub stages."""
    register_tariff_workflow()

    workflow = isolated_registry.get("tariff_classification")
    assert workflow is not None
    assert workflow["name"] == "tariff_classification"

    has_superdocs = bool(getattr(settings, "superdocs_api_key", ""))
    expected_names = _registry_stage_names(has_superdocs)
    assert [stage.name for stage in workflow["stages"]] == expected_names


def test_workflow_definition(isolated_registry):
    """Test workflow stages are connected properly."""
    register_tariff_workflow()

    workflow = isolated_registry.get("tariff_classification")
    edges = workflow["edges"]
    has_superdocs = bool(getattr(settings, "superdocs_api_key", ""))

    for edge in _expected_edges(has_superdocs):
        assert edge in edges

    assert ("knowledge_retrieve", "quality_gate") not in edges
    assert ("citations", "quality_gate") in edges

    terminal_edges = [edge for edge in edges if edge[1] == "END"]
    assert len(terminal_edges) == 1
    assert terminal_edges[0][0] == "knowledge_store"


def test_workflow_metadata(isolated_registry):
    """Test workflow has proper metadata."""
    register_tariff_workflow()

    workflow = isolated_registry.get("tariff_classification")

    assert "memo" in workflow["description"].lower()
    assert workflow["configuration_schema"] is not None
    assert "llm_model" in workflow["configuration_schema"]["properties"]


def test_workflow_state_schema(isolated_registry):
    """Test workflow has correct state schema."""
    register_tariff_workflow()

    workflow = isolated_registry.get("tariff_classification")
    assert workflow["state_schema"] is TariffWorkflowState


def test_workflow_stage_names(isolated_registry):
    """Test workflow list metadata reflects configured stage graph."""
    register_tariff_workflow()

    workflows = isolated_registry.list_workflows()
    assert len(workflows) == 1

    workflow_info = workflows[0]
    has_superdocs = bool(getattr(settings, "superdocs_api_key", ""))
    # Phase 4: added 4 new stages (discover_documents, load_product_content, load_ruling_content, reconcile_documents)
    expected_count = 17 if has_superdocs else 13

    assert workflow_info["name"] == "tariff_classification"
    assert workflow_info["stage_count"] == expected_count
    assert workflow_info["stages"] == _registry_stage_names(has_superdocs)


def test_build_registry_stages_match_edges():
    """Registry stubs must cover every edge endpoint."""
    has_superdocs = bool(getattr(settings, "superdocs_api_key", ""))
    stages = build_registry_stages(has_superdocs)
    stage_names = {stage.name for stage in stages}

    for from_stage, to_stage in _expected_edges(has_superdocs):
        assert from_stage in stage_names
        if to_stage != "END":
            assert to_stage in stage_names
