"""The proof: a restart is invisible in the output.

The experiment, once per kill point:

1. Run the job to completion, uninterrupted. Record the documents, the exported bytes,
   and the ordered commit log. This is the control.
2. Wipe everything. Run the same job again, but ``SIGKILL`` the process at one named
   checkpoint. Confirm it really died of signal 9 and really reached that checkpoint.
3. Resume. Compare against the control.

The kill points are not chosen by hand. Step 1 runs with tracing on and emits every
checkpoint the run actually reached; the trial set is that list. It cannot be
cherry-picked, and it cannot drift away from the code, because it *is* the code's
behaviour.

What is compared, and why each one is needed:

* **Document HTML** — the state on the server.
* **Exported bytes**, markdown and html — the artefact a user actually receives.
* **The commit log** ``(step_index, change_id, approved)`` — this is what catches a
  double-apply that happens to be idempotent in the text, and a skipped step whose
  absence the text would not reveal.
* **The server's own turn counter** — asserted against the server, never against the
  runner's account of itself.
"""

from __future__ import annotations

import json
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from .conftest import Harness

#: The brief asks for at least twenty. A full run traverses far more; sampling exists so
#: the default test suite stays quick, and `make proof` runs every one.
MINIMUM_KILL_POINTS = 20


@dataclass
class Baseline:
    documents: dict[str, str]
    exports_md: dict[str, bytes]
    exports_html: dict[str, bytes]
    commit_log: list[tuple]
    checkpoints: list[str]
    turn_counts: dict[str, int]


@dataclass
class TrialResult:
    checkpoint: str
    ok: bool
    notes: list[str] = field(default_factory=list)


def _baseline(harness: Harness) -> Baseline:
    trace = harness.workdir / "trace.txt"
    harness.reset()
    result = harness.run(trace=trace)
    assert result.returncode == 0, (
        f"the uninterrupted control run must succeed:\n{result.stdout}\n{result.stderr}"
    )
    checkpoints = [ln for ln in trace.read_text().splitlines() if ln]
    assert len(checkpoints) >= MINIMUM_KILL_POINTS, (
        f"only {len(checkpoints)} checkpoints; the brief requires proof across at least "
        f"{MINIMUM_KILL_POINTS}"
    )
    return Baseline(
        documents=harness.document_html(),
        exports_md=harness.export("markdown"),
        exports_html=harness.export("html"),
        commit_log=harness.commit_log(),
        checkpoints=checkpoints,
        turn_counts=harness.server.stats()["turn_counts"],
    )


def _trial(harness: Harness, baseline: Baseline, checkpoint: str) -> TrialResult:
    notes: list[str] = []
    harness.reset()
    Path(harness.workdir / "killed.marker").unlink(missing_ok=True)

    killed = harness.run(kill_at=checkpoint)
    if killed.returncode != -signal.SIGKILL:
        return TrialResult(checkpoint, False, [
            f"expected death by SIGKILL, got returncode {killed.returncode}. "
            f"A kill point that does not fire proves nothing.",
            killed.stdout[-500:], killed.stderr[-500:],
        ])
    if harness.killed_marker() != checkpoint:
        return TrialResult(checkpoint, False, [
            f"process died but never recorded reaching {checkpoint}"
        ])

    resumed = harness.run()
    if resumed.returncode != 0:
        return TrialResult(checkpoint, False, [
            f"resume did not complete (exit {resumed.returncode})",
            resumed.stdout[-1500:], resumed.stderr[-800:],
        ])

    documents = harness.document_html()
    if documents != baseline.documents:
        for title in sorted(set(documents) | set(baseline.documents)):
            if documents.get(title) != baseline.documents.get(title):
                notes.append(f"document {title!r} differs from the uninterrupted run")

    for label, got, want in (
        ("markdown", harness.export("markdown"), baseline.exports_md),
        ("html", harness.export("html"), baseline.exports_html),
    ):
        if got != want:
            for name in sorted(set(got) | set(want)):
                if got.get(name) != want.get(name):
                    notes.append(f"exported {label} bytes differ for {name}")

    commits = harness.commit_log()
    if commits != baseline.commit_log:
        notes.append(
            f"commit log differs: {len(commits)} entries vs {len(baseline.commit_log)}; "
            f"first divergence at {_first_divergence(commits, baseline.commit_log)}"
        )

    duplicates = harness.server.stats()["duplicate_turns"]
    if duplicates:
        notes.append(f"the server received a turn more than once: {duplicates}")

    status = harness.status()
    if status["status"] != "completed":
        notes.append(f"run status is {status['status']!r}, not 'completed'")

    return TrialResult(checkpoint, not notes, notes)


def _first_divergence(a: list, b: list) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"index {i}: {x} vs {y}"
    return f"index {min(len(a), len(b))} (length differs)"


def _sample(checkpoints: list[str]) -> list[str]:
    """Every checkpoint by default; an evenly-spread subset when sampling.

    Sampling strides across the list rather than taking a prefix, so a sampled run still
    covers every stage of every step rather than only the first steps.
    """
    limit = int(os.environ.get("PROOF_SAMPLE", "0"))
    if limit <= 0 or limit >= len(checkpoints):
        return checkpoints
    limit = max(limit, MINIMUM_KILL_POINTS)
    stride = len(checkpoints) / limit
    picked = {checkpoints[min(int(i * stride), len(checkpoints) - 1)] for i in range(limit)}
    return [c for c in checkpoints if c in picked]


@pytest.mark.proof
@pytest.mark.timeout(3600)
def test_restart_is_invisible_at_every_kill_point(harness: Harness, capsys) -> None:
    baseline = _baseline(harness)
    points = _sample(baseline.checkpoints)
    assert len(points) >= MINIMUM_KILL_POINTS, (
        f"{len(points)} kill points is below the required {MINIMUM_KILL_POINTS}"
    )

    results = [_trial(harness, baseline, cp) for cp in points]
    failures = [r for r in results if not r.ok]

    with capsys.disabled():
        print(f"\n  kill points proven : {len(results) - len(failures)}/{len(results)}")
        print(f"  documents compared : {len(baseline.documents)} per trial, "
              f"by HTML and by exported bytes (markdown + html)")
        print(f"  commit log entries : {len(baseline.commit_log)}")
        for r in failures:
            print(f"  FAILED {r.checkpoint}")
            for note in r.notes:
                print(f"         {note}")

    _write_artifact(baseline, results)

    assert not failures, (
        f"{len(failures)} of {len(results)} kill points did not reproduce the "
        f"uninterrupted run:\n" + "\n".join(
            f"  {r.checkpoint}: {'; '.join(r.notes)}" for r in failures
        )
    )


def _write_artifact(baseline: Baseline, results: list[TrialResult]) -> None:
    """Commit the raw data, not just the verdict."""
    target = os.environ.get("PROOF_ARTIFACT")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "kill_points_total": len(results),
        "kill_points_passed": sum(1 for r in results if r.ok),
        "checkpoints_traced": len(baseline.checkpoints),
        "documents": sorted(baseline.documents),
        "commit_log_entries": len(baseline.commit_log),
        "turn_counts": baseline.turn_counts,
        "results": [
            {"checkpoint": r.checkpoint, "identical": r.ok, "notes": r.notes}
            for r in results
        ],
    }, indent=2, sort_keys=True), encoding="utf-8")
