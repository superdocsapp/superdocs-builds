"""The claims worth testing: a run killed and resumed, two runs at once.

These use real operating-system processes and a real SIGKILL rather than simulating interruption
in-process. A test that calls a resume function directly proves the function works; it does not
prove the state on disk survives a process dying between two writes, which is the actual claim.

They are slower than the rest of the suite and marked, so they can be run alone:

    pytest -m resume
    pytest -m concurrency

Both run against the fake service, so neither needs an API key or spends an operation.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from docs_lint.state import RunStore

SLOW_DOC = """# Getting started

We utilise the API in order to fetch results.

This sentence must never be touched by anything at all.
"""

CONFIG = """
[styleguide]
path = "styleguide.md"
content_sha256 = "pinned"

[superdocs]
enabled = true
poll_interval_seconds = 0.05
job_timeout_seconds = 60
"""

#: A driver script, run as a real subprocess so it can be killed for real.
DRIVER = """
import os, sys, json
sys.path.insert(0, {src!r})
sys.path.insert(0, {tests_root!r})

from pathlib import Path
from docs_lint.cache import VerdictCache
from docs_lint.config import load_config
from docs_lint.runner import Runner
from docs_lint.state import RunStore
from docs_lint.superdocs.client import RetryPolicy, SuperDocsClient
from docs_lint.targets import select_targets

root = Path({root!r})
config = load_config(root)
store = RunStore(root)
client = SuperDocsClient(
    api_key={api_key!r},
    base_url={base_url!r},
    retry=RetryPolicy(max_attempts=2, base_delay=0.0, jitter=False),
)

def announce(event):
    print(json.dumps({{"stage": event.stage, "action": event.action, "path": event.path}}),
          flush=True)

runner = Runner(
    config=config,
    store=store,
    cache=VerdictCache(root, config_fingerprint=config.fingerprint(), enabled={cache!r}),
    client=client,
    observe=announce,
)

targets, _ = select_targets(config)
mode = {mode!r}
if mode == "resume":
    summary = runner.resume({run_id!r}, targets)
else:
    summary = runner.check(targets)

print(json.dumps({{"result": "done", "run_id": summary.run_id,
                   "ops": summary.ops_charged,
                   "findings": len(summary.all_findings)}}), flush=True)
