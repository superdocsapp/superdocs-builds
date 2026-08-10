"""Run the canonical task through a native CrewAI Tool."""

from pathlib import Path

from quickstarts.common import ARGUMENTS, build_toolset
from superdocs_adapter.bindings.crewai import create_flow


def main() -> None:
    toolset = build_toolset(Path(__file__).parent / "output")
    flow = create_flow(toolset, ARGUMENTS)
    print(flow.kickoff())


if __name__ == "__main__":
    main()
