"""
LangChain BaseTool implementations for SuperDocs operations, live chat, and task execution.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.models import (
    ApprovalMode,
    ExportFormat,
    ModelTier,
    SectionEditMode,
    ThinkingDepth,
    ToolResponse,
)


# -----------------------------------------------------------------------------
# Input Schemas
# -----------------------------------------------------------------------------

class ChatInput(BaseModel):
    session_id: str = Field(..., description="Unique session identifier for conversation & document continuity.")
    message: str = Field(..., description="Natural language instructions to create, edit, or transform the document.")
    document_html: Optional[str] = Field(
        default=None,
        description="Optional initial document HTML. Omit on follow-up turns as server persists state."
    )
    model_tier: str = Field(
        default="core",
        description="AI model tier: 'core' (default, fast), 'turbo', 'pro' (advanced reasoning), 'max'."
    )
    thinking_depth: Optional[str] = Field(
        default=None,
        description="Reasoning depth: 'fast', 'balanced', or 'deep'."
    )
    approval_mode: str = Field(
        default="approve_all",
        description="Review mode: 'approve_all' (default) or 'ask_every_time' for HITL."
    )


class CreateTaskInput(BaseModel):
    session_id: str = Field(..., description="Unique session identifier.")
    message: str = Field(..., description="Instruction or goal for background execution.")
    document_html: Optional[str] = Field(default=None, description="Optional starting HTML.")
    model_tier: str = Field(default="core", description="Model tier: 'core', 'turbo', 'pro', 'max'.")
    thinking_depth: Optional[str] = Field(default=None, description="Reasoning depth: 'fast', 'balanced', 'deep'.")
    approval_mode: str = Field(default="approve_all", description="Approval mode: 'approve_all' or 'ask_every_time'.")


class ExecuteTaskInput(BaseModel):
    session_id: str = Field(..., description="Unique session identifier.")
    message: str = Field(..., description="Instruction or goal to execute to completion.")
    document_html: Optional[str] = Field(default=None, description="Optional initial HTML.")
    model_tier: str = Field(default="core", description="Model tier: 'core', 'turbo', 'pro', 'max'.")
    max_wait_seconds: float = Field(default=120.0, description="Max seconds to wait for completion.")


class GetTaskStatusInput(BaseModel):
    job_id: str = Field(..., description="Unique task / job identifier returned by create_task.")


class ListTasksInput(BaseModel):
    status: Optional[str] = Field(default=None, description="Filter by status: 'pending', 'in_progress', 'completed', 'failed'.")
    session_id: Optional[str] = Field(default=None, description="Optional session filter.")


class CancelTaskInput(BaseModel):
    job_id: str = Field(..., description="Job identifier to abort.")


class CreateDocumentInput(BaseModel):
    title: str = Field(..., description="The title of the new document.")
    content: str = Field(default="", description="Initial Markdown or text content for the document.")
    folder: str = Field(default="default", description="Folder or category to place document in.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Key-value metadata or tags.")


class GetDocumentInput(BaseModel):
    document_id: str = Field(..., description="Unique identifier of the document to retrieve.")
    include_outline: bool = Field(default=False, description="Whether to include section outline structure.")
    section_id: Optional[str] = Field(default=None, description="Optional specific section heading or ID to extract.")


class EditSectionInput(BaseModel):
    document_id: str = Field(..., description="Target document or session identifier.")
    section_target: str = Field(..., description="Heading title or section ID to modify.")
    content: str = Field(default="", description="New content to insert or replace with.")
    mode: Union[SectionEditMode, str] = Field(
        default=SectionEditMode.REPLACE,
        description="Edit mode: 'replace', 'append', 'prepend', or 'delete'."
    )
    heading: Optional[str] = Field(default=None, description="Optional revised heading text.")


class SearchInput(BaseModel):
    query: str = Field(..., description="Search terms or keywords.")
    top_k: int = Field(default=5, description="Maximum number of search results to return.")
    tag_filter: Optional[str] = Field(default=None, description="Optional metadata tag filter.")


class RenderTemplateInput(BaseModel):
    template_id: str = Field(
        ...,
        description="ID of the template to render (e.g., 'tech-spec', 'pr-description', 'incident-report')."
    )
    variables: Dict[str, Any] = Field(
        ...,
        description="Dictionary of variable substitutions for template placeholders."
    )
    target_title: Optional[str] = Field(
        default=None,
        description="Title for the rendered document."
    )
    folder: str = Field(default="default", description="Target folder location.")


class ExportDocumentInput(BaseModel):
    document_id: Optional[str] = Field(default=None, description="Document or session identifier.")
    session_id: Optional[str] = Field(default=None, description="Session ID holding document state.")
    html_content: Optional[str] = Field(default=None, description="Raw HTML string to export.")
    export_format: Union[ExportFormat, str] = Field(
        default=ExportFormat.DOCX,
        description="Format: 'docx', 'pdf', 'markdown', 'html', 'text', 'json'."
    )


class AddCommentInput(BaseModel):
    document_id: str = Field(..., description="Target document ID.")
    content: str = Field(..., description="Feedback, critique, or suggestion text.")
    section_id: Optional[str] = Field(default=None, description="Optional target section identifier.")
    author: str = Field(default="reviewer-agent", description="Author identifier.")


class HistoryInput(BaseModel):
    document_id: str = Field(..., description="Target document identifier.")


class SessionHistoryInput(BaseModel):
    session_id: str = Field(..., description="Session identifier to restore.")


class SessionRevertInput(BaseModel):
    session_id: str = Field(..., description="Unique user-chosen session identifier")
    turn_index: int = Field(..., description="0-indexed position of user message to rewind to")


# -----------------------------------------------------------------------------
# Base SuperDocs Tool
# -----------------------------------------------------------------------------

class _SuperDocsBaseTool(BaseTool):
    """Base class for all SuperDocs tools with shared client."""
    client: SuperDocsClient = Field(default_factory=SuperDocsClient)

    def _format_response(self, response: ToolResponse) -> str:
        """Convert ToolResponse to a clean JSON string for LLMs."""
        return json.dumps(response.model_dump(), indent=2)


# -----------------------------------------------------------------------------
# Concrete BaseTool Implementations
# -----------------------------------------------------------------------------

class SuperDocsChatTool(_SuperDocsBaseTool):
    """Tool for direct AI document drafting and editing via SuperDocs live API."""
    name: str = "superdocs_chat"
    description: str = (
        "Send natural language instructions to SuperDocs AI to create or modify documents. "
        "Preserves document state across turns using session_id."
    )
    args_schema: Type[BaseModel] = ChatInput

    def _run(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        thinking_depth: Optional[str] = None,
        approval_mode: str = "approve_all",
        **kwargs: Any,
    ) -> str:
        res = self.client.chat(
            session_id=session_id,
            message=message,
            document_html=document_html,
            model_tier=model_tier,
            thinking_depth=thinking_depth,
            approval_mode=approval_mode,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsCreateTaskTool(_SuperDocsBaseTool):
    """Tool for creating background asynchronous SuperDocs tasks."""
    name: str = "superdocs_create_task"
    description: str = (
        "Create an asynchronous background SuperDocs task/job (/v1/chat/async). "
        "Returns a job_id for status tracking and non-blocking execution."
    )
    args_schema: Type[BaseModel] = CreateTaskInput

    def _run(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        thinking_depth: Optional[str] = None,
        approval_mode: str = "approve_all",
        **kwargs: Any,
    ) -> str:
        res = self.client.create_task(
            session_id=session_id,
            message=message,
            document_html=document_html,
            model_tier=model_tier,
            thinking_depth=thinking_depth,
            approval_mode=approval_mode,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsExecuteTaskTool(_SuperDocsBaseTool):
    """Tool for creating and executing a task to completion with live status polling."""
    name: str = "superdocs_execute_task"
    description: str = (
        "Create and synchronously poll a SuperDocs background task until completion. "
        "Returns the final generated document HTML, summary of changes, and AI reply."
    )
    args_schema: Type[BaseModel] = ExecuteTaskInput

    def _run(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        max_wait_seconds: float = 120.0,
        **kwargs: Any,
    ) -> str:
        res = self.client.execute_task_and_wait(
            session_id=session_id,
            message=message,
            document_html=document_html,
            model_tier=model_tier,
            max_wait=max_wait_seconds,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsGetTaskStatusTool(_SuperDocsBaseTool):
    """Tool for checking the status and progress of an async task by job_id."""
    name: str = "superdocs_get_task_status"
    description: str = (
        "Check the live execution status, progress percentage (0-100), and intermediate results "
        "of an async SuperDocs task by job_id."
    )
    args_schema: Type[BaseModel] = GetTaskStatusInput

    def _run(self, job_id: str, **kwargs: Any) -> str:
        res = self.client.get_task_status(job_id=job_id)
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsListTasksTool(_SuperDocsBaseTool):
    """Tool for listing active and completed SuperDocs async tasks."""
    name: str = "superdocs_list_tasks"
    description: str = (
        "List background async tasks/jobs, optionally filtered by status ('pending', 'in_progress', 'completed')."
    )
    args_schema: Type[BaseModel] = ListTasksInput

    def _run(self, status: Optional[str] = None, session_id: Optional[str] = None, **kwargs: Any) -> str:
        res = self.client.list_tasks(status=status, session_id=session_id)
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsCancelTaskTool(_SuperDocsBaseTool):
    """Tool for cancelling a pending or in-progress SuperDocs task."""
    name: str = "superdocs_cancel_task"
    description: str = "Cancel a running or queued SuperDocs task by job_id."
    args_schema: Type[BaseModel] = CancelTaskInput

    def _run(self, job_id: str, **kwargs: Any) -> str:
        res = self.client.cancel_task(job_id=job_id)
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsCreateDocumentTool(_SuperDocsBaseTool):
    """Tool for creating new documents in SuperDocs."""
    name: str = "superdocs_create_document"
    description: str = "Create a new SuperDocs document with initial title and content."
    args_schema: Type[BaseModel] = CreateDocumentInput

    def _run(
        self,
        title: str,
        content: str = "",
        folder: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        res = self.client.create_document(
            title=title,
            content=content,
            folder=folder,
            metadata=metadata or {},
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsGetDocumentTool(_SuperDocsBaseTool):
    """Tool for reading SuperDocs documents, section outlines, or specific sections."""
    name: str = "superdocs_get_document"
    description: str = "Retrieve full content or specific sections/outlines of an existing document."
    args_schema: Type[BaseModel] = GetDocumentInput

    def _run(
        self,
        document_id: str,
        include_outline: bool = False,
        section_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        res = self.client.get_document(
            document_id=document_id,
            include_outline=include_outline,
            section_id=section_id,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsEditSectionTool(_SuperDocsBaseTool):
    """Tool for modifying specific sections of a document."""
    name: str = "superdocs_edit_section"
    description: str = "Edit, replace, append, prepend, or delete specific sections in a SuperDocs document."
    args_schema: Type[BaseModel] = EditSectionInput

    def _run(
        self,
        document_id: str,
        section_target: str,
        content: str = "",
        mode: Union[SectionEditMode, str] = SectionEditMode.REPLACE,
        heading: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        res = self.client.edit_section(
            document_id=document_id,
            section_target=section_target,
            content=content,
            mode=mode,
            new_heading=heading,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsSearchTool(_SuperDocsBaseTool):
    """Tool for searching document contents across the workspace."""
    name: str = "superdocs_search"
    description: str = "Search SuperDocs documents for keywords or semantic terms."
    args_schema: Type[BaseModel] = SearchInput

    def _run(
        self,
        query: str,
        top_k: int = 5,
        tag_filter: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        res = self.client.search_documents(
            query=query,
            top_k=top_k,
            tag_filter=tag_filter,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsRenderTemplateTool(_SuperDocsBaseTool):
    """Tool for instantiating standard templates."""
    name: str = "superdocs_render_template"
    description: str = "Render a built-in document template ('tech-spec', 'pr-description', 'incident-report') with variables."
    args_schema: Type[BaseModel] = RenderTemplateInput

    def _run(
        self,
        template_id: str,
        variables: Dict[str, Any],
        target_title: Optional[str] = None,
        folder: str = "default",
        **kwargs: Any,
    ) -> str:
        res = self.client.render_template(
            template_id=template_id,
            variables=variables,
            target_title=target_title,
            folder=folder,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsExportDocumentTool(_SuperDocsBaseTool):
    """Tool for exporting documents to styled DOCX, PDF, HTML, Markdown, or plain text."""
    name: str = "superdocs_export_document"
    description: str = (
        "Export a SuperDocs document to DOCX, PDF, HTML, Markdown, or JSON. "
        "Pass session_id, document_id, or raw html_content."
    )
    args_schema: Type[BaseModel] = ExportDocumentInput

    def _run(
        self,
        document_id: Optional[str] = None,
        session_id: Optional[str] = None,
        html_content: Optional[str] = None,
        export_format: Union[ExportFormat, str] = ExportFormat.DOCX,
        **kwargs: Any,
    ) -> str:
        res = self.client.export_document(
            document_id=document_id,
            session_id=session_id,
            html_content=html_content,
            export_format=export_format,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsAddCommentTool(_SuperDocsBaseTool):
    """Tool for adding review comments or inline critiques."""
    name: str = "superdocs_add_comment"
    description: str = "Add a review comment or feedback suggestion to a document."
    args_schema: Type[BaseModel] = AddCommentInput

    def _run(
        self,
        document_id: str,
        content: str,
        section_id: Optional[str] = None,
        author: str = "reviewer-agent",
        **kwargs: Any,
    ) -> str:
        res = self.client.add_comment(
            document_id=document_id,
            content=content,
            section_id=section_id,
            author=author,
        )
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsHistoryTool(_SuperDocsBaseTool):
    """Tool for retrieving document version snapshot history."""
    name: str = "superdocs_get_history"
    description: str = "Retrieve full version history snapshots for a document."
    args_schema: Type[BaseModel] = HistoryInput

    def _run(self, document_id: str, **kwargs: Any) -> str:
        res = self.client.get_document_history(document_id=document_id)
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsListSessionsTool(_SuperDocsBaseTool):
    """Tool for listing active document editing sessions."""
    name: str = "superdocs_list_sessions"
    description: str = "List all active document editing sessions with message counts and previews."

    def _run(self, **kwargs: Any) -> str:
        res = self.client.list_sessions()
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsGetSessionHistoryTool(_SuperDocsBaseTool):
    """Tool for retrieving full conversation history and current document state for a session."""
    name: str = "superdocs_get_session_history"
    description: str = "Retrieve full conversation turn history and current document HTML for a session."
    args_schema: Type[BaseModel] = SessionHistoryInput

    def _run(self, session_id: str, **kwargs: Any) -> str:
        res = self.client.get_session_history(session_id=session_id)
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsSessionRevertTool(_SuperDocsBaseTool):
    """Tool for rewinding a session to a previous turn."""
    name: str = "superdocs_revert_session"
    description: str = "Rewind session state to before a specific turn index."
    args_schema: Type[BaseModel] = SessionRevertInput

    def _run(self, session_id: str, turn_index: int, **kwargs: Any) -> str:
        res = self.client.revert_session(session_id=session_id, turn_index=turn_index)
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class SuperDocsListDocumentsTool(_SuperDocsBaseTool):
    """Tool for listing durable saved documents (Files view)."""
    name: str = "superdocs_list_documents"
    description: str = "List all durable documents saved in the SuperDocs account with metadata and session counts."

    def _run(self, **kwargs: Any) -> str:
        res = self.client.list_documents()
        return self._format_response(res)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


# Aliases
SuperDocsCommentTool = SuperDocsAddCommentTool
SuperDocsExportTool = SuperDocsExportDocumentTool
SuperDocsTemplateRenderTool = SuperDocsRenderTemplateTool
SuperDocsSessionHistoryTool = SuperDocsGetSessionHistoryTool

ALL_SUPERDOCS_TOOLS = [
    SuperDocsCreateDocumentTool,
    SuperDocsGetDocumentTool,
    SuperDocsEditSectionTool,
    SuperDocsSearchTool,
    SuperDocsRenderTemplateTool,
    SuperDocsExportDocumentTool,
    SuperDocsAddCommentTool,
    SuperDocsHistoryTool,
    SuperDocsChatTool,
    SuperDocsListSessionsTool,
    SuperDocsGetSessionHistoryTool,
    SuperDocsSessionRevertTool,
    SuperDocsCreateTaskTool,
    SuperDocsExecuteTaskTool,
    SuperDocsGetTaskStatusTool,
    SuperDocsListTasksTool,
    SuperDocsCancelTaskTool,
    SuperDocsListDocumentsTool,
]
