"""Test harness: a real fake server, real subprocesses, real signals.

Nothing here mocks Longhaul's own code. The runner under test talks HTTP to a server in
another process, and the proof suite kills it with a real ``SIGKILL``. Tests that only
prove the mocks work would not prove anything about a crash.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests" / "fake" / "server.py"
FAKE_KEY = "sk_fake_00000000000000000000000000000000"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class FakeServer:
    base_url: str
    state_dir: Path
    process: subprocess.Popen

    def reset(self) -> None:
        """Return the server to a blank slate between trials."""
        for name in ("state.json", "state.tmp"):
            (self.state_dir / name).unlink(missing_ok=True)

    def stats(self) -> dict:
        return httpx.get(f"{self.base_url}/_test/stats", timeout=10).json()

    def documents(self, session_id: str) -> dict:
        return httpx.get(
            f"{self.base_url}/_test/documents/{session_id}", timeout=10
        ).json()


@pytest.fixture(scope="session")
def fake_server(tmp_path_factory: pytest.TempPathFactory):
    """One fake SuperDocs for the whole session; state is reset per trial."""
    state_dir = tmp_path_factory.mktemp("fake-state")
    port = _free_port()
    env = {
        **os.environ,
        "FAKE_STATE_DIR": str(state_dir),
        "FAKE_PORT": str(port),
        "FAKE_JOB_TTL": os.environ.get("FAKE_JOB_TTL", "3600"),
    }
    proc = subprocess.Popen(
        [sys.executable, str(FAKE)], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"fake server died: {proc.stderr.read().decode()[:2000]}")
        try:
            httpx.get(f"{base_url}/v1/sessions", timeout=1).raise_for_status()
            break
        except (httpx.HTTPError, OSError):
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("fake server never became ready")

    yield FakeServer(base_url=base_url, state_dir=state_dir, process=proc)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@dataclass
class Harness:
    """Drives ``longhaul`` as a separate process, the way a crash would find it."""

    server: FakeServer
    workdir: Path
    spec: Path
    run_id: str

    @property
    def state_dir(self) -> Path:
        return self.workdir / "state"

    @property
    def session_id(self) -> str:
        import yaml

        prefix = yaml.safe_load(self.spec.read_text())["session_prefix"]
        return f"{prefix}-{self.run_id}"

    def env(self, **extra: str) -> dict[str, str]:
        return {
            **os.environ,
            "SUPERDOCS_API_KEY": FAKE_KEY,
            "SUPERDOCS_BASE_URL": self.server.base_url,
            "LONGHAUL_STATE_DIR": str(self.state_dir),
            "PYTHONPATH": str(ROOT / "src"),
            # Wide enough that rich never truncates a disposition in captured output.
            "COLUMNS": "200",
            **extra,
        }

    def reset(self) -> None:
        """Blank server, blank ledger. Each trial starts from nothing."""
        self.server.reset()
        shutil.rmtree(self.state_dir, ignore_errors=True)
        shutil.rmtree(self.workdir / "out", ignore_errors=True)

    def destroy_ledger(self) -> None:
        """Lose the local ledger while the server keeps everything.

        Not a crash — a crash preserves the ledger, which is why the kill-point proof
        cannot produce this. This is the ledger being lost, restored from an older backup,
        or rolled back, with the server still holding work the ledger has forgotten.
        """
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def cli(
        self, *args: str, timeout: float = 240, **env: str
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "longhaul.cli", *args],
            cwd=self.workdir, env=self.env(**env),
            capture_output=True, text=True, timeout=timeout,
        )

    def run(self, *, kill_at: str | None = None, trace: Path | None = None,
            gate: str = "policy", timeout: float = 240) -> subprocess.CompletedProcess:
        env: dict[str, str] = {}
        if kill_at:
            env["LONGHAUL_KILL_AT"] = kill_at
            env["LONGHAUL_KILL_MARKER"] = str(self.workdir / "killed.marker")
        if trace:
            env["LONGHAUL_TRACE"] = str(trace)
        return self.cli(
            "run", "--spec", str(self.spec), "--run-id", self.run_id,
            "--gate", gate, "--json", str(self.report_path),
            timeout=timeout, **env,
        )

    @property
    def report_path(self) -> Path:
        return self.workdir / "report.json"

    def report(self) -> dict:
        """The machine-readable report written by the last run."""
        return json.loads(self.report_path.read_text())

    def export(self, fmt: str = "markdown") -> dict[str, bytes]:
        result = self.cli("export", "--run", self.run_id, "--format", fmt,
                          "--out", str(self.workdir / "out"))
        assert result.returncode == 0, f"export failed:\n{result.stdout}\n{result.stderr}"
        target = self.workdir / "out" / self.run_id
        return {p.name: p.read_bytes() for p in sorted(target.iterdir())}

    def document_html(self) -> dict[str, str]:
        docs = self.server.documents(self.session_id)
        return {v["title"]: v["html"] for v in docs.values()}

    def commit_log(self) -> list[tuple]:
        """The ordered decision log: the oracle for "no edit twice, no step skipped"."""
        import sqlite3

        db = self.state_dir / "longhaul.db"
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute(
                "SELECT step_index, change_id, approved FROM commits "
                "WHERE run_id=? ORDER BY seq", (self.run_id,)
            ).fetchall()
        finally:
            conn.close()
        return [tuple(r) for r in rows]

    def status(self) -> dict:
        result = self.cli("status", "--run", self.run_id, "--json")
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def killed_marker(self) -> str | None:
        marker = self.workdir / "killed.marker"
        return marker.read_text() if marker.exists() else None


@pytest.fixture
def harness(fake_server: FakeServer, tmp_path: Path) -> Harness:
    return Harness(
        server=fake_server,
        workdir=tmp_path,
        spec=ROOT / "jobs" / "proof-compact.yaml",
        run_id="prooffixed01",
    )
