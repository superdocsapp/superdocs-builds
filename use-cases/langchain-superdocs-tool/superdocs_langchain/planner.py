"""
Dynamic Prompt-Specific Agentic Task Planner with SuperDocs API and HITL Approval Gate.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.models import (
    DynamicTaskPlan,
    PlanApprovalState,
    TaskPlanItem,
    ToolResponse,
)

logger = logging.getLogger(__name__)


class DynamicTaskPlanner:
    """
    Intelligent Agentic Task Planner that uses SuperDocs AI to:
    1. Assess whether a prompt requires multi-step planning.
    2. Decompose complex user goals into prompt-specific, content-aware subtasks.
    3. Provide an interactive Human-in-the-Loop (HITL) review & approval gate.
    4. Coordinate sequential live execution against SuperDocs Cloud API.
    """

    def __init__(self, client: Optional[SuperDocsClient] = None):
        self.client = client or SuperDocsClient()
        self._active_plans: Dict[str, DynamicTaskPlan] = {}

    def evaluate_and_plan(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        document_html: Optional[str] = None,
        model_tier: str = "core",
        thinking_depth: Optional[str] = "balanced",
    ) -> DynamicTaskPlan:
        """
        Analyze the user's prompt using SuperDocs AI to synthesize a prompt-specific task plan.
        """
        sess_id = session_id or f"plan-sess-{uuid.uuid4().hex[:8]}"
        prompt_trimmed = prompt.strip()

        # Step 1: Query SuperDocs AI with a structured planning meta-prompt
        planning_prompt = (
            f"You are an expert Document Architect & Agentic Task Planner. "
            f"Analyze the following user prompt and generate a structured JSON execution plan.\n\n"
            f"USER PROMPT: \"{prompt_trimmed}\"\n\n"
            f"Rules for planning:\n"
            f"1. Determine if this prompt is simple (single minor edit/typo) or complex (new document, multi-section policy/spec, extensive revisions).\n"
            f"2. If complex, decompose the request into 3 to 6 prompt-specific, tailored subtasks based specifically on the entities, sections, and constraints mentioned.\n"
            f"3. Do NOT use generic placeholder titles. Use exact domain terms from the prompt.\n"
            f"4. Respond with ONLY a valid JSON object matching this schema:\n"
            f"{{\n"
            f"  \"is_complex\": true,\n"
            f"  \"decision_rationale\": \"Explanation of complexity\",\n"
            f"  \"document_type\": \"Inferred Document Type (e.g., Enterprise AI Security Policy)\",\n"
            f"  \"tasks\": [\n"
            f"    {{\n"
            f"      \"step\": 1,\n"
            f"      \"phase\": \"Planning & Outline\",\n"
            f"      \"title\": \"Prompt-specific task title\",\n"
            f"      \"description\": \"Detailed instructions tailored to user prompt\",\n"
            f"      \"target_section\": \"Section Name\",\n"
            f"      \"tool\": \"superdocs_chat\",\n"
            f"      \"acceptance_criteria\": \"What determines task success\",\n"
            f"      \"estimated_time\": \"3-5s\"\n"
            f"    }}\n"
            f"  ]\n"
            f"}}"
        )

        plan_data = None

        if not self.client.offline:
            try:
                # Use a planning session
                planner_session = f"planner-meta-{uuid.uuid4().hex[:8]}"
                res = self.client.chat(
                    session_id=planner_session,
                    message=planning_prompt,
                    model_tier="core",
                    thinking_depth=thinking_depth or "balanced",
                )
                if res.success and res.data:
                    raw_reply = res.data.get("response", "")
                    # Extract JSON block
                    json_match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
                    if json_match:
                        plan_data = json.loads(json_match.group(0))
            except Exception as e:
                logger.warning(f"Live SuperDocs AI planning query failed, falling back to smart heuristic: {e}")

        # Fallback / Offline smart dynamic decomposition if live JSON parsing fails
        if not plan_data:
            plan_data = self._smart_heuristic_decomposition(prompt_trimmed)

        # Build TaskPlanItem models
        tasks: List[TaskPlanItem] = []
        raw_tasks = plan_data.get("tasks", [])
        for i, t in enumerate(raw_tasks):
            step_num = t.get("step", i + 1)
            tasks.append(
                TaskPlanItem(
                    id=f"TASK-{step_num}",
                    step=step_num,
                    phase=t.get("phase", "Drafting"),
                    title=t.get("title", f"Step {step_num}"),
                    description=t.get("description", ""),
                    target_section=t.get("target_section"),
                    tool=t.get("tool", "superdocs_create_task"),
                    acceptance_criteria=t.get("acceptance_criteria", "Completed successfully"),
                    estimated_time=t.get("estimated_time", "5-10s"),
                    status="pending",
                )
            )

        plan = DynamicTaskPlan(
            user_prompt=prompt_trimmed,
            session_id=sess_id,
            is_complex=plan_data.get("is_complex", True),
            decision_rationale=plan_data.get("decision_rationale", "Synthesized dynamic execution plan."),
            document_type=plan_data.get("document_type", "Tailored Document"),
            tasks=tasks,
            approval_status="pending_review",
        )

        self._active_plans[plan.plan_id] = plan
        return plan

    def _smart_heuristic_decomposition(self, prompt: str) -> Dict[str, Any]:
        """Smart fallback parser extracting domain topics and clauses directly from prompt."""
        p_lower = prompt.lower()
        words = [w.strip(",.;:()") for w in prompt.split() if len(w) > 3]

        # Simple edit check
        if len(prompt.split()) <= 6 and any(k in p_lower for k in ("fix", "typo", "change heading", "bold", "delete")):
            return {
                "is_complex": False,
                "decision_rationale": "Single direct edit instruction.",
                "document_type": "Document Edit",
                "tasks": [
                    {
                        "step": 1,
                        "phase": "Direct Edit",
                        "title": f"Execute Direct Modification: '{prompt[:40]}'",
                        "description": prompt,
                        "target_section": "Target Section",
                        "tool": "superdocs_chat",
                        "acceptance_criteria": "Direct modification applied in session.",
                        "estimated_time": "2-3s",
                    }
                ],
            }

        # Infer Document Type
        doc_type = "Custom Document"
        if "security" in p_lower or "policy" in p_lower:
            doc_type = "Security & Governance Policy"
        elif "architecture" in p_lower or "design" in p_lower or "spec" in p_lower:
            doc_type = "Technical Architecture Specification"
        elif "agreement" in p_lower or "nda" in p_lower or "contract" in p_lower:
            doc_type = "Legal Agreement"
        elif "disaster recovery" in p_lower or "runbook" in p_lower:
            doc_type = "Disaster Recovery Runbook"
        elif "pr" in p_lower or "pull request" in p_lower:
            doc_type = "Pull Request Documentation"

        # Extract specific items/clauses mentioned
        items = []
        if ":" in prompt:
            after_colon = prompt.split(":", 1)[1]
            items = [seg.strip() for seg in re.split(r",|;|\band\b", after_colon) if len(seg.strip()) > 3]

        tasks = []
        # Step 1: Outline
        tasks.append({
            "step": 1,
            "phase": "Planning & Scope",
            "title": f"Synthesize {doc_type} Structure & Scope",
            "description": f"Establish structural foundation and executive preamble for '{prompt[:50]}...'",
            "target_section": "Executive Summary",
            "tool": "superdocs_chat",
            "acceptance_criteria": "H1/H2 hierarchy and scope established.",
            "estimated_time": "3-5s",
        })

        # Step 2-N: Domain-specific sections
        if items:
            for idx, item in enumerate(items[:3]):
                tasks.append({
                    "step": len(tasks) + 1,
                    "phase": "Core Drafting",
                    "title": f"Draft {item.title()}",
                    "description": f"Formulate authoritative technical clauses and tables for {item}.",
                    "target_section": item.title(),
                    "tool": "superdocs_create_task",
                    "acceptance_criteria": f"Comprehensive content generated for {item}.",
                    "estimated_time": "8-12s",
                })
        else:
            tasks.append({
                "step": 2,
                "phase": "Core Drafting",
                "title": f"Draft Substantive Sections for {doc_type}",
                "description": f"Draft main technical body covering all user requirements: '{prompt[:60]}...'",
                "target_section": "Main Body",
                "tool": "superdocs_create_task",
                "acceptance_criteria": "All substantive clauses formulated.",
                "estimated_time": "12-18s",
            })

        # Audit Step
        tasks.append({
            "step": len(tasks) + 1,
            "phase": "Quality & Audit",
            "title": f"Perform Consistency Review & Verification",
            "description": f"Audit terminology consistency, clause references, and compliance tone for {doc_type}.",
            "target_section": "All Sections",
            "tool": "superdocs_add_comment",
            "acceptance_criteria": "Formatting assertions verified and zero placeholders.",
            "estimated_time": "3-4s",
        })

        # Export Step
        tasks.append({
            "step": len(tasks) + 1,
            "phase": "Export & Delivery",
            "title": "Compile & Export Deliverable",
            "description": "Export final deliverable to DOCX, PDF, and clean Markdown formats.",
            "target_section": "Final Document",
            "tool": "superdocs_export_document",
            "acceptance_criteria": "Multi-format exported artifacts ready.",
            "estimated_time": "2-3s",
        })

        return {
            "is_complex": True,
            "decision_rationale": f"Complex multi-clause {doc_type} generation requiring staged synthesis.",
            "document_type": doc_type,
            "tasks": tasks,
        }

    def get_plan(self, plan_id: str) -> Optional[DynamicTaskPlan]:
        """Retrieve an active plan by ID."""
        return self._active_plans.get(plan_id)

    def approve_plan(
        self,
        plan_id: str,
        edited_tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> ToolResponse:
        """
        Human-in-the-loop approval gate. Confirms user review and allows custom edits/reordering.
        """
        if plan_id not in self._active_plans:
            return ToolResponse(success=False, message=f"Plan '{plan_id}' not found.", error="NotFound")

        plan = self._active_plans[plan_id]

        if edited_tasks is not None:
            updated: List[TaskPlanItem] = []
            for i, t in enumerate(edited_tasks):
                step_num = t.get("step", i + 1)
                updated.append(
                    TaskPlanItem(
                        id=t.get("id", f"TASK-{step_num}"),
                        step=step_num,
                        phase=t.get("phase", "Drafting"),
                        title=t.get("title", f"Step {step_num}"),
                        description=t.get("description", ""),
                        target_section=t.get("target_section"),
                        tool=t.get("tool", "superdocs_create_task"),
                        acceptance_criteria=t.get("acceptance_criteria", "Completed successfully"),
                        estimated_time=t.get("estimated_time", "5-10s"),
                        status="approved",
                    )
                )
            plan.tasks = updated
        else:
            for t in plan.tasks:
                t.status = "approved"

        plan.approval_status = "approved"
        return ToolResponse(
            success=True,
            message=f"Plan '{plan_id}' approved with {len(plan.tasks)} tasks ready for execution.",
            data=plan.model_dump(),
        )

    def execute_approved_plan(
        self,
        plan_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> ToolResponse:
        """
        Step through all approved tasks sequentially against SuperDocs Cloud API in session context.
        """
        if plan_id not in self._active_plans:
            return ToolResponse(success=False, message=f"Plan '{plan_id}' not found.", error="NotFound")

        plan = self._active_plans[plan_id]
        if plan.approval_status != "approved":
            return ToolResponse(
                success=False,
                message=f"Cannot execute plan '{plan_id}': status is '{plan.approval_status}'. Approval required.",
                error="ApprovalRequired",
            )

        session_id = plan.session_id
        final_doc_html = None
        executed_logs: List[str] = []

        for idx, task in enumerate(plan.tasks):
            plan.current_step_index = idx + 1
            task.status = "in_progress"

            if progress_callback:
                progress_callback({
                    "plan_id": plan_id,
                    "session_id": session_id,
                    "current_step": task.step,
                    "total_steps": len(plan.tasks),
                    "task": task.model_dump(),
                    "status": "in_progress",
                })

            step_instruction = f"[{task.id} - {task.title}]: {task.description}"

            try:
                if task.tool == "superdocs_create_task" and not self.client.offline:
                    # Async task execution
                    exec_res = self.client.execute_task_and_wait(
                        session_id=session_id,
                        message=step_instruction,
                        model_tier="core",
                        max_wait=120.0,
                    )
                    if exec_res.success:
                        task.status = "completed"
                        task.execution_result = exec_res.message
                        changes = exec_res.data.get("document_changes") if exec_res.data else None
                        if changes and changes.get("updated_html"):
                            final_doc_html = changes.get("updated_html")
                    else:
                        task.status = "failed"
                        task.execution_result = exec_res.message
                else:
                    # Direct chat turn
                    chat_res = self.client.chat(
                        session_id=session_id,
                        message=step_instruction,
                        model_tier="core",
                    )
                    if chat_res.success:
                        task.status = "completed"
                        task.execution_result = chat_res.message
                        if chat_res.data:
                            changes = chat_res.data.get("document_changes")
                            if changes and changes.get("updated_html"):
                                final_doc_html = changes.get("updated_html")
                    else:
                        task.status = "failed"
                        task.execution_result = chat_res.message

            except Exception as e:
                task.status = "failed"
                task.execution_result = str(e)
                logger.error(f"Error executing step {task.id}: {e}")

            executed_logs.append(f"[{task.id}] {task.title} -> {task.status.upper()}")

            if progress_callback:
                progress_callback({
                    "plan_id": plan_id,
                    "session_id": session_id,
                    "current_step": task.step,
                    "total_steps": len(plan.tasks),
                    "task": task.model_dump(),
                    "status": task.status,
                })

        # Final export step
        export_res = self.client.export_document(session_id=session_id, export_format="markdown")

        all_completed = all(t.status == "completed" for t in plan.tasks)
        return ToolResponse(
            success=all_completed,
            message="All prompt-specific tasks executed." if all_completed else "Some tasks encountered issues.",
            data={
                "plan_id": plan_id,
                "session_id": session_id,
                "document_type": plan.document_type,
                "tasks": [t.model_dump() for t in plan.tasks],
                "final_document_html": final_doc_html,
                "export_markdown": export_res.data.get("content") if export_res.success and export_res.data else None,
                "execution_logs": executed_logs,
            },
        )
