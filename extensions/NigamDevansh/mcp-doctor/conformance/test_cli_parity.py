"""The release gate: both native CLIs must give the same answer.

The unit suites prove that each implementation meets the shared fixture
contract.  This suite instead invokes their real command-line entry points
over the same temporary files and compares the public ``--json`` wire format.
It is deliberately black-box: changing a private helper in one language must
not create an unobserved behavioural fork.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "node"
PYTHON = ROOT / "python"
CLIENTS = ("claude-code", "vscode", "codex", "antigravity")


def fixture_cases() -> Iterator[tuple[str, dict]]:
    for client_id in CLIENTS:
        data = json.loads((ROOT / "shared" / "fixtures" / f"{client_id}.cases.json").read_text())
        yield from ((client_id, case) for case in data["cases"])


CASES = list(fixture_cases())


@pytest.fixture(scope="session", autouse=True)
def build_node_cli() -> None:
    """Conformance must test the generated `npx` executable, not TS sources."""
    subprocess.run(["npm", "run", "build"], cwd=NODE, check=True, capture_output=True, text=True)


def case_environment(root: Path, case: dict) -> dict[str, str]:
    """A tiny hermetic environment; inherited keys must never affect a fixture."""
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(root),
        "USERPROFILE": str(root),
        "CODEX_HOME": str(root / ".codex"),
        "XDG_CONFIG_HOME": str(root / ".config"),
        "MCP_DOCTOR_DETERMINISTIC": "1",
    }
    for name, value in case.get("env", {}).items():
        if value is not None:
            env[name] = value
    return env


def configured_file(root: Path, client_id: str, case: dict) -> Path:
    """Select the one config a fixture asks this client to diagnose."""
    filenames = {
        location["path"].split("/")[-1]
        for location in json.loads((ROOT / "shared" / "clients" / f"{client_id}.json").read_text())["locations"]
    }
    matches = [root / relative for relative in case["raw_files"] if Path(relative).name in filenames]
    assert len(matches) == 1, f"{client_id}/{case['name']}: no unique configuration file"
    return matches[0]


def invoke(command: list[str], *, env: dict[str, str], cwd: Path) -> tuple[int, dict]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    assert result.stderr == "", result.stderr
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - makes a CLI failure readable
        raise AssertionError(f"CLI did not emit JSON:\nstdout={result.stdout}\nstderr={result.stderr}") from exc


def comparable(report: dict) -> dict:
    """Implementation identity is intentionally different; behaviour is not."""
    report = json.loads(json.dumps(report))
    report["tool"].pop("implementation")
    return report


@pytest.fixture(scope="session")
def promoted_contract(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("promoted") / "shared"
    shutil.copytree(ROOT / "shared", root)
    for client_id in CLIENTS:
        path = root / "clients" / f"{client_id}.json"
        entry = json.loads(path.read_text())
        entry["evidence"]["schema"] = {"status": "captured", "date": "2026-08-23", "how": "conformance"}
        entry["evidence"]["repairs"] = {"status": "captured", "date": "2026-08-23", "how": "conformance"}
        entry["evidence"]["paths"] = {
            os_name: {"status": "captured", "date": "2026-08-23", "how": "conformance"}
            for os_name in ("darwin", "linux", "win32")
        }
        entry["write_capable"] = {"darwin": True, "linux": True, "win32": True}
        entry["repairs"]["allowed"] = entry["repairs"].get("planned", [])
        path.write_text(json.dumps(entry, indent=2))
    return root


@pytest.mark.parametrize(("client_id", "case"), CASES, ids=lambda value: value if isinstance(value, str) else value["name"])
def test_repair_engines_write_identical_bytes(
    tmp_path: Path, client_id: str, case: dict, promoted_contract: Path
) -> None:
    results = {}
    for label in ("node", "python"):
        root = tmp_path / label
        root.mkdir()
        for relative, contents in case["raw_files"].items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents.encode("utf-8"))

        env = case_environment(root, case)
        env["MCP_DOCTOR_SHARED"] = str(promoted_contract)
        env.setdefault("SUPERDOCS_API_KEY", "sk_fixture_conformance_0000")
        args = ["--json", "--fix", "--client", client_id, "--config", str(configured_file(root, client_id, case))]

        if label == "node":
            code, report = invoke(["node", str(NODE / "dist" / "cli.js"), *args], env=env, cwd=root)
        else:
            code, report = invoke(
                [sys.executable, "-m", "mcp_doctor.cli", *args],
                env={**env, "PYTHONPATH": str(PYTHON / "src")},
                cwd=root,
            )

        results[label] = (
            code,
            comparable(report),
            {relative: (root / relative).read_bytes() for relative in case["raw_files"]},
            # Names carry a timestamp, so only the count is comparable.
            len(list(root.rglob("*.mcp-doctor-*.bak"))),
        )

    node, python = results["node"], results["python"]
    label = f"{client_id}/{case['name']}"
    assert python[2] == node[2], f"{label}: repaired bytes differ"
    assert python[0] == node[0], f"{label}: exit codes differ"
    assert python[3] == node[3], f"{label}: backup counts differ"
    assert python[1] == node[1], f"{label}: --json differs"


@pytest.mark.parametrize(("client_id", "case"), CASES, ids=lambda value: value if isinstance(value, str) else value["name"])
@pytest.mark.parametrize("fix", [False, True], ids=["scan", "fix"])
def test_native_clis_have_identical_json_and_safe_gated_fix(
    tmp_path: Path, client_id: str, case: dict, fix: bool
) -> None:
    for relative, contents in case["raw_files"].items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents.encode("utf-8"))
    config = configured_file(tmp_path, client_id, case)
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    env = case_environment(tmp_path, case)
    args = ["--json", "--client", client_id, "--config", str(config)]
    if fix:
        args.append("--fix")

    # Both commands must run from the same project root.  Otherwise a
    # deterministic relative path could compare equal merely because `node/`
    # and `python/` happen to be siblings, rather than because each CLI
    # implements the documented scan-root semantics.
    node_code, node_report = invoke(
        ["node", str(NODE / "dist" / "cli.js"), *args], env=env, cwd=tmp_path
    )
    python_env = {**env, "PYTHONPATH": str(PYTHON / "src")}
    python_code, python_report = invoke(
        [sys.executable, "-m", "mcp_doctor.cli", *args], env=python_env, cwd=tmp_path
    )

    assert python_code == node_code, f"{client_id}/{case['name']} ({'fix' if fix else 'scan'})"
    assert comparable(python_report) == comparable(node_report)
    if fix:
        # No client has earned write capability yet.  Prove the public --fix
        # path cannot accidentally create a backup or alter a fixture.
        after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
        assert after == before
        assert not list(tmp_path.rglob("*.mcp-doctor-*.bak"))
