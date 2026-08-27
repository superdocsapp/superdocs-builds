"""I5: a success line only ever means the output is in the state it claims."""

from __future__ import annotations

import json
import sqlite3

from longhaul.model import ISSUING

from .conftest import Harness


def _force_inconclusive(harness: Harness, step_index: int = 1) -> None:
    """Put one step into the state a crash leaves when the evidence cannot be settled.

    The turn is in the session transcript (a full run put it there), its job id points at
    nothing, and the recorded pre-state no longer matches the document. That is the exact
    shape of "something happened here and I cannot tell what" — and the only honest
    response is to stop.
    """
    db = harness.state_dir / "longhaul.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE steps SET state=?, job_id=?, pre_hash=?, disposition=NULL, "
            "evidence=NULL WHERE run_id=? AND step_index=?",
            (ISSUING, "job_that_never_existed", "0" * 64, harness.run_id, step_index),
        )
        conn.commit()
    finally:
        conn.close()


def test_a_run_with_an_unresolved_step_never_reports_completed(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0  # transcript now carries every token

    _force_inconclusive(harness)
    result = harness.run()

    assert result.returncode == 4, "an unresolved step must not exit as success"
    report = harness.report()
    assert report["status"] == "blocked"
    assert report["totals"]["adjudicate"] == 1

    stuck = [s for s in report["steps"] if s["disposition"] == "adjudicate"]
    assert len(stuck) == 1
    assert stuck[0]["evidence"], "the halt must say what it could not establish"
    assert "cannot be established" in stuck[0]["evidence"]


def test_a_human_can_settle_what_the_runner_refused_to_guess(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0
    _force_inconclusive(harness)
    assert harness.run().returncode == 4

    settled = harness.cli("adjudicate", "--run", harness.run_id, "--step", "1",
                          "--resolve", "done")
    assert settled.returncode == 0, settled.stdout

    final = harness.run()
    assert final.returncode == 0
    assert harness.report()["status"] == "completed"


def test_every_step_reports_a_disposition_and_skips_carry_evidence(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0
    report = harness.report()

    for step in report["steps"]:
        assert step["disposition"], f"step {step['step_index']} has no disposition"
        if step["disposition"] != "executed":
            assert step["evidence"], (
                f"step {step['step_index']} claims {step['disposition']!r} without evidence"
            )


def test_the_report_a_person_reads_and_the_one_a_program_reads_agree(
    harness: Harness,
) -> None:
    harness.reset()
    result = harness.run()
    assert result.returncode == 0
    report = harness.report()

    assert report["status"].upper() in result.stdout
    assert str(report["totals"]["executed"]) in result.stdout
    assert str(report["totals"]["changes_approved"]) in result.stdout
    assert str(report["totals"]["billable_operations"]) in result.stdout


def test_cost_and_time_are_reported_per_step(harness: Harness) -> None:
    """A run can say what it spent and where the time went."""
    harness.reset()
    assert harness.run().returncode == 0
    report = harness.report()

    assert report["totals"]["wall_ms"] > 0
    assert report["totals"]["billable_operations"] > 0
    assert sum(s["duration_ms"] for s in report["steps"]) == report["totals"]["step_ms"]

    # A turn that proposed nothing is not billed for the edit it never made.
    free = [s for s in report["steps"] if s["approved"] == 0 and s["rejected"] == 0]
    assert free, "the corpus should contain at least one step with nothing to change"
    assert all(s["billable_ops"] == 0 for s in free), (
        f"a no-op step was billed: {free}"
    )


def test_status_shows_the_resume_point_from_the_ledger(harness: Harness) -> None:
    harness.reset()
    assert harness.run().returncode == 0
    _force_inconclusive(harness, step_index=2)

    status = json.loads(harness.cli("status", "--run", harness.run_id, "--json").stdout)
    unfinished = [s for s in status["steps"] if s["state"] == ISSUING]
    assert [s["index"] for s in unfinished] == [2]


def test_latency_is_reported_as_a_spread_not_an_average(harness: Harness) -> None:
    """A mean hides the slow step behind the fast ones, and the slow step is the whole
    reason a job needs to be resumable. The report gives the tail."""
    harness.reset()
    assert harness.run().returncode == 0
    report = harness.report()

    spread = report["step_latency_ms"]
    assert spread["count"] > 0
    for key in ("min_ms", "p50_ms", "p95_ms", "max_ms", "spread_ms"):
        assert key in spread, f"{key} missing from the latency report"

    assert spread["min_ms"] <= spread["p50_ms"] <= spread["p95_ms"] <= spread["max_ms"]
    assert spread["spread_ms"] == spread["max_ms"] - spread["min_ms"]
    # Nearest-rank: every figure reported is a measurement that actually happened.
    observed = {s["duration_ms"] for s in report["steps"] if s["duration_ms"]}
    for key in ("min_ms", "p50_ms", "p95_ms", "max_ms"):
        assert spread[key] in observed, f"{key} is not one of the measured durations"


def test_percentiles_are_nearest_rank() -> None:
    from longhaul.report import _distribution

    assert _distribution([]) == {"count": 0}
    d = _distribution([10, 20, 30, 40, 100])
    assert d["min_ms"] == 10 and d["max_ms"] == 100
    assert d["p50_ms"] == 30
    assert d["p95_ms"] == 100
    assert d["spread_ms"] == 90
