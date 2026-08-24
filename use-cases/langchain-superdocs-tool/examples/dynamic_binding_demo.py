import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Ensure package is importable when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.dynamic import load_dynamic_superdocs_tools

console = Console()


def run_dynamic_demo():
    console.print(
        Panel.fit(
            "[bold cyan]SuperDocs Dynamic Tool Binding (MCP / REST Schema Discovery)[/bold cyan]\n"
            "[dim]Dynamically discovering and synthesizing LangChain StructuredTools from live server manifests[/dim]",
            border_style="cyan",
        )
    )

    client = SuperDocsClient(offline=True)

    # 1. Fetch live declarations
    declarations = client.get_tool_declarations()
    console.print(f"[bold yellow]Discovered {len(declarations)} tool declarations from SuperDocs manifest.[/bold yellow]\n")

    # 2. Dynamically compile into LangChain BaseTools
    tools = load_dynamic_superdocs_tools(client)

    table = Table(title="Dynamically Generated LangChain Tools", show_header=True, header_style="bold green")
    table.add_column("Tool Name", style="bold cyan")
    table.add_column("Description", style="white")
    table.add_column("Args Schema Class", style="yellow")

    for tool in tools:
        table.add_row(
            tool.name,
            tool.description[:65] + ("..." if len(tool.description) > 65 else ""),
            tool.args_schema.__name__ if tool.args_schema else "None",
        )

    console.print(table)
    console.print()

    # 3. Test dynamic invocation
    create_tool = next(t for t in tools if t.name == "superdocs_create_document")
    console.print("[bold yellow]Testing Dynamic Tool Invocation: 'superdocs_create_document'...[/bold yellow]")
    res = create_tool.invoke({
        "title": "Dynamic Tool Generated Spec",
        "content": "## Section 1\nContent populated dynamically via generated LangChain tool.",
    })
    console.print(Panel(res, title="Tool Execution Result", border_style="green"))


if __name__ == "__main__":
    run_dynamic_demo()