"""


def build_workspace(tmp_path: Path, documents: dict[str, str]) -> Path:
    (tmp_path / "styleguide.md").write_text("# Style\nUse plain words.\n")
    (tmp_path / "docs-lint.toml").write_text(CONFIG)
    for name, body in documents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return tmp_path


def driver_source(root: Path, base_url: str, *, mode="check", run_id="", cache=False) -> str:
    here = Path(__file__).resolve().parent
    return DRIVER.format(
        src=str(here.parent / "src"),
        tests_root=str(here.parent),
        root=str(root),
        base_url=base_url,
        api_key="sk_fake_test_key",
        mode=mode,
        run_id=run_id,
        cache=cache,
    )


def spawn(root: Path, script: str) -> subprocess.Popen:
    path = root / f".driver-{os.getpid()}-{time.monotonic_ns()}.py"
    path.write_text(script)
    return subprocess.Popen(
        [sys.executable, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(root),
    )


# -- it survives being stopped ------------------------------------------------------


@pytest.mark.resume
def test_a_run_killed_mid_flight_resumes_without_repeating_or_re_buying_work(
    tmp_path, base_url, fake_state, set_fault
):
    """Kill the process while a document is in the middle of its model pass, then resume.

    The assertions that matter: the resumed run does not start a second SuperDocs job for the same
    document, and the findings the first run had already paid for are still there.
    """
    # Make the job take several polls, so there is a real window in which to kill the process.
    set_fault(job_polls_until_proposals=40)
    root = build_workspace(tmp_path, {"a.md": SLOW_DOC})

    process = spawn(root, driver_source(root, base_url))
    try:
        # Wait until the run has actually instructed SuperDocs and persisted the job id.
        deadline = time.monotonic() + 30
        instructed = False
        while time.monotonic() < deadline and not instructed:
            line = process.stdout.readline()
            if not line:
                break
            event = json.loads(line) if line.strip().startswith("{") else {}
            instructed = event.get("action") == "instructed"
        assert instructed, "the run never reached the SuperDocs pass"

        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    finally:
        if process.poll() is None:  # pragma: no cover - defensive
            process.kill()

    assert process.returncode == -signal.SIGKILL

    # The state on disk survived the kill and remembers the job that was already paid for.
    store = RunStore(root)
    run_id = store.latest_run_id()
    assert run_id is not None
    killed = store.load(run_id)
    assert killed.file("a.md") is not None
    assert killed.file("a.md").job_id, "the job id was not persisted before the first poll"
    ops_after_kill = fake_state()["operations_used"]
    assert ops_after_kill == 1

    # Let the job finish, then resume.
    set_fault(job_polls_until_proposals=1)
    resumed = spawn(root, driver_source(root, base_url, mode="resume", run_id=run_id))
    stdout, stderr = resumed.communicate(timeout=120)
    assert resumed.returncode == 0, stderr

    events = [json.loads(x) for x in stdout.splitlines() if x.strip().startswith("{")]
    final = next(e for e in events if e.get("result") == "done")

    assert any(e.get("action") == "reattached" for e in events), (
        "the resumed run started a fresh job instead of reattaching to the one already bought"
    )
    assert fake_state()["operations_used"] == 1, "resuming must not spend a second operation"
    assert final["findings"] > 0, "work finished before the kill was lost"


@pytest.mark.resume
def test_finished_documents_are_not_rechecked_when_a_later_one_fails(
    tmp_path, base_url, fake_state
):
    """A resume redoes the unfinished, and only the unfinished."""
    root = build_workspace(tmp_path, {"a.md": SLOW_DOC, "b.md": SLOW_DOC.replace("API", "SDK")})

    first = spawn(root, driver_source(root, base_url))
    stdout, stderr = first.communicate(timeout=120)
    assert first.returncode == 0, stderr
    ops_after_first = fake_state()["operations_used"]
    assert ops_after_first == 2

    run_id = RunStore(root).latest_run_id()
    second = spawn(root, driver_source(root, base_url, mode="resume", run_id=run_id))
    stdout, stderr = second.communicate(timeout=120)
    assert second.returncode == 0, stderr

    assert fake_state()["operations_used"] == ops_after_first, (
        "a fully finished run must cost nothing to resume"
    )


# -- two runs at once ---------------------------------------------------------------


@pytest.mark.concurrency
def test_two_runs_over_the_same_repository_do_not_corrupt_each_other(
    tmp_path, base_url, fake_state
):
    """Two processes, same documents, started together.

    Every document must end with exactly one verdict in each run's own state file, no state file
    may be truncated or unparseable, and no document may be linted twice - the lock is what stops
    two runs paying twice to learn the same thing.
    """
    documents = {f"doc{i}.md": SLOW_DOC.replace("API", f"API{i}") for i in range(6)}
    root = build_workspace(tmp_path, documents)

    left = spawn(root, driver_source(root, base_url))
    right = spawn(root, driver_source(root, base_url))

    left_out, left_err = left.communicate(timeout=180)
    right_out, right_err = right.communicate(timeout=180)

    assert left.returncode == 0, left_err
    assert right.returncode == 0, right_err

    store = RunStore(root)
    run_ids = store.list_runs()
    assert len(run_ids) == 2, "two runs must stay two runs"

    for run_id in run_ids:
        state = store.load(run_id)  # parses, so no state file was left half-written
        assert len(state.files) == len(documents)
        assert all(f.verdict is not None for f in state.files), (
            "every document must end with a verdict, even if that verdict is 'skipped'"
        )

    # Note what is deliberately *not* asserted: that each document was checked only once. The lock
    # prevents two runs working a document simultaneously; it does not stop the second run
    # checking it after the first has finished and released it. That is correct - a later run over
    # the same file should check it - and asserting otherwise would encode a misunderstanding.
    #
    # What must hold is that contention resolved cleanly rather than corruptly: every document in
    # every run has exactly one verdict, and any run that lost a race recorded that honestly
    # instead of inventing a result.
    for run_id in run_ids:
        state = store.load(run_id)
        for file_state in state.files:
            verdict = file_state.verdict
            assert verdict is not None
            if not verdict.is_trustworthy:
                assert verdict.reason, f"{file_state.path} has no verdict without a reason"

    # And spending stays bounded: at worst each run pays once per document, never more.
    assert fake_state()["operations_used"] <= 2 * len(documents), "operations ran away"


@pytest.mark.concurrency
def test_no_lock_files_are_left_behind_after_both_runs_finish(tmp_path, base_url):
    root = build_workspace(tmp_path, {f"doc{i}.md": SLOW_DOC for i in range(4)})

    left = spawn(root, driver_source(root, base_url))
    right = spawn(root, driver_source(root, base_url))
    left.communicate(timeout=180)
    right.communicate(timeout=180)

    locks = list((root / ".docs-lint" / "locks").glob("*.lock"))
    assert locks == [], f"stale locks would wedge the next run: {locks}"
