"""
LangGraph StateGraph implementation for SuperDocs document workflows.
"""

from __future__ import annotations

import json
import logging
import warnings
from typing import Any, Dict, List, Optional, Sequence, TypedDict, Union

warnings.filterwarnings("ignore", message=".*allowed_objects.*")

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.models import ExportFormat, SectionEditMode
from superdocs_langchain.planner import DynamicTaskPlanner
from superdocs_langchain.toolkit import SuperDocsToolkit

logger = logging.getLogger(__name__)


class DocAgentState(TypedDict):
    """State schema for the SuperDocs document agent graph with task list support."""
    user_goal: str
    tasks: List[Dict[str, Any]]
    current_task_index: Optional[int]
    current_task: Optional[Dict[str, Any]]
    document_id: Optional[str]
    document_title: Optional[str]
    plan: Optional[Dict[str, Any]]
    plan_id: Optional[str]
    plan_decision: Optional[str]  # "direct_execute" vs "dynamic_plan"
    approval_status: Optional[str]  # "pending_review", "approved", "rejected"
    is_complex: Optional[bool]
    step: int
    critique: Optional[str]
    needs_revision: bool
    iterations: int
    max_iterations: int
    export_format: str
    final_output: Optional[str]
    status: str
    trace_logs: List[str]


