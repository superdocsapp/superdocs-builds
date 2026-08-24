import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Ensure package is importable when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.graph import create_superdocs_agent_graph

console = Console()


from typing import Any, Dict, List, Optional
import json

def run_demo(
    user_prompt: str,
    export_format: str = "markdown",
    dynamic_tools: bool = False,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    offline: Optional[bool] = None,
    custom_tasks: Optional[List[Dict[str, Any]]] = None,
):
    client = SuperDocsClient(base_url=base_url, api_key=api_key, offline=offline)
    mode_desc = "Offline Mock Engine" if client.offline else f"Live REST API ({client.base_url})"

    console.print(
        Panel.fit(
            "[bold cyan]SuperDocs LangGraph Autonomous Task Agent[/bold cyan]\n"
            f"[dim]Objective: {user_prompt}[/dim]\n"
            f"[dim]Mode: {mode_desc} | Dynamic Tools: {dynamic_tools} | Format: {export_format}[/dim]",
            border_style="cyan",
        )
    )

    graph = create_superdocs_agent_graph(
        client=client,
        dynamic_tools=dynamic_tools,
        max_iterations=15,
    )

    initial_state = {
        "user_goal": user_prompt,
        "tasks": custom_tasks or [],
        "current_task_index": None,
        "current_task": None,
        "document_id": None,
        "document_title": None,
        "plan": None,
        "step": 0,
        "critique": None,
        "needs_revision": False,
        "iterations": 0,
        "max_iterations": 15,
        "export_format": export_format,
        "final_output": None,
        "status": "initialized",
        "trace_logs": [],
    }

    console.print("[bold yellow]▶ Launching Task-Driven Agent Execution Loop...[/bold yellow]\n")

    start_time = time.time()
    final_state = graph.invoke(initial_state)
    elapsed = round(time.time() - start_time, 3)

    # Render Task Execution Status Table
    tasks_table = Table(title="Autonomous Task Execution Queue", show_header=True, header_style="bold cyan")
    tasks_table.add_column("Task ID", style="bold yellow", width=10)
    tasks_table.add_column("Task Title", style="white")
    tasks_table.add_column("Target Tool", style="magenta")
    tasks_table.add_column("Status", justify="center")
    tasks_table.add_column("Result / Output", style="dim")

    for task in final_state.get("tasks", []):
        st = task.get("status", "pending")
        if st == "completed":
            badge = "[bold green]✔ COMPLETED[/bold green]"
        elif st == "failed":
            badge = "[bold red]✖ FAILED[/bold red]"
        else:
            badge = f"[dim]{st.upper()}[/dim]"

        tasks_table.add_row(
            task.get("id", ""),
            task.get("title", ""),
            task.get("tool_target", "auto"),
            badge,
            (task.get("result") or "")[:55] + ("..." if len(task.get("result") or "") > 55 else ""),
        )

    console.print(tasks_table)
    console.print()

    # Render Step-by-Step Execution Trace Table
    trace_table = Table(title="LangGraph Agent Execution Trace", show_header=True, header_style="bold magenta")
    trace_table.add_column("#", style="dim", width=4)
    trace_table.add_column("Trace Event", style="green")

    for idx, log in enumerate(final_state.get("trace_logs", []), 1):
        trace_table.add_row(str(idx), log)

    console.print(trace_table)
    console.print(f"\n[bold green]✔ All Objectives in Task List Complete in {elapsed}s with status: '{final_state['status']}'[/bold green]")
    console.print(f"[bold]Generated Document ID:[/bold] {final_state.get('document_id')}")
    console.print(f"[bold]Total Tasks Executed:[/bold] {len(final_state.get('tasks', []))}\n")

    # Render Document Output Preview
    final_output = final_state.get("final_output", "")
    console.print(
        Panel(
            Syntax(
                final_output,
                "markdown" if export_format in ("markdown", "text") else export_format,
                theme="monokai",
                line_numbers=True,
            ),
            title=f"[bold green]Final Exported Document ({export_format.upper()})[/bold green]",
            border_style="green",
        )
    )

    return final_state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LangGraph SuperDocs document workflow demo.")
    parser.add_argument(
        "--prompt",
        type=str,
        default="Create a technical architecture specification for a real-time event streaming pipeline",
        help="Natural language document creation or editing prompt.",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["markdown", "html", "text", "json"],
        default="markdown",
        help="Desired export format.",
    )
    parser.add_argument(
        "--dynamic",
        action="store_true",
        help="Enable dynamic tool binding from live schema definitions.",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="SuperDocs live REST API base URL (e.g. http://localhost:8000 or https://api.superdocs.io/v1).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="SuperDocs API Bearer token.",
    )
    parser.add_argument(
        "--tasks-json",
        type=str,
        default=None,
        help="Optional JSON string of custom tasks list to execute.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run offline using embedded zero-dependency mock engine.",
    )

    args = parser.parse_args()
    tasks_input = json.loads(args.tasks_json) if args.tasks_json else None

    run_demo(
        args.prompt,
        export_format=args.format,
        dynamic_tools=args.dynamic,
        base_url=args.base_url,
        api_key=args.api_key,
        offline=args.offline if args.offline else None,
        custom_tasks=tasks_input,
    )
