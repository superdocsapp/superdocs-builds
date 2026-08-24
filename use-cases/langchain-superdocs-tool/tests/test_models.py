"""
Unit tests for Pydantic data models.
"""

from superdocs_langchain.models import (
    DocumentComment,
    DocumentSection,
    DocumentVersion,
    ExportFormat,
    SearchResult,
    SectionEditMode,
    SuperDocument,
    TemplateDefinition,
    ToolResponse,
)


def test_document_section_model():
    sec = DocumentSection(
        id="sec-1",
        heading="Introduction",
        level=1,
        content="Introductory remarks.",
    )
    assert sec.id == "sec-1"
    assert sec.heading == "Introduction"
    assert sec.level == 1
    assert sec.content == "Introductory remarks."
    assert sec.metadata == {}


def test_super_document_model():
    doc = SuperDocument(
        id="doc-123",
        title="Test Document",
        content="# Test Document\n\nBody content",
        folder="projects",
        version=2,
    )
    assert doc.id == "doc-123"
    assert doc.title == "Test Document"
    assert doc.version == 2
    assert doc.created_at is not None


def test_tool_response_serialization():
    resp = ToolResponse(
        success=True,
        message="Operation succeeded",
        data={"id": "doc-1", "title": "My Doc"},
    )
    dumped = resp.model_dump()
    assert dumped["success"] is True
    assert dumped["data"]["id"] == "doc-1"
    assert dumped["error"] is None


def test_export_format_enum():
    assert ExportFormat.MARKDOWN.value == "markdown"
    assert ExportFormat.HTML.value == "html"
    assert ExportFormat.TEXT.value == "text"
    assert ExportFormat.JSON.value == "json"


def test_section_edit_mode_enum():
    assert SectionEditMode.REPLACE.value == "replace"
    assert SectionEditMode.APPEND.value == "append"
    assert SectionEditMode.PREPEND.value == "prepend"
    assert SectionEditMode.DELETE.value == "delete"


def test_dynamic_task_plan_and_item_models():
    from superdocs_langchain.models import DynamicTaskPlan, TaskPlanItem, PlanApprovalState
    
    item = TaskPlanItem(
        id="TASK-1",
        step=1,
        phase="Planning",
        title="Outline Architecture",
        description="Draft initial scope",
        tool="superdocs_chat",
    )
    assert item.id == "TASK-1"
    assert item.status == "pending"

    plan = DynamicTaskPlan(
        user_prompt="Draft DR plan",
        session_id="sess-1",
        tasks=[item],
        approval_status=PlanApprovalState.PENDING_REVIEW,
    )
    assert plan.is_complex is True
    assert len(plan.tasks) == 1
    assert plan.approval_status == PlanApprovalState.PENDING_REVIEW
    dumped = plan.model_dump()
    assert dumped["tasks"][0]["title"] == "Outline Architecture"