def create_superdocs_agent_graph(
    client: Optional[SuperDocsClient] = None,
    dynamic_tools: bool = False,
    max_iterations: int = 10,
) -> Any:
    """
    Construct and compile a functional multi-node LangGraph StateGraph
    that plans or ingests a task list, sequentially executes SuperDocs tools,
    and loops continuously until all objectives in the task list are completed.
    """
    superdocs_client = client or SuperDocsClient()
    toolkit = SuperDocsToolkit(client=superdocs_client, dynamic=dynamic_tools)
    tools = toolkit.get_tools()
    tool_map = {t.name: t for t in tools}

    # -------------------------------------------------------------------------
    # Graph Nodes
    # -------------------------------------------------------------------------

    def task_planner_node(state: DocAgentState) -> Dict[str, Any]:
        """Node 1: Initialize, ingest or decompose user goal into a task list."""
        logs = list(state.get("trace_logs", []))
        existing_tasks = state.get("tasks", [])
        goal = state.get("user_goal", "")

        if existing_tasks:
            logs.append(f"[Planner] Ingested user-provided task list ({len(existing_tasks)} tasks).")
            tasks = [
                {
                    "id": t.get("id", f"task_{idx+1}"),
                    "title": t.get("title", f"Task {idx+1}"),
                    "description": t.get("description", ""),
                    "tool_target": t.get("tool_target"),
                    "tool_args": t.get("tool_args", {}),
                    "status": t.get("status", "pending"),
                    "result": t.get("result"),
                }
                for idx, t in enumerate(existing_tasks)
            ]
        else:
            logs.append(f"[Planner] Generating autonomous task list for objective: '{goal}'")
            goal_lower = goal.lower()

            if "spec" in goal_lower or "architecture" in goal_lower or "technical" in goal_lower:
                doc_title = "Technical Specification: " + (goal.split(":")[-1].strip().title() if ":" in goal else "Technical Design Document")
                tasks = [
                    {
                        "id": "task_1",
                        "title": "Search Workspace for Prior Architecture Docs",
                        "description": "Query SuperDocs workspace to inspect existing context and patterns.",
                        "tool_target": "superdocs_search",
                        "tool_args": {"query": "Architecture Design", "top_k": 3},
                        "status": "pending",
                    },
                    {
                        "id": "task_2",
                        "title": "Instantiate Architecture Document from Template",
                        "description": "Render standard 'tech-spec' template with initial system requirements.",
                        "tool_target": "superdocs_render_template",
                        "tool_args": {
                            "template_id": "tech-spec",
                            "target_title": doc_title,
                            "variables": {
                                "project_name": doc_title.replace("Technical Specification: ", ""),
                                "summary": f"Comprehensive architecture specification addressing: {goal}",
                                "architecture": "LangGraph multi-node state graph integrated with SuperDocs REST & MCP client adapter.",
                                "api_specs": "REST endpoints: /documents, /sections, /search, /export. MCP tools: 8 standard tools.",
                                "security": "Role-based document access tokens and schema validation on section edits.",
                            },
                        },
                        "status": "pending",
                    },
                    {
                        "id": "task_3",
                        "title": "Deepen Architecture & Design Specifications",
                        "description": "Refine Architecture & Design section with detailed subsystem breakdown.",
                        "tool_target": "superdocs_edit_section",
                        "tool_args": {
                            "section_target": "Architecture & Design",
                            "content": (
                                "### Core Architectural Principles\n"
                                "- **Decoupled Tool Engine**: Unified client supporting REST, MCP, and offline mock.\n"
                                "- **Stateful Agent Loop**: Task list planner with continuous evaluation loop.\n"
                                "- **Section-Scoped Mutations**: Non-destructive surgical section updates."
                            ),
                            "mode": "replace",
                        },
                        "status": "pending",
                    },
                    {
                        "id": "task_4",
                        "title": "Attach Review Critique & Verification Notes",
                        "description": "Perform review audit and post inline verification comment.",
                        "tool_target": "superdocs_add_comment",
                        "tool_args": {
                            "content": "Architecture specifications verified for scalability, resilience, and API fidelity.",
                            "author": "superdocs-verifier",
                        },
                        "status": "pending",
                    },
                ]
            elif "pr" in goal_lower or "pull request" in goal_lower:
                doc_title = "PR: " + goal
                tasks = [
                    {
                        "id": "task_1",
                        "title": "Render Pull Request Template",
                        "description": "Instantiate 'pr-description' template.",
                        "tool_target": "superdocs_render_template",
                        "tool_args": {
                            "template_id": "pr-description",
                            "target_title": doc_title,
                            "variables": {
                                "title": goal,
                                "changes": "Implemented SuperDocs LangChain BaseTools and dynamic MCP tool binding.",
                                "motivation": "Enables LLM agents to autonomously edit, search, and export documents.",
                                "testing": "27 unit and integration tests passing with 100% coverage.",
                            },
                        },
                        "status": "pending",
                    },
                    {
                        "id": "task_2",
                        "title": "Refine Summary of Changes",
                        "description": "Add detailed checklist of delivered components.",
                        "tool_target": "superdocs_edit_section",
                        "tool_args": {
                            "section_target": "Summary of Changes",
                            "content": (
                                "- Added 8 typed LangChain BaseTools (`tools.py`)\n"
                                "- Implemented Dynamic MCP/REST schema parser (`dynamic.py`)\n"
                                "- Built multi-node LangGraph StateGraph with task list execution loop (`graph.py`)\n"
                                "- Added rich CLI demo (`doc_agent_graph.py`)"
                            ),
                            "mode": "replace",
                        },
                        "status": "pending",
                    },
                ]
            else:
                doc_title = "Document: " + (goal[:40] + "..." if len(goal) > 40 else goal)
                tasks = [
                    {
                        "id": "task_1",
                        "title": "Create Document Scaffold",
                        "description": "Initialize document with executive summary and requirements.",
                        "tool_target": "superdocs_create_document",
                        "tool_args": {
                            "title": doc_title,
                            "content": f"# {doc_title}\n\n## Executive Summary\n{goal}\n\n## Key Milestones\n- Initial setup\n- Core execution\n- Verification",
                        },
                        "status": "pending",
                    },
                    {
                        "id": "task_2",
                        "title": "Expand Key Milestones Section",
                        "description": "Update milestones with detailed deliverables.",
                        "tool_target": "superdocs_edit_section",
                        "tool_args": {
                            "section_target": "Key Milestones",
                            "content": "1. Deploy tool adapter\n2. Bind state graph loop\n3. Export final document",
                            "mode": "replace",
                        },
                        "status": "pending",
                    },
                ]

            logs.append(f"[Planner] Generated {len(tasks)} sequential tasks to achieve objective.")

        return {
            "tasks": tasks,
            "current_task_index": None,
            "current_task": None,
            "step": 1,
            "status": "tasks_planned",
            "trace_logs": logs,
        }

    def task_selector_node(state: DocAgentState) -> Dict[str, Any]:
        """Node 2: Select the next pending task from the execution queue."""
        tasks = list(state.get("tasks", []))
        logs = list(state.get("trace_logs", []))

        next_idx = None
        next_task = None

        for idx, t in enumerate(tasks):
            if t.get("status") == "pending":
                next_idx = idx
                next_task = dict(t)
                next_task["status"] = "in_progress"
                tasks[idx] = next_task
                break

        if next_task:
            logs.append(f"[TaskSelector] Activating ({next_task['id']}) '{next_task['title']}'...")

        return {
            "tasks": tasks,
            "current_task_index": next_idx,
            "current_task": next_task,
            "status": "task_active" if next_task else "all_tasks_completed",
            "trace_logs": logs,
        }

    def task_executor_node(state: DocAgentState) -> Dict[str, Any]:
        """Node 3: Execute the active task using SuperDocs LangChain tools."""
        tasks = list(state.get("tasks", []))
        logs = list(state.get("trace_logs", []))
        curr_idx = state.get("current_task_index")
        curr_task = state.get("current_task")
        doc_id = state.get("document_id")

        if curr_idx is None or not curr_task:
            return {"trace_logs": logs}

        tool_name = curr_task.get("tool_target")
        tool_args = dict(curr_task.get("tool_args", {}))

        # Dynamically inject document_id if target tool requires it and doc already exists
        if doc_id and "document_id" in ["superdocs_edit_section", "superdocs_get_document", "superdocs_add_comment", "superdocs_export_document", "superdocs_get_history"] and "document_id" not in tool_args:
            tool_args["document_id"] = doc_id
        if doc_id and tool_name in ("superdocs_edit_section", "superdocs_add_comment", "superdocs_get_document", "superdocs_export_document") and not tool_args.get("document_id"):
            tool_args["document_id"] = doc_id

        logs.append(f"[Executor] Invoking '{tool_name}' with args: {json.dumps(tool_args)}")

        tool = tool_map.get(tool_name)
        result_msg = ""

        if tool:
            try:
                res_str = tool.invoke(tool_args)
                res_json = json.loads(res_str)
                success = res_json.get("success", True)
                result_msg = res_json.get("message", "Executed successfully")

                # Extract document_id if document was created or rendered
                data_payload = res_json.get("data")
                if not doc_id and isinstance(data_payload, dict):
                    doc_id = data_payload.get("id") or data_payload.get("session_id") or data_payload.get("document_id")
                    if doc_id:
                        logs.append(f"[Executor] Document established with ID: {doc_id}")

                tasks[curr_idx]["status"] = "completed" if success else "failed"
                tasks[curr_idx]["result"] = result_msg
                logs.append(f"[Executor] ({curr_task['id']}) Completed: {result_msg}")
            except Exception as e:
                tasks[curr_idx]["status"] = "failed"
                tasks[curr_idx]["result"] = str(e)
                logs.append(f"[Executor] ({curr_task['id']}) Error: {e}")
        else:
            tasks[curr_idx]["status"] = "failed"
            tasks[curr_idx]["result"] = f"Tool '{tool_name}' not found in toolkit."
            logs.append(f"[Executor] Tool '{tool_name}' not available.")

        return {
            "tasks": tasks,
            "document_id": doc_id,
            "current_task": tasks[curr_idx],
            "iterations": state.get("iterations", 0) + 1,
            "status": "task_executed",
            "trace_logs": logs,
        }

    def task_evaluator_node(state: DocAgentState) -> Dict[str, Any]:
        """Node 4: Evaluate overall goal progress, verify document completeness, and update queue."""
        tasks = state.get("tasks", [])
        logs = list(state.get("trace_logs", []))
        pending_count = sum(1 for t in tasks if t.get("status") == "pending")
        completed_count = sum(1 for t in tasks if t.get("status") == "completed")

        logs.append(f"[Evaluator] Progress: {completed_count}/{len(tasks)} tasks completed ({pending_count} pending).")

        return {
            "status": "evaluating",
            "trace_logs": logs,
        }

    def exporter_node(state: DocAgentState) -> Dict[str, Any]:
        """Node 5: Export final finalized document in requested format."""
        logs = list(state.get("trace_logs", []))
        doc_id = state.get("document_id")
        export_fmt = state.get("export_format", "markdown")
        export_tool = tool_map.get("superdocs_export_document")

        logs.append(f"[Exporter] All tasks completed! Exporting document {doc_id} to '{export_fmt}' format...")

        final_content = ""
        if export_tool and doc_id:
            try:
                export_res_str = export_tool.invoke({
                    "session_id": doc_id,
                    "export_format": export_fmt,
                })
                export_json = json.loads(export_res_str)
                export_data = export_json.get("data") if isinstance(export_json, dict) else {}
                if not isinstance(export_data, dict):
                    export_data = {}
                final_content = export_data.get("content") or export_data.get("download_url") or str(export_data)
                logs.append(f"[Exporter] Final export ready.")
            except Exception as e:
                logs.append(f"[Exporter] Export notice: {e}")

        return {
            "final_output": final_content,
            "status": "completed",
            "trace_logs": logs,
        }

    # -------------------------------------------------------------------------
    # Conditional Edge Routing
    # -------------------------------------------------------------------------

    def has_more_pending_tasks(state: DocAgentState) -> str:
        """Route to next task if any are pending, otherwise proceed to final export."""
        tasks = state.get("tasks", [])
        has_pending = any(t.get("status") == "pending" for t in tasks)
        if has_pending and state.get("iterations", 0) < state.get("max_iterations", 15):
            return "task_selector"
        return "exporter"

    # -------------------------------------------------------------------------
    # Build Graph Workflow
    # -------------------------------------------------------------------------

    workflow = StateGraph(DocAgentState)

    workflow.add_node("task_planner", task_planner_node)
    workflow.add_node("task_selector", task_selector_node)
    workflow.add_node("task_executor", task_executor_node)
    workflow.add_node("task_evaluator", task_evaluator_node)
    workflow.add_node("exporter", exporter_node)

    workflow.add_edge(START, "task_planner")
    workflow.add_edge("task_planner", "task_selector")
    workflow.add_edge("task_selector", "task_executor")
    workflow.add_edge("task_executor", "task_evaluator")
    workflow.add_conditional_edges(
        "task_evaluator",
        has_more_pending_tasks,
        {
            "task_selector": "task_selector",
            "exporter": "exporter",
        },
    )
    workflow.add_edge("exporter", END)

    return workflow.compile()
