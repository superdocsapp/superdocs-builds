"""
Pydantic data models for SuperDocs LangChain integration.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"
    JSON = "json"
    DOCX = "docx"
    PDF = "pdf"


class SectionEditMode(str, Enum):
    REPLACE = "replace"
    APPEND = "append"
    PREPEND = "prepend"
    DELETE = "delete"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelTier(str, Enum):
    CORE = "core"
    TURBO = "turbo"
    PRO = "pro"
    MAX = "max"


class ThinkingDepth(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


class ApprovalMode(str, Enum):
    APPROVE_ALL = "approve_all"
    ASK_EVERY_TIME = "ask_every_time"


class PlanApprovalState(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class TaskPlanItem(BaseModel):
    """A single prompt-specific subtask decomposed by the AI planner."""
    id: str = Field(..., description="Unique task identifier, e.g. TASK-1")
    step: int = Field(..., description="Sequential 1-indexed step number")
    phase: str = Field(default="Drafting", description="Lifecycle phase (Planning, Drafting, Audit, Export)")
    title: str = Field(..., description="Prompt-specific, content-aware title")
    description: str = Field(..., description="Tailored instructions and requirements for this subtask")
    target_section: Optional[str] = Field(default=None, description="Document section or heading affected")
    tool: str = Field(default="superdocs_create_task", description="Target SuperDocs tool for execution")
    acceptance_criteria: str = Field(default="", description="Measurable verification criteria")
    estimated_time: str = Field(default="5-10s", description="Estimated execution latency")
    status: str = Field(default="pending", description="pending, approved, in_progress, completed, failed, skipped")
    execution_result: Optional[str] = Field(default=None, description="Output or response after execution")


class DynamicTaskPlan(BaseModel):
    """Complete dynamic execution plan for a specific user prompt."""
    plan_id: str = Field(default_factory=lambda: f"plan_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    user_prompt: str = Field(..., description="Original user prompt")
    session_id: str = Field(..., description="Target SuperDocs session ID")
    is_complex: bool = Field(default=True, description="Whether prompt requires multi-step decomposition")
    decision_rationale: str = Field(default="", description="Why planning was or wasn't needed")
    document_type: str = Field(default="Custom Document", description="Inferred document type")
    tasks: List[TaskPlanItem] = Field(default_factory=list, description="Decomposed subtasks")
    approval_status: Union[PlanApprovalState, str] = Field(default=PlanApprovalState.PENDING_REVIEW, description="Approval status")
    created_at: float = Field(default_factory=lambda: datetime.utcnow().timestamp())
    current_step_index: int = Field(default=0)


class SuperDocsUsage(BaseModel):
    """Usage statistics returned by SuperDocs API."""
    monthly_used: int = Field(default=0, description="Operations used in current billing cycle")
    monthly_limit: int = Field(default=1000, description="Monthly operation limit")
    monthly_remaining: int = Field(default=1000, description="Remaining operations available")
    was_billable: bool = Field(default=True, description="Whether this request consumed an operation")
    subscription_tier: str = Field(default="free", description="Subscription tier (free, pro, enterprise)")


class DocumentChanges(BaseModel):
    """Document modifications returned by SuperDocs chat / async execution."""
    updated_html: Optional[str] = Field(default=None, description="Full updated document HTML")
    changes_summary: Optional[str] = Field(default=None, description="Summary of applied edits")
    chunk_diffs: Optional[List[Dict[str, Any]]] = Field(default=None, description="Granular per-chunk changes")


class SuperDocsChatResponse(BaseModel):
    """Standard response from /v1/chat endpoint."""
    response: str = Field(..., description="The AI's reply explaining what it accomplished")
    session_id: str = Field(..., description="Target session identifier")
    document_changes: Optional[DocumentChanges] = Field(default=None, description="Updated document HTML and changes")
    usage: Optional[SuperDocsUsage] = Field(default=None, description="Operation usage metadata")
    hint: Optional[str] = Field(default=None, description="Helpful API hint or next step suggestion")


class SuperDocsJob(BaseModel):
    """Represents a SuperDocs asynchronous task / job (/v1/chat/async)."""
    job_id: str = Field(..., description="Unique job execution identifier")
    session_id: str = Field(..., description="Target session identifier")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Execution status")
    progress: int = Field(default=0, description="Progress percentage (0-100)")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    result: Optional[Dict[str, Any]] = Field(default=None, description="Job output result payload")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Job execution parameters and metadata")


class AgentTask(BaseModel):
    """Represents a discrete goal or action item in an autonomous agent execution queue."""
    id: str = Field(..., description="Unique task identifier (e.g. task_1)")
    title: str = Field(..., description="Task title or summary")
    description: str = Field(default="", description="Detailed instructions or goal for the task")
    tool_target: Optional[str] = Field(default=None, description="Name of the SuperDocs tool to invoke")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current execution status")
    result: Optional[str] = Field(default=None, description="Output or observation from executing the task")
    job_id: Optional[str] = Field(default=None, description="SuperDocs background job ID if async")


class DocumentSection(BaseModel):
    """Represents a discrete heading-delimited section in a SuperDocs document."""
    id: str = Field(..., description="Unique identifier for the section")
    heading: str = Field(..., description="Heading title of the section")
    level: int = Field(default=2, description="Heading level (1-6)")
    content: str = Field(default="", description="Markdown / text content under the heading")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Section specific metadata")


class DocumentVersion(BaseModel):
    """Snapshot representing a historical version of a document."""
    version_id: str = Field(..., description="Unique version identifier")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="ISO timestamp")
    author: str = Field(default="system", description="Author or agent responsible for version")
    summary: str = Field(default="", description="Summary of changes")
    content: str = Field(..., description="Full document snapshot at this version")


class DocumentComment(BaseModel):
    """Review comment or inline suggestion attached to a document or section."""
    id: str = Field(..., description="Unique comment identifier")
    document_id: str = Field(..., description="Target document identifier")
    section_id: Optional[str] = Field(default=None, description="Optional target section identifier")
    author: str = Field(default="reviewer-agent", description="Comment author")
    content: str = Field(..., description="Feedback, critique, or suggestion")
    resolved: bool = Field(default=False, description="Whether the feedback has been addressed")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="Creation timestamp")


class SuperDocument(BaseModel):
    """SuperDocs document model."""
    id: str = Field(..., description="Unique document ID")
    title: str = Field(..., description="Document title")
    content: str = Field(default="", description="Full raw markdown or HTML content")
    sections: List[DocumentSection] = Field(default_factory=list, description="Parsed sections")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom document metadata/tags")
    folder: str = Field(default="default", description="Folder or workspace path")
    version: int = Field(default=1, description="Current revision counter")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SearchResult(BaseModel):
    """Result item returned by SuperDocs search."""
    document_id: str = Field(..., description="Document identifier")
    title: str = Field(..., description="Document title")
    matched_section: Optional[str] = Field(default=None, description="Matched section heading or ID")
    snippet: str = Field(..., description="Relevant text snippet")
    score: float = Field(default=1.0, description="Relevance score (0.0 to 1.0)")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TemplateDefinition(BaseModel):
    """SuperDocs reusable document template."""
    template_id: str = Field(..., description="Unique template identifier")
    title: str = Field(..., description="Template display name")
    description: str = Field(default="", description="Template description")
    raw_template: str = Field(..., description="Template body containing {{ placeholder }} tokens")
    required_variables: List[str] = Field(default_factory=list, description="List of required variable names")


class EditorAction(str, Enum):
    UPDATE = "update"
    CLEAR = "clear"
    KEEP = "keep"


class SessionMessage(BaseModel):
    """A single turn in a persistent SuperDocs conversation session."""
    turn_index: int = Field(..., description="0-indexed position in the session timeline")
    checkpoint_id: Optional[str] = Field(default=None, description="Marker used by the revert endpoint")
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text content")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class DocumentState(BaseModel):
    """Holds current document state inside a SuperDocs session."""
    document_html: str = Field(default="", description="Current document HTML representation")
    version_id: str = Field(default="v1", description="Current document revision ID")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Attached files or durable resources")


class SessionSummary(BaseModel):
    """Summary item returned by list sessions endpoint."""
    session_id: str = Field(..., description="Unique user-chosen session identifier")
    message_count: int = Field(default=0, description="Total messages in session")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    first_message_preview: Optional[str] = Field(default=None, description="Preview of the initial user message")


class SessionHistoryResponse(BaseModel):
    """Payload returned by load session history endpoint."""
    session_id: str = Field(..., description="Session identifier")
    messages: List[SessionMessage] = Field(default_factory=list, description="Full conversation history")
    document_state: DocumentState = Field(default_factory=DocumentState, description="Current document state")
    editor_action: EditorAction = Field(default=EditorAction.KEEP, description="Action for client editor")


class SessionRevertResponse(BaseModel):
    """Payload returned by revert session endpoint."""
    compose_text: str = Field(..., description="The text of the user message that was reverted")
    reverted_to_turn: int = Field(..., description="Turn index the conversation now ends at")
    document_state: DocumentState = Field(..., description="Restored document state")
    editor_action: EditorAction = Field(default=EditorAction.UPDATE, description="Action for editor")
    archived_turn_count: int = Field(default=1, description="Number of soft-archived rows")


class AccountWhoamiResponse(BaseModel):
    """Account quota and identity information."""
    account_id: str = Field(..., description="Unique SuperDocs account UUID")
    tier: str = Field(default="free", description="Subscription tier")
    monthly_limit: int = Field(default=1000, description="Monthly quota operations")
    used: int = Field(default=0, description="Used operations this month")
    remaining: int = Field(default=1000, description="Remaining quota")
    resets_at: Optional[str] = Field(default=None, description="Reset date timestamp")


class ToolResponse(BaseModel):
    """Standardized response envelope returned by all SuperDocs tools."""
    success: bool = Field(..., description="Whether the operation succeeded")
    message: str = Field(..., description="Human/LLM readable status summary")
    data: Optional[Any] = Field(default=None, description="Structured payload")
    error: Optional[str] = Field(default=None, description="Error details if success is False")
