import os
from pathlib import Path

import pytest

from superdocs_adapter import SuperDocsAdapter, SuperDocsClient, SuperDocsToolset
from superdocs_adapter.bindings.crewai import invoke as invoke_crewai
from superdocs_adapter.bindings.langgraph import invoke as invoke_langgraph
from superdocs_adapter.bindings.openai_agents import invoke as invoke_openai_agents

ROOT = Path(__file__).resolve().parents[1]


def normalize_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").strip().splitlines())


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SUPERDOCS") != "1",
    reason="Set RUN_LIVE_SUPERDOCS=1 explicitly; this test spends three operations.",
)
def test_three_live_framework_runs_match_expected_output(tmp_path: Path) -> None:
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        pytest.fail("SUPERDOCS_API_KEY is required when RUN_LIVE_SUPERDOCS=1")

    source = ROOT / "examples" / "input" / "sample-policy.txt"
    expected = normalize_text(
        (ROOT / "examples" / "expected" / "expected-output.txt").read_text(encoding="utf-8")
    )
    arguments = {
        "file_path": str(source),
        "instruction": (
            "Replace the exact sentence 'Support is available on weekdays.' with "
            "'Support is available Monday through Friday, 09:00-17:00 UTC.' "
            "Do not change anything else."
        ),
        "output_format": "txt",
    }
    outputs: list[str] = []

    for name, invoke in (
        ("langgraph", invoke_langgraph),
        ("crewai", invoke_crewai),
        ("openai_agents", invoke_openai_agents),
    ):
        with SuperDocsClient(api_key) as client:
            toolset = SuperDocsToolset(
                SuperDocsAdapter(client, timeout=600),
                output_directory=tmp_path / name,
            )
            invoke(toolset, arguments)
        output = (tmp_path / name / "superdocs-output.txt").read_text(encoding="utf-8")
        outputs.append(normalize_text(output))

    assert outputs == [expected, expected, expected]
