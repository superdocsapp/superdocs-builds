import subprocess
import sys


def test_importing_core_does_not_import_optional_frameworks() -> None:
    program = """
import sys
import superdocs_adapter
for name in ("langgraph", "crewai", "agents"):
    assert name not in sys.modules, f"optional framework imported by core: {name}"
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
