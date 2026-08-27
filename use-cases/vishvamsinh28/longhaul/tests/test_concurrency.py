"""Two runs at once stay two runs — whether they are two jobs or one job hit twice."""

from __future__ import annotations

import concurrent.futures
import shutil
from dataclasses import replace

from .conftest import Harness


def test_one_run_hit_twice_at_once_executes_each_step_once(harness: Harness) -> None:
    """The same run, started twice concurrently.

    Exactly one process may execute a step. The other must lose the lease or lose the
    compare-and-swap and back off — never force the write, because forcing it is how two
    processes issue the same edit.
    """
    harness.reset()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(harness.run) for _ in range(2)]
        results = [f.result() for f in futures]

    duplicates = harness.server.stats()["duplicate_turns"]
    assert not duplicates, f"a turn was issued twice under concurrency: {duplicates}"

    # One of them owns the run; the other is expected to be turned away cleanly.
    codes = sorted(r.returncode for r in results)
    assert 0 in codes, f"neither process completed the run: {[r.stdout for r in results]}"
    assert codes[0] in (0, 3), f"unexpected exit codes {codes}"

    status = harness.status()
    assert status["status"] == "completed"
    assert all(
        s["state"] in ("done", "rejected") for s in status["steps"]
    ), status["steps"]


def test_a_concurrent_loser_leaves_no_partial_damage(harness: Harness) -> None:
    """After the collision, the run must still finish cleanly and match a solo run."""
    harness.reset()
    solo = harness.run()
    assert solo.returncode == 0
    expected_docs = harness.document_html()
    expected_commits = harness.commit_log()

    harness.reset()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        [f.result() for f in [pool.submit(harness.run) for _ in range(3)]]
    # Whoever lost, a following run finishes what is left.
    assert harness.run().returncode == 0

    assert harness.document_html() == expected_docs
    assert harness.commit_log() == expected_commits
    assert not harness.server.stats()["duplicate_turns"]


def test_two_different_runs_do_not_interfere(harness: Harness) -> None:
    """Separate runs share a ledger and a server and must stay completely separate."""
    harness.reset()
    other_dir = harness.workdir / "second"
    other_dir.mkdir(exist_ok=True)
    second = replace(harness, workdir=other_dir, run_id="prooffixed02")
    shutil.rmtree(second.state_dir, ignore_errors=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(harness.run)
        second_future = pool.submit(second.run)
        first, other = first_future.result(), second_future.result()

    assert first.returncode == 0, f"{first.stdout}\n{first.stderr}"
    assert other.returncode == 0, f"{other.stdout}\n{other.stderr}"
    assert not harness.server.stats()["duplicate_turns"]

    # Same plan, two sessions: identical content, entirely separate server-side state.
    # Compared on exported text, not on HTML — chunk ids are per-session by design, so
    # identical documents in different sessions correctly carry different ids.
    assert harness.session_id != second.session_id
    assert harness.export("markdown") == second.export("markdown")

    for run in (harness, second):
        assert run.status()["status"] == "completed"
