"""Regenerate the images in docs/.

Both are produced from a real run against the local deterministic stand-in, so what the
README shows is what the tool actually prints — never a mock-up.

    uv run python scripts/capture.py

The review-UI shot needs Chrome and is captured separately; the command is printed at
the end.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rich.console import Console  # noqa: E402

from longhaul.report import render  # noqa: E402

SPEC = ROOT / "jobs" / "runbook-migration.yaml"
WORK = ROOT / ".capture"
KEY = "sk_demo_00000000000000000000000000000000"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def cli(args: list[str], env: dict[str, str], **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "longhaul.cli", *args],
        cwd=ROOT, env={**env, **extra}, capture_output=True, text=True,
    )


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    port = free_port()

    fake = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "fake" / "server.py")],
        env={**os.environ, "FAKE_STATE_DIR": str(WORK / "fake"), "FAKE_PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    env = {
        **os.environ,
        "SUPERDOCS_API_KEY": KEY,
        "SUPERDOCS_BASE_URL": f"http://127.0.0.1:{port}",
        "LONGHAUL_STATE_DIR": str(WORK / "state"),
        "PYTHONPATH": str(ROOT / "src"),
        "COLUMNS": "108",
    }
    try:
        import httpx

        for _ in range(60):
            try:
                httpx.get(f"http://127.0.0.1:{port}/v1/sessions", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.2)

        # Trace a full run to learn where its checkpoints are, then start over.
        trace = WORK / "trace.txt"
        cli(["run", "--spec", str(SPEC), "--run-id", "capturetrace"], env,
            LONGHAUL_TRACE=str(trace))
        checkpoints = [c for c in trace.read_text().splitlines() if c]
        kill_at = checkpoints[len(checkpoints) // 2]

        (WORK / "fake" / "state.json").unlink(missing_ok=True)
        shutil.rmtree(WORK / "state", ignore_errors=True)

        killed = cli(["run", "--spec", str(SPEC), "--run-id", "capturekill0"], env,
                     LONGHAUL_KILL_AT=kill_at)
        assert killed.returncode == -signal.SIGKILL, killed.returncode

        report_path = WORK / "report.json"
        resumed = cli(["run", "--spec", str(SPEC), "--run-id", "capturekill0",
                       "--json", str(report_path)], env)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr

        console = Console(record=True, width=108)
        console.print()
        console.print(f"[dim]$ longhaul run --spec {SPEC.name}   "
                      f"[/dim][bold]# after SIGKILL at {kill_at}[/bold]")
        console.print()
        render(json.loads(report_path.read_text()), console)
        console.save_svg(
            str(ROOT / "docs" / "resume-report.svg"),
            title="longhaul run — resumed after SIGKILL",
        )
        print(f"wrote docs/resume-report.svg (killed at {kill_at})")
    finally:
        fake.terminate()
        fake.wait(timeout=10)
        shutil.rmtree(WORK, ignore_errors=True)

    print(
        "\nFor docs/review-ui.png, run `make review` in one terminal, then:\n"
        "  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \\\n"
        "    --headless=new --hide-scrollbars --virtual-time-budget=6000 \\\n"
        "    --window-size=1240,1000 --screenshot=docs/review-ui.png \\\n"
        "    http://127.0.0.1:8420"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
