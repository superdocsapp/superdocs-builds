"""
SuperDocs Persistent Sessions Demonstration.

Demonstrates:
1. Multi-turn conversation and document evolution in a persistent session.
2. Re-using session_id to maintain conversational context without resending document HTML.
3. Loading session history with turn indices and checkpoints.
4. Reverting a session to a previous message turn (rewinding both chat and document state).
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Ensure package is importable when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.toolkit import SuperDocsToolkit

console = Console()


def run_sessions_demo():
    console.print(
        Panel.fit(
            "[bold cyan]SuperDocs Persistent Sessions Lifecycle Demo[/bold cyan]\n"
            "[dim]Reference: https://docs.superdocs.app/concepts/sessions[/dim]",
            border_style="cyan",
        )
    )

    client = SuperDocsClient(offline=True)
    toolkit = SuperDocsToolkit(client=client)
    tools = {t.name: t for t in toolkit.get_tools()}

    session_id = "project-proposal-v1"

    # Step 1: First Request — Starts a new session with initial HTML
    console.print(f"[bold yellow]1. Starting new session '{session_id}' with initial document...[/bold yellow]")
    chat_tool = tools["superdocs_chat"]
    res1 = chat_tool.invoke({
        "message": "Add an introduction section",
        "session_id": session_id,
        "document_html": "<h1>Project Proposal</h1>",
    })
    console.print(Panel(res1, title="Turn 1 Response", border_style="blue"))

    # Step 2: Second Request — Continues the same session without re-sending document_html
    console.print(f"\n[bold yellow]2. Continuing session '{session_id}' (adding Budget section)...[/bold yellow]")
    res2 = chat_tool.invoke({
        "message": "Now add a budget section",
        "session_id": session_id,
    })
    console.print(Panel(res2, title="Turn 2 Response", border_style="blue"))

    # Step 3: Inspect Session History
    console.print(f"\n[bold yellow]3. Loading full session history for '{session_id}'...[/bold yellow]")
    hist_tool = tools["superdocs_get_session_history"]
    history_res = hist_tool.invoke({"session_id": session_id})
    console.print(Panel(history_res, title="Session History & Document State", border_style="magenta"))

    # Step 4: Revert Session to Previous Message (Rewind to turn_index 2)
    console.print(f"\n[bold yellow]4. Rewinding session '{session_id}' to turn_index 2 (undo budget turn)...[/bold yellow]")
    revert_tool = tools["superdocs_revert_session"]
    revert_res = revert_tool.invoke({
        "session_id": session_id,
        "turn_index": 2,
    })
    console.print(Panel(revert_res, title="Session Revert Response (Restored State)", border_style="green"))


if __name__ == "__main__":
    run_sessions_demo()
