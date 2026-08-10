"""Run the canonical task through an OpenAI Agents SDK FunctionTool."""

from pathlib import Path

from quickstarts.common import ARGUMENTS, build_toolset
from superdocs_adapter.bindings.openai_agents import create_agent, invoke


def main() -> None:
    toolset = build_toolset(Path(__file__).parent / "output")
    agent = create_agent(toolset)
    print(f"{agent.name}: {len(agent.tools)} SuperDocs tool attached")
    # Direct native-tool invocation keeps this comparison deterministic and avoids
    # requiring a second model-provider key. The README also shows Runner usage.
    print(invoke(toolset, ARGUMENTS))


if __name__ == "__main__":
    main()
