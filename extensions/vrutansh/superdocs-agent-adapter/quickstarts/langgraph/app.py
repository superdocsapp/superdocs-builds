"""Run the canonical task through a LangGraph-compatible StructuredTool."""

from pathlib import Path

from quickstarts.common import ARGUMENTS, build_toolset
from superdocs_adapter.bindings.langgraph import create_workflow


def main() -> None:
    toolset = build_toolset(Path(__file__).parent / "output")
    workflow = create_workflow(toolset)
    state = workflow.invoke({"arguments": ARGUMENTS})
    print(state["result"])


if __name__ == "__main__":
    main()
