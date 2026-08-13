"""Whether the crash-recovery story survives an actual crash.

Every other test in this suite proves a claim by calling a function and
reading what it returns, which proves the code does what it says -- not that
the process it runs inside can be killed and still leave something a second,
unrelated process can recover. `approve --discard` exists for exactly this,
by its own docstring in cli.py: "a batch parked by a run that never wrote one
-- a crash between turns, a different machine, a session someone left open."
That claim had never been run under an actual kill -9 until this file.

`mb edit` runs as a real subprocess against a local stub standing in for
api.superdocs.app (`stub_superdocs.py`), gets SIGKILLed while it is genuinely
blocked inside the HTTP call that polls a parked job, and a second, freshly
started process is then asked to clean up after it. No network, no key, no
quota -- the stub is local and free, and nothing here touches the real
service.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import PROJECT_ROOT
from .stub_superdocs import Stub

PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


@pytest.fixture
def stub():
    server = Stub()
    yield server
    server.stop()


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A fresh project directory `mb` can run in: just the spec it needs.

    Not `PROJECT_ROOT` itself -- this test writes `out/published.json` and
    `out/proposal.json`, and a crash test should not leave debris in the real
    working copy if something about it goes wrong.
    """
    (tmp_path / "spec").mkdir()
    shutil.copy(PROJECT_ROOT / "spec" / "halyard_m1.yaml", tmp_path / "spec" / "halyard_m1.yaml")
    return tmp_path


def _env(stub: Stub) -> dict[str, str]:
    return {
        **os.environ,
        "SUPERDOCS_API_KEY": "sk_test_stub",
        "SUPERDOCS_BASE_URL": stub.base_url,
    }


def _mb(args: list[str], cwd: Path, stub: Stub, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), "-m", "manualbuilder.cli", *args],
        cwd=cwd,
        env=_env(stub),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_a_killed_edit_leaves_a_batch_that_discard_still_finds(stub: Stub, workdir: Path):
    published = _mb(["publish"], workdir, stub)
    assert published.returncode == 0, published.stderr
    assert (workdir / "out" / "published.json").is_file()

    # Not `_mb`: this one has to be killed mid-flight, so it is launched
    # rather than run to completion.
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "manualbuilder.cli", "edit", "raise the rail torque to 1.6 N·m"],
        cwd=workdir,
        env=_env(stub),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    got_there = stub.polled.wait(timeout=15)
    proc.kill()
    proc.wait(timeout=5)

    assert got_there, "the edit never reached the point of polling a job -- nothing was tested"
    assert proc.returncode != 0, "a killed process does not exit 0"
    assert not (workdir / "out" / "proposal.json").exists(), (
        "the process died before `edit_both` returned, so nothing should have been "
        "written locally -- a proposal.json here would be a half-written lie about "
        "what actually happened"
    )

    # Both turns really were sent before either was waited on: the manual's
    # and the card's jobs both exist server-side, and only the first one was
    # ever polled.
    assert len(stub.jobs) == 2
    assert all(job["status"] == "awaiting_approval" for job in stub.jobs.values())

    # A second process, sharing nothing with the first but the disk and the
    # stub, is handed the cleanup.
    discarded = _mb(["approve", "--discard"], workdir, stub)
    assert discarded.returncode == 0, discarded.stderr
    assert "denied 2 proposed change(s)" in discarded.stdout

    assert len(stub.approve_calls) == 2, "one deny call per stranded job, manual and card alike"
    for call in stub.approve_calls:
        assert call["approved"] is False
        assert all(change["approved"] is False for change in call["changes"])

    # Recovery is not a one-shot trick: the session is genuinely free now.
    quiet = _mb(["approve", "--discard"], workdir, stub)
    assert quiet.returncode == 0
    assert "nothing was parked" in quiet.stdout
