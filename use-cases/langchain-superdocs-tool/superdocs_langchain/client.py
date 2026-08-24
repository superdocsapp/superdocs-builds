"""
Unified SuperDocs REST API & MCP Client with Live Task Execution & Offline Engine.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from dotenv import find_dotenv, load_dotenv
    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()
except ImportError:
    pass

import requests
from superdocs_langchain.models import (
    AccountWhoamiResponse,
    ApprovalMode,
    DocumentChanges,
    DocumentComment,
    DocumentSection,
    DocumentState,
    DocumentVersion,
    EditorAction,
    ExportFormat,
    ModelTier,
    SearchResult,
    SectionEditMode,
    SessionHistoryResponse,
    SessionMessage,
    SessionRevertResponse,
    SessionSummary,
    SuperDocsChatResponse,
    SuperDocsJob,
    SuperDocsUsage,
    SuperDocument,
    TaskStatus,
    TemplateDefinition,
    ThinkingDepth,
    ToolResponse,
)

logger = logging.getLogger(__name__)


def _parse_markdown_into_sections(markdown_text: str) -> List[DocumentSection]:
    """Parse a markdown string into hierarchical sections by headings."""
    lines = markdown_text.splitlines()
    sections: List[DocumentSection] = []
    
    current_heading = "Overview"
    current_level = 1
    current_lines: List[str] = []
    sec_idx = 1

    heading_regex = re.compile(r"^(#{1,6})\s+(.*)$")

    for line in lines:
        match = heading_regex.match(line)
        if match:
            if current_lines or sections:
                sec_id = f"sec-{sec_idx}-{re.sub(r'[^a-zA-Z0-9]', '-', current_heading.lower()).strip('-')}"
                sections.append(
                    DocumentSection(
                        id=sec_id,
                        heading=current_heading,
                        level=current_level,
                        content="\n".join(current_lines).strip(),
                    )
                )
                sec_idx += 1
                current_lines = []
            
            hashes, title = match.groups()
            current_level = len(hashes)
            current_heading = title.strip()
        else:
            current_lines.append(line)

    # Add final section
    sec_id = f"sec-{sec_idx}-{re.sub(r'[^a-zA-Z0-9]', '-', current_heading.lower()).strip('-')}"
    sections.append(
        DocumentSection(
            id=sec_id,
            heading=current_heading,
            level=current_level,
            content="\n".join(current_lines).strip(),
        )
    )

    return sections


def _reconstruct_markdown_from_sections(sections: List[DocumentSection]) -> str:
    """Recombine DocumentSection objects back into a cohesive markdown document."""
    parts = []
    for sec in sections:
        prefix = "#" * sec.level
        heading_line = f"{prefix} {sec.heading}"
        if sec.content:
            parts.append(f"{heading_line}\n\n{sec.content}")
        else:
            parts.append(heading_line)
    return "\n\n".join(parts)


class SuperDocsClient:
    """
    Unified client for interacting with SuperDocs via live REST API,
    asynchronous background task queues, and embedded offline mock engine.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 45.0,
        offline: Optional[bool] = None,
    ):
        raw_base_url = base_url or os.getenv("SUPERDOCS_BASE_URL") or "https://api.superdocs.app/v1"
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        self.timeout = timeout

        # Normalize base URL (strip trailing slashes, ensure /v1 presence if root host given)
        cleaned_url = raw_base_url.rstrip("/")
        if cleaned_url and not cleaned_url.endswith("/v1") and "superdocs.app" in cleaned_url:
            cleaned_url = f"{cleaned_url}/v1"
        self.base_url = cleaned_url

        # Determine offline mode
        if offline is None:
            # Go live if API key is present, else fallback to offline mock engine
            self.offline = not bool(self.api_key)
        else:
            self.offline = offline

        # In-memory mock database for offline execution
        self._documents: Dict[str, SuperDocument] = {}
        self._versions: Dict[str, List[DocumentVersion]] = {}
        self._comments: Dict[str, List[DocumentComment]] = {}
        self._templates: Dict[str, TemplateDefinition] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._jobs: Dict[str, SuperDocsJob] = {}

        self._seed_default_templates()

    def _seed_default_templates(self) -> None:
        """Seed built-in document templates."""
        templates = [
            TemplateDefinition(
                template_id="tech-spec",
                title="Technical Architecture Specification",
                description="Standard technical design document template.",
                raw_template=(
                    "# Technical Specification: {{ project_name }}\n\n"
                    "## Executive Summary\n{{ summary }}\n\n"
                    "## Architecture & Design\n{{ architecture }}\n\n"
                    "## API Specifications\n{{ api_specs }}\n\n"
                    "## Security & Verification\n{{ security }}"
                ),
                required_variables=["project_name", "summary", "architecture"],
            ),
            TemplateDefinition(
                template_id="pr-description",
                title="Pull Request Description",
                description="Template for structured pull request documentation.",
                raw_template=(
                    "# PR: {{ title }}\n\n"
                    "## Summary of Changes\n{{ changes }}\n\n"
                    "## Motivation & Context\n{{ motivation }}\n\n"
                    "## Verification & Testing\n{{ testing }}"
                ),
                required_variables=["title", "changes", "testing"],
            ),
            TemplateDefinition(
                template_id="incident-report",
                title="Incident Post-Mortem Report",
                description="Template for site reliability incident reviews.",
                raw_template=(
                    "# Post-Mortem: {{ incident_title }}\n\n"
                    "## Incident Overview\n**Date**: {{ date }}\n**Severity**: {{ severity }}\n\n"
                    "## Root Cause Analysis\n{{ root_cause }}\n\n"
                    "## Timeline of Events\n{{ timeline }}\n\n"
                    "## Corrective Action Items\n{{ action_items }}"
                ),
                required_variables=["incident_title", "severity", "root_cause"],
            ),
        ]
        for t in templates:
            self._templates[t.template_id] = t

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SuperDocs-LangChain-Adapter/0.2.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # -------------------------------------------------------------------------
    # Account & Quota Operations
    # -------------------------------------------------------------------------

    def get_whoami(self) -> ToolResponse:
        """Fetch authenticated account status, quota, tier, and remaining credits."""
        if not self.offline:
            try:
                resp = requests.get(
                    f"{self.base_url}/agents/whoami",
                    headers=self._headers(),
                    timeout=min(self.timeout, 5.0),
                )
                resp.raise_for_status()
                data = resp.json()
                quota = data.get("quota") or {}
                parsed = AccountWhoamiResponse(
                    account_id=data.get("account_id", ""),
                    tier=data.get("tier", "free"),
                    monthly_limit=quota.get("monthly_limit", 1000),
                    used=quota.get("used", 0),
                    remaining=quota.get("remaining", 1000),
                    resets_at=quota.get("resets_at"),
                )
                return ToolResponse(
                    success=True,
                    message=f"SuperDocs account verified ({parsed.tier} tier, {parsed.remaining} remaining operations).",
                    data=parsed.model_dump(),
                )
            except Exception as e:
                logger.error(f"Live API whoami error: {e}")
                return ToolResponse(success=False, message="Failed to fetch account status.", error=str(e))

        return ToolResponse(
            success=True,
            message="SuperDocs Offline Mock Account active.",
            data={
                "account_id": "mock-account-local-001",
                "tier": "offline-pro",
                "monthly_limit": 10000,
                "used": 0,
                "remaining": 10000,
                "resets_at": None,
            },
        )

    # -------------------------------------------------------------------------
    # Live SuperDocs Chat & AI Document Editing (/v1/chat)
    # -------------------------------------------------------------------------

    def chat(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        thinking_depth: Optional[str] = None,
        approval_mode: str = "approve_all",
        document_id: Optional[str] = None,
        cross_session_memory: Optional[bool] = None,
        cross_session_search: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> ToolResponse:
        """
        Send a chat message to create or edit a document with the live SuperDocs AI.
        Maintains conversation & document state server-side across turns with `session_id`.
        """
        if not self.offline:
            try:
                payload: Dict[str, Any] = {
                    "session_id": session_id,
                    "message": message,
                    "model_tier": model_tier,
                    "approval_mode": approval_mode,
                }
                if document_html is not None:
                    payload["document_html"] = document_html
                if thinking_depth:
                    payload["thinking_depth"] = thinking_depth
                if document_id:
                    payload["document_id"] = document_id
                if cross_session_memory is not None:
                    payload["cross_session_memory"] = cross_session_memory
                if cross_session_search is not None:
                    payload["cross_session_search"] = cross_session_search

                call_timeout = timeout if timeout is not None else self.timeout
                resp = requests.post(
                    f"{self.base_url}/chat",
                    json=payload,
                    headers=self._headers(),
                    timeout=call_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                chat_resp = SuperDocsChatResponse(**data)
                return ToolResponse(
                    success=True,
                    message=chat_resp.response,
                    data=chat_resp.model_dump(),
                )
            except Exception as e:
                logger.error(f"Live chat error: {e}")
                return ToolResponse(
                    success=False,
                    message=f"SuperDocs live chat error: {str(e)}",
                    error=str(e),
                )

        # Offline Mock Implementation
        sess = self._sessions.setdefault(session_id, {
            "session_id": session_id,
            "messages": [],
            "document_html": document_html or "<h1>Document</h1><p>Initial content</p>",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

        if document_html:
            sess["document_html"] = document_html

        updated_html = sess["document_html"]
        # Format headings based on prompt intent
        msg_lower = message.lower()
        if "introduction" in msg_lower:
            updated_html += "<h2>Introduction</h2><p>Overview of project and system scope.</p>"
        elif "budget" in msg_lower:
            updated_html += "<h2>Budget</h2><p>Financial allocations and cost breakdown.</p>"
        elif "architecture" in msg_lower:
            updated_html += "<h2>Architecture</h2><p>System design and subsystem components.</p>"
        elif "<p>" in updated_html:
            updated_html = updated_html.replace("</p>", f" {html.escape(message)}</p>", 1)
        else:
            updated_html += f"<p>{html.escape(message)}</p>"
        sess["document_html"] = updated_html

        reply_text = f"Offline Engine executed edit: '{message}'"
        user_turn = len(sess["messages"])
        sess["messages"].append({
            "turn_index": user_turn,
            "checkpoint_id": f"chk_{user_turn}_{uuid.uuid4().hex[:6]}",
            "role": "user",
            "content": message,
        })
        ai_turn = len(sess["messages"])
        sess["messages"].append({
            "turn_index": ai_turn,
            "checkpoint_id": f"chk_{ai_turn}_{uuid.uuid4().hex[:6]}",
            "role": "assistant",
            "content": reply_text,
        })

        mock_data = {
            "response": reply_text,
            "session_id": session_id,
            "turn_index": ai_turn,
            "document_state": {
                "document_html": updated_html,
                "version_id": f"v{ai_turn}",
            },
            "document_changes": {
                "updated_html": updated_html,
                "changes_summary": f"Offline mock applied: {message[:40]}...",
            },
            "usage": {
                "monthly_used": 1,
                "monthly_limit": 1000,
                "monthly_remaining": 999,
                "was_billable": False,
                "subscription_tier": "offline-mock",
            },
        }
        return ToolResponse(success=True, message=reply_text, data=mock_data)

    def revert_session(self, session_id: str, turn_index: int) -> ToolResponse:
        """Rewind a session to before a specific turn index."""
        if not self.offline:
            try:
                resp = requests.post(
                    f"{self.base_url}/sessions/{session_id}/revert",
                    json={"turn_index": turn_index},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="Session reverted.", data=resp.json())
            except Exception as e:
                logger.error(f"Error reverting session: {e}")
                return ToolResponse(success=False, message="Failed to revert session.", error=str(e))

        if session_id not in self._sessions:
            return ToolResponse(success=False, message=f"Session '{session_id}' not found.", error="NotFound")

        sess = self._sessions[session_id]
        messages = sess.get("messages", [])

        reverted_msg_text = ""
        for m in messages:
            if m.get("turn_index") == turn_index:
                reverted_msg_text = m.get("content", "")
                break

        # Keep messages before turn_index
        kept_messages = [m for m in messages if m.get("turn_index", 0) < turn_index]
        archived_count = len(messages) - len(kept_messages)
        sess["messages"] = kept_messages

        # Reset document HTML
        sess["document_html"] = "<h1>Restored Document</h1><p>Restored state</p>"

        return ToolResponse(
            success=True,
            message=f"Reverted session '{session_id}' to turn {turn_index - 1}.",
            data=SessionRevertResponse(
                compose_text=reverted_msg_text or f"Reverted turn {turn_index}",
                reverted_to_turn=turn_index - 1,
                document_state=DocumentState(document_html=sess["document_html"]),
                editor_action=EditorAction.UPDATE,
                archived_turn_count=archived_count,
            ).model_dump(),
        )

    # -------------------------------------------------------------------------
    # SuperDocs Task Creation & Background Job Operations (/v1/chat/async & /v1/jobs)
    # -------------------------------------------------------------------------

    def create_task(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        thinking_depth: Optional[str] = None,
        approval_mode: str = "approve_all",
        document_id: Optional[str] = None,
        response_mode: str = "full",
    ) -> ToolResponse:
        """
        Create a new background task / asynchronous AI job via POST /v1/chat/async.
        Returns a job_id for progress polling and status verification.
        """
        if not self.offline:
            try:
                payload: Dict[str, Any] = {
                    "session_id": session_id,
                    "message": message,
                    "model_tier": model_tier,
                    "approval_mode": approval_mode,
                    "response_mode": response_mode,
                    "async_mode": True,
                }
                if document_html is not None:
                    payload["document_html"] = document_html
                if thinking_depth:
                    payload["thinking_depth"] = thinking_depth
                if document_id:
                    payload["document_id"] = document_id

                resp = requests.post(
                    f"{self.base_url}/chat/async",
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                job_id = data.get("job_id")
                return ToolResponse(
                    success=True,
                    message=f"SuperDocs task created successfully with Job ID: {job_id}",
                    data=data,
                )
            except Exception as e:
                logger.error(f"Failed to create SuperDocs async task: {e}")
                return ToolResponse(
                    success=False,
                    message=f"Failed to create SuperDocs task: {str(e)}",
                    error=str(e),
                )

        # Offline Mock Engine
        job_id = f"job_mock_{uuid.uuid4().hex[:12]}"
        job = SuperDocsJob(
            job_id=job_id,
            session_id=session_id,
            status=TaskStatus.PENDING,
            progress=10,
            metadata={"message": message, "document_html": document_html, "model_tier": model_tier},
        )
        self._jobs[job_id] = job
        return ToolResponse(
            success=True,
            message=f"Mock SuperDocs task created with Job ID: {job_id}",
            data={"job_id": job_id, "session_id": session_id, "status": "pending"},
        )

    def get_task_status(self, job_id: str) -> ToolResponse:
        """Retrieve the live progress, execution status, and result of an async task by job_id."""
        if not self.offline:
            try:
                resp = requests.get(
                    f"{self.base_url}/jobs/{job_id}",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "unknown")
                progress = data.get("progress", 0)
                return ToolResponse(
                    success=True,
                    message=f"Task {job_id} status: {status} ({progress}%).",
                    data=data,
                )
            except Exception as e:
                logger.error(f"Error fetching task status for {job_id}: {e}")
                return ToolResponse(
                    success=False,
                    message=f"Failed to fetch task status for {job_id}",
                    error=str(e),
                )

        # Offline Mock Polling
        if job_id not in self._jobs:
            return ToolResponse(success=False, message=f"Job {job_id} not found in offline engine.", error="NotFound")
        job = self._jobs[job_id]
        if job.status == TaskStatus.PENDING:
            job.status = TaskStatus.IN_PROGRESS
            job.progress = 50
        elif job.status == TaskStatus.IN_PROGRESS:
            job.status = TaskStatus.COMPLETED
            job.progress = 100
            msg = job.metadata.get("message", "Task finished")
            job.result = {
                "response": f"✅ [Offline Engine] Completed task: {msg}",
                "session_id": job.session_id,
                "document_changes": {
                    "updated_html": f"<div data-chunk-id='sec-1'><h1>Completed Document</h1><p>{html.escape(msg)}</p></div>",
                    "changes_summary": "Document generated by offline engine",
                },
            }
        return ToolResponse(
            success=True,
            message=f"Mock Task {job_id} status: {job.status.value} ({job.progress}%).",
            data=job.model_dump(),
        )

    def execute_task_and_wait(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        thinking_depth: Optional[str] = None,
        approval_mode: str = "approve_all",
        poll_interval: float = 2.0,
        max_wait: float = 180.0,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> ToolResponse:
        """
        Create a live SuperDocs task and poll until completion, invoking progress callbacks.
        Returns the final completed document HTML and AI response.
        """
        create_res = self.create_task(
            session_id=session_id,
            message=message,
            document_html=document_html,
            model_tier=model_tier,
            thinking_depth=thinking_depth,
            approval_mode=approval_mode,
        )
        if not create_res.success or not create_res.data:
            return create_res

        job_id = create_res.data.get("job_id")
        if not job_id:
            return ToolResponse(success=False, message="No job_id returned during task creation.", error="MissingJobId")

        start_time = time.time()
        while time.time() - start_time < max_wait:
            status_res = self.get_task_status(job_id)
            if not status_res.success:
                time.sleep(poll_interval)
                continue

            job_data = status_res.data or {}
            status = job_data.get("status")

            if progress_callback:
                try:
                    progress_callback(job_data)
                except Exception as cb_err:
                    logger.debug(f"Progress callback exception: {cb_err}")

            if status == "completed":
                result = job_data.get("result") or {}
                reply = result.get("response", "Task completed successfully.")
                return ToolResponse(
                    success=True,
                    message=reply,
                    data={
                        "job_id": job_id,
                        "session_id": session_id,
                        "status": "completed",
                        "response": reply,
                        "document_changes": result.get("document_changes"),
                        "raw_result": result,
                    },
                )
            elif status == "failed":
                err_msg = job_data.get("error") or "Task execution failed on SuperDocs server."
                return ToolResponse(success=False, message=f"Task {job_id} failed: {err_msg}", error=err_msg)
            elif status == "cancelled":
                return ToolResponse(success=False, message=f"Task {job_id} was cancelled.", error="Cancelled")
            elif status == "awaiting_approval":
                return ToolResponse(
                    success=True,
                    message=f"Task {job_id} is awaiting human approval.",
                    data=job_data,
                )

            time.sleep(poll_interval)

        return ToolResponse(
            success=False,
            message=f"Task {job_id} timed out after {max_wait} seconds.",
            error="Timeout",
        )

    def list_tasks(self, status: Optional[str] = None, session_id: Optional[str] = None) -> ToolResponse:
        """List active, pending, or completed async chat jobs."""
        if not self.offline:
            try:
                url = f"{self.base_url}/sessions/{session_id}/jobs" if session_id else f"{self.base_url}/jobs"
                params = {"status": status} if status else {}
                resp = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
                resp.raise_for_status()
                return ToolResponse(success=True, message="Jobs retrieved.", data=resp.json())
            except Exception as e:
                logger.error(f"Error listing tasks: {e}")
                return ToolResponse(success=False, message="Failed to list tasks.", error=str(e))

        # Offline Mock
        jobs_list = [j.model_dump() for j in self._jobs.values()]
        if status:
            jobs_list = [j for j in jobs_list if j.get("status") == status]
        if session_id:
            jobs_list = [j for j in jobs_list if j.get("session_id") == session_id]
        return ToolResponse(success=True, message="Mock tasks listed.", data={"jobs": jobs_list, "total": len(jobs_list)})

    def cancel_task(self, job_id: str) -> ToolResponse:
        """Cancel an in-progress or pending SuperDocs job."""
        if not self.offline:
            try:
                resp = requests.post(
                    f"{self.base_url}/jobs/{job_id}/cancel",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message=f"Task {job_id} cancelled.", data=resp.json())
            except Exception as e:
                logger.error(f"Error cancelling task {job_id}: {e}")
                return ToolResponse(success=False, message=f"Failed to cancel task {job_id}.", error=str(e))

        if job_id in self._jobs:
            self._jobs[job_id].status = TaskStatus.CANCELLED
            return ToolResponse(success=True, message=f"Mock task {job_id} marked as cancelled.", data={"job_id": job_id, "status": "cancelled"})
        return ToolResponse(success=False, message=f"Task {job_id} not found.", error="NotFound")

    def approve_task(self, session_id: str, decisions: List[Dict[str, Any]]) -> ToolResponse:
        """Approve or deny AI-proposed document changes for HITL workflow."""
        if not self.offline:
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/{session_id}/approve",
                    json={"decisions": decisions},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="HITL decisions submitted.", data=resp.json())
            except Exception as e:
                logger.error(f"Error submitting HITL approval: {e}")
                return ToolResponse(success=False, message="Failed to submit approval decisions.", error=str(e))

        return ToolResponse(success=True, message="Mock HITL decisions approved.", data={"session_id": session_id, "status": "approved"})

    # -------------------------------------------------------------------------
    # Saved Documents & Files Operations (/v1/documents)
    # -------------------------------------------------------------------------

    def list_documents(self) -> ToolResponse:
        """List authenticated user's durable saved documents (Files view)."""
        if not self.offline:
            try:
                resp = requests.get(
                    f"{self.base_url}/documents",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="Documents retrieved.", data=resp.json())
            except Exception as e:
                logger.error(f"Error listing documents: {e}")
                return ToolResponse(success=False, message="Failed to list documents.", error=str(e))

        # Offline Mock
        docs = [d.model_dump() for d in self._documents.values()]
        return ToolResponse(success=True, message="Mock documents listed.", data={"documents": docs, "total": len(docs)})

    def get_document(
        self,
        document_id: str,
        include_outline: bool = False,
        section_id: Optional[str] = None,
    ) -> ToolResponse:
        """Get saved document details, structure outline, or specific section."""
        if not self.offline:
            try:
                resp = requests.get(
                    f"{self.base_url}/documents/{document_id}",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="Document details retrieved.", data=resp.json())
            except Exception as e:
                logger.error(f"Error getting document {document_id}: {e}")
                return ToolResponse(success=False, message=f"Failed to get document {document_id}.", error=str(e))

        if document_id not in self._documents:
            return ToolResponse(success=False, message=f"Document '{document_id}' not found.", error="NotFound")

        doc = self._documents[document_id]
        if section_id:
            for s in doc.sections:
                if s.id.lower() == section_id.lower() or s.heading.lower() == section_id.lower():
                    return ToolResponse(success=True, message=f"Section '{s.heading}' found.", data=s.model_dump())
            return ToolResponse(success=False, message=f"Section '{section_id}' not found.", error="SectionNotFound")

        doc_dict = doc.model_dump()
        if include_outline:
            doc_dict["outline"] = [{"id": s.id, "heading": s.heading, "level": s.level} for s in doc.sections]

        return ToolResponse(success=True, message="Document retrieved.", data=doc_dict)

    def save_document(self, session_id: str, document_id: str, document_html: str) -> ToolResponse:
        """Autosave human/non-AI edits to a document in a session."""
        if not self.offline:
            try:
                resp = requests.post(
                    f"{self.base_url}/sessions/{session_id}/documents/{document_id}/save",
                    json={"document_html": document_html},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="Document saved.", data=resp.json())
            except Exception as e:
                logger.error(f"Error saving document: {e}")
                return ToolResponse(success=False, message="Failed to save document.", error=str(e))

        if session_id in self._sessions:
            self._sessions[session_id]["document_html"] = document_html
        return ToolResponse(success=True, message="Mock document autosaved.", data={"session_id": session_id, "document_id": document_id})

    def export_document(
        self,
        document_id: Optional[str] = None,
        export_format: Union[ExportFormat, str] = "docx",
        html_content: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResponse:
        """Export document to DOCX, PDF, HTML, Markdown, JSON, or plain text."""
        fmt_str = export_format.value if hasattr(export_format, "value") else str(export_format) # type: ignore
        target_session = session_id or document_id

        if not self.offline:
            try:
                payload: Dict[str, Any] = {"format": fmt_str}
                if target_session:
                    payload["session_id"] = target_session
                elif html_content:
                    payload["html"] = html_content

                resp = requests.post(
                    f"{self.base_url}/documents/export",
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()

                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    data = resp.json()
                    return ToolResponse(success=True, message=f"Document exported to {fmt_str}.", data=data)
                elif "text" in content_type or fmt_str in ("markdown", "html", "txt", "text", "json"):
                    text_content = resp.text
                    return ToolResponse(
                        success=True,
                        message=f"Document exported to {fmt_str}.",
                        data={"format": fmt_str, "content": text_content, "length": len(text_content)},
                    )
                else:
                    import base64
                    b64_content = base64.b64encode(resp.content).decode("utf-8")
                    return ToolResponse(
                        success=True,
                        message=f"Document exported to {fmt_str} ({len(resp.content)} bytes).",
                        data={"format": fmt_str, "content_base64": b64_content, "size_bytes": len(resp.content)},
                    )
            except Exception as e:
                logger.error(f"Error exporting document: {e}")
                return ToolResponse(success=False, message="Failed to export document.", error=str(e))

        # Offline Mock
        raw = html_content
        doc_obj = self._documents.get(target_session or "")
        if not raw:
            if doc_obj:
                raw = doc_obj.content
            elif target_session in self._sessions:
                raw = self._sessions[target_session].get("document_html", "")
            else:
                raw = "# Sample Document"

        title = doc_obj.title if doc_obj else "Exported Document"

        if fmt_str == "html":
            formatted = f"<!DOCTYPE html><html><head><title>{title}</title></head><body><h1>{title}</h1>{raw}</body></html>"
        elif fmt_str == "json":
            formatted = json.dumps({"title": title, "content": raw})
        elif fmt_str == "text":
            formatted = re.sub(r"[#*_`]", "", raw)
        else:
            formatted = raw

        return ToolResponse(
            success=True,
            message=f"Mock exported to {fmt_str}.",
            data={"format": fmt_str, "content": formatted, "download_url": f"https://mock.superdocs.local/download/{fmt_str}"},
        )

    # -------------------------------------------------------------------------
    # Sessions Operations (/v1/sessions)
    # -------------------------------------------------------------------------

    def list_sessions(self) -> ToolResponse:
        """List active document editing sessions."""
        if not self.offline:
            try:
                resp = requests.get(
                    f"{self.base_url}/sessions",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="Sessions retrieved.", data=resp.json())
            except Exception as e:
                logger.error(f"Error listing sessions: {e}")
                return ToolResponse(success=False, message="Failed to list sessions.", error=str(e))

        # Offline Mock
        sess_list = [
            {
                "session_id": s_id,
                "message_count": len(s_data.get("messages", [])),
                "created_at": s_data.get("created_at", ""),
                "preview": s_data.get("messages", [{}])[0].get("content", "") if s_data.get("messages") else "New session",
            }
            for s_id, s_data in self._sessions.items()
        ]
        return ToolResponse(success=True, message="Mock sessions retrieved.", data={"sessions": sess_list, "total": len(sess_list)})

    def get_session_history(self, session_id: str) -> ToolResponse:
        """Restore full conversation and document state for a session."""
        if not self.offline:
            try:
                resp = requests.get(
                    f"{self.base_url}/sessions/{session_id}/history",
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return ToolResponse(success=True, message="Session history loaded.", data=resp.json())
            except Exception as e:
                logger.error(f"Error getting session history for {session_id}: {e}")
                return ToolResponse(success=False, message=f"Failed to get history for {session_id}.", error=str(e))

        if session_id in self._sessions:
            s_data = self._sessions[session_id]
            messages = [
                SessionMessage(
                    turn_index=m.get("turn_index", i),
                    checkpoint_id=m.get("checkpoint_id", f"chk_{i}"),
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                )
                for i, m in enumerate(s_data.get("messages", []))
            ]
            doc_state = DocumentState(document_html=s_data.get("document_html", ""))
            return ToolResponse(
                success=True,
                message=f"Loaded mock session '{session_id}'.",
                data={
                    "session_id": session_id,
                    "messages": [m.model_dump() for m in messages],
                    "document_state": doc_state.model_dump(),
                    "editor_action": "update",
                },
            )
        return ToolResponse(success=False, message=f"Session '{session_id}' not found.", error="NotFound")

    # -------------------------------------------------------------------------
    # Legacy / Utility Document & Template Helpers
    # -------------------------------------------------------------------------

    def create_document(
        self,
        title: str,
        content: str = "",
        folder: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolResponse:
        """Create a new document (calls live chat to create or registers in offline mock)."""
        if not self.offline:
            session_id = f"doc-init-{uuid.uuid4().hex[:8]}"
            initial_html = f"<h1>{html.escape(title)}</h1>\n" + (f"<p>{html.escape(content)}</p>" if content else "")
            prompt = f"Create initial document titled '{title}'." if not content else f"Initialize document '{title}' with content."
            chat_res = self.chat(session_id=session_id, message=prompt, document_html=initial_html)
            if chat_res.success and chat_res.data:
                return ToolResponse(
                    success=True,
                    message=f"Document '{title}' created via live SuperDocs session '{session_id}'.",
                    data={
                        "id": session_id,
                        "title": title,
                        "session_id": session_id,
                        "content": chat_res.data.get("document_changes", {}).get("updated_html", initial_html),
                        "response": chat_res.message,
                    },
                )
            return chat_res

        # Offline Mock
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        sections = _parse_markdown_into_sections(content) if content else [
            DocumentSection(id="sec-1-overview", heading="Overview", level=1, content="")
        ]
        doc = SuperDocument(
            id=doc_id,
            title=title,
            content=content,
            sections=sections,
            folder=folder,
            metadata=metadata or {},
            version=1,
        )
        self._documents[doc_id] = doc
        self._versions[doc_id] = [DocumentVersion(version_id="v1", author="creator", summary="Initial document", content=content)]
        self._comments[doc_id] = []
        return ToolResponse(success=True, message=f"Created document '{title}' (ID: {doc_id}).", data=doc.model_dump())

    def edit_section(
        self,
        document_id: str,
        section_target: str,
        content: str = "",
        mode: Union[SectionEditMode, str] = SectionEditMode.REPLACE,
        new_heading: Optional[str] = None,
        author: str = "agent",
    ) -> ToolResponse:
        """Edit a specific document section (via live chat or offline engine)."""
        if not self.offline:
            prompt = f"Edit section '{section_target}': {mode} with '{content}'"
            if new_heading:
                prompt += f" and change heading to '{new_heading}'"
            return self.chat(session_id=document_id, message=prompt)

        # Offline Mock
        if document_id not in self._documents:
            return ToolResponse(success=False, message=f"Document '{document_id}' not found.", error="NotFound")
        doc = self._documents[document_id]
        target_sec = None
        for s in doc.sections:
            if s.id.lower() == section_target.lower() or s.heading.lower() == section_target.lower():
                target_sec = s
                break
        if not target_sec:
            target_sec = DocumentSection(id=f"sec-{len(doc.sections)+1}-{section_target.lower()}", heading=section_target, level=2, content="")
            doc.sections.append(target_sec)

        if isinstance(mode, str):
            mode = SectionEditMode(mode)

        if mode == SectionEditMode.REPLACE:
            target_sec.content = content
        elif mode == SectionEditMode.APPEND:
            target_sec.content = f"{target_sec.content}\n\n{content}".strip()
        elif mode == SectionEditMode.PREPEND:
            target_sec.content = f"{content}\n\n{target_sec.content}".strip()
        elif mode == SectionEditMode.DELETE:
            doc.sections.remove(target_sec)

        if new_heading and mode != SectionEditMode.DELETE:
            target_sec.heading = new_heading

        doc.content = _reconstruct_markdown_from_sections(doc.sections)
        doc.version += 1

        self._versions.setdefault(document_id, []).append(
            DocumentVersion(
                version_id=f"v{doc.version}",
                author=author,
                summary=f"Edited section {section_target}",
                content=doc.content,
            )
        )

        return ToolResponse(success=True, message=f"Section '{section_target}' updated.", data=doc.model_dump())

    def search(
        self,
        query: str,
        top_k: int = 5,
        tag_filter: Optional[str] = None,
    ) -> ToolResponse:
        """Search documents across account."""
        return self.search_documents(query=query, top_k=top_k, tag_filter=tag_filter)

    def search_documents(
        self,
        query: str,
        top_k: int = 5,
        tag_filter: Optional[str] = None,
    ) -> ToolResponse:
        """Search documents across account."""
        if not self.offline:
            list_res = self.list_documents()
            if list_res.success and list_res.data:
                docs = list_res.data.get("documents", [])
                results = []
                for d in docs:
                    title = d.get("title", "")
                    if any(w.lower() in title.lower() for w in query.split()):
                        results.append(SearchResult(
                            document_id=d.get("document_id", ""),
                            title=title,
                            snippet=f"Document '{title}' (Version {d.get('version', 1)})",
                            score=1.0,
                        ).model_dump())
                return ToolResponse(
                    success=True,
                    message=f"Found {len(results)} matches for '{query}'.",
                    data={"query": query, "results": results[:top_k], "total": len(results)},
                )

        # Offline Mock
        matches = []
        q_words = [w.lower() for w in query.split() if w]
        for doc_id, doc in self._documents.items():
            if tag_filter:
                doc_tags = [t.lower() for t in doc.metadata.get("tags", [])]
                if tag_filter.lower() not in doc_tags and tag_filter.lower() not in doc.folder.lower():
                    continue

            content_lower = doc.content.lower()
            title_lower = doc.title.lower()

            matched = False
            if any(w in title_lower or w in content_lower for w in q_words):
                matched = True
            elif query.lower() in title_lower or query.lower() in content_lower:
                matched = True

            if matched:
                matches.append(SearchResult(
                    document_id=doc_id,
                    title=doc.title,
                    snippet=doc.content[:150],
                    score=1.0,
                ).model_dump())

        return ToolResponse(
            success=True,
            message=f"Found {len(matches)} results.",
            data={"query": query, "results": matches[:top_k], "total": len(matches)},
        )

    def render_template(
        self,
        template_id: str,
        variables: Dict[str, Any],
        target_title: Optional[str] = None,
        folder: str = "default",
    ) -> ToolResponse:
        """Render a document template with variables."""
        if template_id not in self._templates:
            return ToolResponse(success=False, message=f"Template '{template_id}' not found.", error="NotFound")
        tmpl = self._templates[template_id]
        rendered = tmpl.raw_template
        for k, v in variables.items():
            rendered = rendered.replace(f"{{{{ {k} }}}}", str(v)).replace(f"{{{{{k}}}}}", str(v))

        title = target_title or tmpl.title
        return self.create_document(title=title, content=rendered, folder=folder)

    def add_comment(
        self,
        document_id: str,
        content: str,
        section_id: Optional[str] = None,
        author: str = "reviewer-agent",
    ) -> ToolResponse:
        """Add a review comment."""
        comment_id = f"cmt_{uuid.uuid4().hex[:6]}"
        comment = DocumentComment(
            id=comment_id,
            document_id=document_id,
            section_id=section_id,
            author=author,
            content=content,
        )
        self._comments.setdefault(document_id, []).append(comment)
        return ToolResponse(success=True, message=f"Comment added to {document_id}.", data=comment.model_dump())

    def get_comments(self, document_id: str) -> ToolResponse:
        """Retrieve comments for a document."""
        cmts = [c.model_dump() for c in self._comments.get(document_id, [])]
        return ToolResponse(success=True, message=f"Found {len(cmts)} comments.", data={"document_id": document_id, "comments": cmts})

    def get_history(self, document_id: str) -> ToolResponse:
        """Get document version snapshot history."""
        return self.get_document_history(document_id)

    def get_document_history(self, document_id: str) -> ToolResponse:
        """Get document version snapshot history."""
        if not self.offline:
            return self.get_session_history(document_id)
        versions = [v.model_dump() for v in self._versions.get(document_id, [])]
        return ToolResponse(success=True, message=f"Retrieved history for {document_id}.", data={"document_id": document_id, "versions": versions})

    def revert_version(self, document_id: str, version_id: str) -> ToolResponse:
        """Revert document to a previous historical version."""
        if document_id not in self._documents:
            return ToolResponse(success=False, message=f"Document '{document_id}' not found.", error="NotFound")
        versions = self._versions.get(document_id, [])
        target_v = None
        for v in versions:
            if v.version_id == version_id:
                target_v = v
                break
        if not target_v:
            return ToolResponse(success=False, message=f"Version '{version_id}' not found.", error="VersionNotFound")

        doc = self._documents[document_id]
        doc.content = target_v.content
        doc.sections = _parse_markdown_into_sections(doc.content)
        doc.version += 1
        return ToolResponse(success=True, message=f"Reverted to version '{version_id}'.", data=doc.model_dump())

    # -------------------------------------------------------------------------
    # Dynamic Tool Discovery & Execution Helpers
    # -------------------------------------------------------------------------

    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Return tool declarations for dynamic schema binding."""
        return [
            {
                "name": "superdocs_create_document",
                "description": "Create a new document in SuperDocs",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Document title"},
                        "content": {"type": "string", "description": "Initial content"},
                        "folder": {"type": "string", "description": "Folder location", "default": "default"},
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "superdocs_get_document",
                "description": "Retrieve a document by ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Document identifier"},
                        "include_outline": {"type": "boolean", "description": "Include outline", "default": False},
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "superdocs_edit_section",
                "description": "Edit or mutate a specific section in a document",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Document identifier"},
                        "section_target": {"type": "string", "description": "Heading or section ID"},
                        "content": {"type": "string", "description": "New content"},
                        "mode": {"type": "string", "description": "Edit mode", "default": "replace"},
                    },
                    "required": ["document_id", "section_target"],
                },
            },
            {
                "name": "superdocs_search",
                "description": "Search workspace documents",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search terms"},
                        "top_k": {"type": "integer", "description": "Max results", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "superdocs_render_template",
                "description": "Render a document template",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_id": {"type": "string", "description": "Template identifier"},
                        "variables": {"type": "object", "description": "Variable map"},
                        "target_title": {"type": "string", "description": "Title"},
                    },
                    "required": ["template_id", "variables"],
                },
            },
            {
                "name": "superdocs_export_document",
                "description": "Export document to DOCX, PDF, HTML, or Markdown",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Document or session ID"},
                        "export_format": {"type": "string", "description": "Export format", "default": "docx"},
                    },
                    "required": ["document_id"],
                },
            },
            {
                "name": "superdocs_add_comment",
                "description": "Add a critique or review comment",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string", "description": "Document identifier"},
                        "content": {"type": "string", "description": "Comment feedback"},
                        "author": {"type": "string", "description": "Author name", "default": "reviewer-agent"},
                    },
                    "required": ["document_id", "content"],
                },
            },
            {
                "name": "superdocs_chat",
                "description": "Live AI conversational document editing with session state",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Session identifier"},
                        "message": {"type": "string", "description": "Instruction message"},
                        "document_html": {"type": "string", "description": "Initial HTML"},
                    },
                    "required": ["session_id", "message"],
                },
            },
            {
                "name": "superdocs_create_task",
                "description": "Create async background document generation task",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Session identifier"},
                        "message": {"type": "string", "description": "Instruction goal"},
                    },
                    "required": ["session_id", "message"],
                },
            },
            {
                "name": "superdocs_get_task_status",
                "description": "Poll background task execution status",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "Job identifier"},
                    },
                    "required": ["job_id"],
                },
            },
        ]

    def execute_dynamic_tool(self, tool_name: str, args: Dict[str, Any]) -> ToolResponse:
        """Execute a dynamic tool by name."""
        if tool_name in ("superdocs_create_document", "create_document"):
            return self.create_document(
                title=args.get("title", "Untitled"),
                content=args.get("content", ""),
                folder=args.get("folder", "default"),
                metadata=args.get("metadata"),
            )
        elif tool_name in ("superdocs_get_document", "get_document"):
            return self.get_document(
                document_id=args.get("document_id", ""),
                include_outline=args.get("include_outline", False),
                section_id=args.get("section_id"),
            )
        elif tool_name in ("superdocs_edit_section", "edit_section"):
            return self.edit_section(
                document_id=args.get("document_id", ""),
                section_target=args.get("section_target", ""),
                content=args.get("content", ""),
                mode=args.get("mode", "replace"),
                new_heading=args.get("new_heading"),
            )
        elif tool_name in ("superdocs_search", "search", "search_documents"):
            return self.search_documents(
                query=args.get("query", ""),
                top_k=args.get("top_k", 5),
                tag_filter=args.get("tag_filter"),
            )
        elif tool_name in ("superdocs_render_template", "render_template"):
            return self.render_template(
                template_id=args.get("template_id", ""),
                variables=args.get("variables", {}),
                target_title=args.get("target_title"),
                folder=args.get("folder", "default"),
            )
        elif tool_name in ("superdocs_export_document", "export_document", "superdocs_export"):
            return self.export_document(
                document_id=args.get("document_id"),
                session_id=args.get("session_id"),
                export_format=args.get("export_format", "docx"),
                html_content=args.get("html_content"),
            )
        elif tool_name in ("superdocs_add_comment", "add_comment"):
            return self.add_comment(
                document_id=args.get("document_id", ""),
                content=args.get("content", ""),
                section_id=args.get("section_id"),
                author=args.get("author", "reviewer-agent"),
            )
        elif tool_name in ("superdocs_chat", "chat"):
            return self.chat(
                session_id=args.get("session_id", "default"),
                message=args.get("message", ""),
                document_html=args.get("document_html"),
            )
        elif tool_name in ("superdocs_create_task", "create_task"):
            return self.create_task(
                session_id=args.get("session_id", "default"),
                message=args.get("message", ""),
                document_html=args.get("document_html"),
            )
        elif tool_name in ("superdocs_get_task_status", "get_task_status"):
            return self.get_task_status(job_id=args.get("job_id", ""))
        else:
            return ToolResponse(success=False, message=f"Dynamic tool '{tool_name}' not implemented.", error="UnknownTool")
