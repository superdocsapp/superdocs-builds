"""Run the canonical task through a native CrewAI Tool."""

from pathlib import Path

from quickstarts.common import ARGUMENTS, build_toolset
from superdocs_adapter.bindings.crewai import invoke


def main() -> None:
    toolset = build_toolset(Path(__file__).parent / "output")
    print(invoke(toolset, ARGUMENTS))


if __name__ == "__main__":
    main()
