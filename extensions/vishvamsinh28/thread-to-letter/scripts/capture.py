"""Regenerate docs/commitments.svg from a real run against the live API.

The image in the README is what the tool actually printed, not a mock-up. Costs two
operations.

    uv run python scripts/capture.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rich.console import Console  # noqa: E402


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "thread_to_letter.cli", "run",
         "threads/migration-project.mbox", "--auto", "--format", "markdown",
         "--from", "priya.raman@northwind.example", "--out", str(ROOT / ".capture")],
        cwd=ROOT,
        env={**__import__("os").environ, "COLUMNS": "104",
             "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    console = Console(record=True, width=104)
    console.print()
    console.print("[dim]$ thread2letter run threads/migration-project.mbox[/dim]")
    for line in result.stdout.splitlines():
        console.print(line, markup=False, highlight=False)
    console.save_svg(
        str(ROOT / "docs" / "commitments.svg"),
        title="thread2letter — what was actually committed to",
    )
    print("wrote docs/commitments.svg")

    import shutil

    shutil.rmtree(ROOT / ".capture", ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
