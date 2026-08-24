"""
LangGraph Multi-Step StateGraph Agent with Dynamic Prompt-Specific Planning and HITL Approval Gate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.planner import DynamicTaskPlan, DynamicTaskPlanner, TaskPlanItem

logger = logging.getLogger(__name__)


class DynamicAgentState(TypedDict):
    """Execution state for the prompt-specific dynamic agent graph."""
    user_goal: str
    session_id: str
    document_html: Optional[str]
    plan_id: Optional[str]
    plan: Optional[Dict[str, Any]]
    approval_status: str  # "pending_review", "approved", "rejected"
    is_complex: bool
    current_step_index: int
    tasks: List[Dict[str, Any]]
    completed_steps: List[str]
    trace_logs: List[str]
    final_output: Optional[str]
    status: str


def create_dynamic_planner_agent(
    client: Optional[SuperDocsClient] = None,
    planner: Optional[DynamicTaskPlanner] = None,
) -> Any:
    """
    Construct a LangGraph StateGraph agent that:
    1. Analyzes the prompt and generates prompt-specific tasks via SuperDocs AI.
    2. Pauses at Human-In-The-Loop (HITL) gate for review/approval.
    3. Executes approved tasks sequentially in persistent session context.
    4. Compiles and exports the deliverable.
    """
    client = client or SuperDocsClient()
    planner = planner or DynamicTaskPlanner(client=client)

    builder = StateGraph(DynamicAgentState)

    # -------------------------------------------------------------------------
    # Node 1: Dynamic Task Planning Node
    # -------------------------------------------------------------------------
    def plan_node(state: DynamicAgentState) -> Dict[str, Any]:
        goal = state.get("user_goal", "")
        sess_id = state.get("session_id") or "dynamic-agent-session"
        doc_html = state.get("document_html")
        logs = list(state.get("trace_logs", []))

        logs.append(f"[Planner] Analyzing goal: '{goal[:60]}...'")
        plan: DynamicTaskPlan = planner.evaluate_and_plan(
            prompt=goal,
            session_id=sess_id,
            document_html=doc_html,
        )

        logs.append(f"[Planner] Generated {len(plan.tasks)} prompt-specific tasks for '{plan.document_type}' (Complex: {plan.is_complex}).")
        for t in plan.tasks:
            logs.append(f"  ↳ [{t.id}] {t.title} (Tool: {t.tool})")

        return {
            "plan_id": plan.plan_id,
            "session_id": sess_id,
            "plan": plan.model_dump(),
            "is_complex": plan.is_complex,
            "approval_status": "pending_review",
            "tasks": [t.model_dump() for t in plan.tasks],
            "trace_logs": logs,
            "status": "awaiting_hitl_approval",
        }

    # -------------------------------------------------------------------------
    # Node 2: HITL Approval Gate Node
    # -------------------------------------------------------------------------
    def hitl_gate_node(state: DynamicAgentState) -> Dict[str, Any]:
        logs = list(state.get("trace_logs", []))
        status = state.get("approval_status", "pending_review")

        if status == "approved":
            logs.append("[HITL Gate] Plan approved by user. Proceeding to task execution.")
            return {"status": "executing_tasks", "trace_logs": logs}
        elif status == "rejected":
            logs.append("[HITL Gate] Plan rejected by user. Aborting execution.")
            return {"status": "rejected", "trace_logs": logs}
        else:
            logs.append("[HITL Gate] Awaiting user review and approval of generated task plan.")
            return {"status": "awaiting_hitl_approval", "trace_logs": logs}

    # -------------------------------------------------------------------------
    # Node 3: Sequential Task Executor Node
    # -------------------------------------------------------------------------
    def execute_tasks_node(state: DynamicAgentState) -> Dict[str, Any]:
        plan_id = state.get("plan_id")
        logs = list(state.get("trace_logs", []))
        tasks = state.get("tasks", [])
        session_id = state.get("session_id", "dynamic-agent-session")

        logs.append(f"[Executor] Beginning sequential execution of {len(tasks)} approved tasks...")

        # Execute approved plan
        exec_res = planner.execute_approved_plan(plan_id=plan_id or "")

        final_html = ""
        export_md = ""
        if exec_res.success and exec_res.data:
            data = exec_res.data
            tasks = data.get("tasks", tasks)
            final_html = data.get("final_document_html", "")
            export_md = data.get("export_markdown", "")
            for entry in data.get("execution_logs", []):
                logs.append(f"[Executor] {entry}")
            logs.append("[Executor] All prompt-specific tasks executed successfully.")
        else:
            logs.append(f"[Executor] Execution completed with status: {exec_res.message}")

        return {
            "tasks": tasks,
            "document_html": final_html,
            "final_output": export_md or final_html,
            "trace_logs": logs,
            "status": "completed" if exec_res.success else "failed",
        }

    # -------------------------------------------------------------------------
    # Routing Decisions
    # -------------------------------------------------------------------------
    def route_after_hitl(state: DynamicAgentState) -> str:
        status = state.get("approval_status", "pending_review")
        if status == "approved":
            return "execute_tasks"
        return "end"

    builder.add_node("planner", plan_node)
    builder.add_node("hitl_gate", hitl_gate_node)
    builder.add_node("execute_tasks", execute_tasks_node)

    builder.set_entry_point("planner")
    builder.add_edge("planner", "hitl_gate")
    builder.add_conditional_edges(
        "hitl_gate",
        route_after_hitl,
        {
            "execute_tasks": "execute_tasks",
            "end": END,
        },
    )
    builder.add_edge("execute_tasks", END)

    return builder.compile()
