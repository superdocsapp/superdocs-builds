import pytest
from backend.core.workflow.registry import WorkflowRegistry
from backend.tests.unit.core.workflow.test_stage import TestState, TestStage


def test_register_workflow():
    """Test registering a workflow"""
    registry = WorkflowRegistry()

    stage1 = TestStage("stage1")
    stage2 = TestStage("stage2")

    registry.register(
        workflow_name="test_workflow",
        stages=[stage1, stage2],
        edges=[("stage1", "stage2"), ("stage2", "END")],
        state_schema=TestState,
        description="Test workflow"
    )

    workflow = registry.get("test_workflow")
    assert workflow is not None
    assert workflow["name"] == "test_workflow"
    assert len(workflow["stages"]) == 2


def test_register_duplicate_workflow():
    """Test that registering duplicate workflow raises error"""
    registry = WorkflowRegistry()

    stage = TestStage("stage1")

    registry.register(
        workflow_name="test_workflow",
        stages=[stage],
        edges=[("stage1", "END")],
        state_schema=TestState
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            workflow_name="test_workflow",
            stages=[stage],
            edges=[("stage1", "END")],
            state_schema=TestState
        )


def test_list_workflows():
    """Test listing registered workflows"""
    registry = WorkflowRegistry()

    stage1 = TestStage("stage1")
    stage2 = TestStage("stage2")

    registry.register(
        workflow_name="workflow1",
        stages=[stage1],
        edges=[("stage1", "END")],
        state_schema=TestState,
        description="First workflow"
    )

    registry.register(
        workflow_name="workflow2",
        stages=[stage1, stage2],
        edges=[("stage1", "stage2"), ("stage2", "END")],
        state_schema=TestState,
        description="Second workflow"
    )

    workflows = registry.list_workflows()
    assert len(workflows) == 2
    assert workflows[0]["name"] == "workflow1"
    assert workflows[0]["stage_count"] == 1
    assert workflows[1]["name"] == "workflow2"
    assert workflows[1]["stage_count"] == 2


def test_unregister_workflow():
    """Test unregistering a workflow"""
    registry = WorkflowRegistry()

    stage = TestStage("stage1")

    registry.register(
        workflow_name="test_workflow",
        stages=[stage],
        edges=[("stage1", "END")],
        state_schema=TestState
    )

    assert registry.unregister("test_workflow")
    assert registry.get("test_workflow") is None
    assert not registry.unregister("test_workflow")


def test_validate_workflow_no_stages():
    """Test validation fails with no stages"""
    registry = WorkflowRegistry()

    with pytest.raises(ValueError, match="at least one stage"):
        registry.register(
            workflow_name="empty_workflow",
            stages=[],
            edges=[],
            state_schema=TestState
        )


def test_validate_workflow_duplicate_stage_names():
    """Test validation fails with duplicate stage names"""
    registry = WorkflowRegistry()

    stage1 = TestStage("duplicate")
    stage2 = TestStage("duplicate")

    with pytest.raises(ValueError, match="duplicate stage names"):
        registry.register(
            workflow_name="dup_workflow",
            stages=[stage1, stage2],
            edges=[("duplicate", "END")],
            state_schema=TestState
        )


def test_validate_workflow_invalid_edge():
    """Test validation fails with invalid edge reference"""
    registry = WorkflowRegistry()

    stage = TestStage("stage1")

    with pytest.raises(ValueError, match="unknown stage"):
        registry.register(
            workflow_name="bad_workflow",
            stages=[stage],
            edges=[("stage1", "nonexistent")],
            state_schema=TestState
        )


@pytest.mark.asyncio
async def test_create_runner():
    """Test creating a WorkflowRunner from registered workflow"""
    from unittest.mock import AsyncMock

    registry = WorkflowRegistry()

    stage1 = TestStage("stage1")
    stage2 = TestStage("stage2")

    registry.register(
        workflow_name="test_workflow",
        stages=[stage1, stage2],
        edges=[("stage1", "stage2"), ("stage2", "END")],
        state_schema=TestState,
        description="Test workflow"
    )

    # Create mock stage repository
    mock_stage_repo = AsyncMock()

    runner = registry.create_runner("test_workflow", mock_stage_repo)

    assert runner is not None
    assert runner.workflow_name == "test_workflow"
    assert len(runner.stages) == 2


def test_create_runner_nonexistent_workflow():
    """Test creating runner for nonexistent workflow raises error"""
    registry = WorkflowRegistry()

    from unittest.mock import AsyncMock
    mock_stage_repo = AsyncMock()

    with pytest.raises(ValueError, match="not found in registry"):
        registry.create_runner("nonexistent", mock_stage_repo)


def test_validate_workflow_no_edges():
    """Test validation fails with no edges"""
    registry = WorkflowRegistry()

    stage = TestStage("stage1")

    with pytest.raises(ValueError, match="at least one edge"):
        registry.register(
            workflow_name="no_edges_workflow",
            stages=[stage],
            edges=[],
            state_schema=TestState
        )


def test_validate_workflow_no_entry_point():
    """Test validation fails when all stages have incoming edges"""
    registry = WorkflowRegistry()

    stage1 = TestStage("stage1")
    stage2 = TestStage("stage2")

    # Create circular dependency - no entry point
    with pytest.raises(ValueError, match="no entry point"):
        registry.register(
            workflow_name="circular_workflow",
            stages=[stage1, stage2],
            edges=[("stage1", "stage2"), ("stage2", "stage1")],
            state_schema=TestState
        )
