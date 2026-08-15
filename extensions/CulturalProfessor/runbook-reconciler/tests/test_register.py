"""The register's promises, each one tested as a promise rather than as a method.

The four that matter, in the order they would hurt if broken:

1. A re-run never un-approves what a human approved.
2. Two sweeps at once stay two sweeps.
3. An id survives an unrelated edit elsewhere on the page, and does not survive
   an edit to the passage itself.
4. `unverifiable` is counted separately, always.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from reconciler.claims import Anchor, Claim, Finding
from reconciler.register import Register


def anchor(text_hash: str = "h1", index: int = 3, occurrence: int = 0) -> Anchor:
    return Anchor(
        heading_path=("Triage",),
        node_index=index,
        content_hash=text_hash,
        char_start=100,
        char_end=180,
        occurrence=occurrence,
    )


def claim(text_hash: str = "h1", index: int = 3, occurrence: int = 0) -> Claim:
    return Claim(
        page_id="1001",
        kind="threshold",
        subject="alert:PaymentsApiHighLatency:threshold",
        asserted="800ms",
        excerpt="stays above 800ms for 10 minutes",
        anchor=anchor(text_hash, index, occurrence),
        page_version=7,
    )


def finding(claim_id: str | None = None, verdict: str = "contradicts") -> Finding:
    return Finding(
        rule_id="alert-threshold",
        kind="threshold",
        subject="alert:PaymentsApiHighLatency:threshold",
        verdict=verdict,  # type: ignore[arg-type]
        evidence_file="fixtures/infra/platform-infra/monitoring/payments.rules.yml",
        evidence_line=7,
        claim_id=claim_id,
        page_id="1001",
        observed="1.2",
    )


@pytest.fixture
def register(tmp_path: Path) -> Register:
    with Register(tmp_path / "register.db") as reg:
        yield reg


# ------------------------------------------------------------- identity ----


def test_the_same_claim_twice_is_one_row(register: Register) -> None:
    first = register.upsert_claim(claim())
    second = register.upsert_claim(claim())
    assert first == second
    assert len(register.claims_for_page("1001")) == 1


def test_an_unrelated_edit_above_the_passage_does_not_change_the_id() -> None:
    """Somebody fixes a typo three headings up and every claim below it shifts.

    If node position were part of the identity, that page would produce a full
    queue of duplicate findings the next morning. It is the single most likely
    way for this tool to become annoying enough to uninstall.
    """
    assert claim(index=3).claim_id == claim(index=11).claim_id


def test_editing_the_passage_itself_does_change_the_id() -> None:
    """And this is how an applied fix stops being re-proposed.

    Once the text says 1.2s, the claim that said 800ms no longer exists. Rule 6
    falls out of the identity scheme rather than depending on a flag.
    """
    assert claim(text_hash="before").claim_id != claim(text_hash="after").claim_id


def test_two_identical_sentences_under_one_heading_stay_two_claims(register: Register) -> None:
    register.upsert_claim(claim(occurrence=0))
    register.upsert_claim(claim(occurrence=1))
    assert len(register.claims_for_page("1001")) == 2


# ------------------------------------------------------- human decisions ----


def test_a_resweep_does_not_undo_an_approval(register: Register) -> None:
    claim_id = register.upsert_claim(claim())
    finding_id = register.upsert_finding(finding(claim_id))
    register.decide(finding_id, "approved")

    register.upsert_finding(finding(claim_id))  # the next sweep, same drift

    stored = register.finding(finding_id)
    assert stored is not None
    assert stored.decision == "approved"
    assert stored.decided_at is not None


def test_a_resweep_does_not_undo_an_application(register: Register) -> None:
    claim_id = register.upsert_claim(claim())
    finding_id = register.upsert_finding(finding(claim_id))
    register.decide(finding_id, "approved")
    register.mark_applied(finding_id)

    register.upsert_finding(finding(claim_id))

    stored = register.finding(finding_id)
    assert stored is not None and stored.applied_at is not None


def test_rejecting_one_finding_leaves_the_others_in_the_queue(register: Register) -> None:
    first = register.upsert_finding(finding(register.upsert_claim(claim("a"))))
    second = register.upsert_finding(
        Finding(
            rule_id="ci-job",
            kind="command",
            subject="workflow:payments-api/deploy:job",
            verdict="contradicts",
            evidence_file="fixtures/infra/service-repos/payments-api/.github/workflows/deploy.yml",
            claim_id=register.upsert_claim(claim("b")),
            page_id="1001",
        )
    )
    register.decide(first, "rejected")

    queue = [f.finding_id for f in register.review_queue()]
    assert queue == [second]


# ------------------------------------------------------------- the resume ---


def test_approved_but_unapplied_survives_a_restart(tmp_path: Path) -> None:
    """The crash window: approved, killed, restarted. Nothing lost, nothing doubled."""
    path = tmp_path / "register.db"
    with Register(path) as reg:
        finding_id = reg.upsert_finding(finding(reg.upsert_claim(claim())))
        reg.decide(finding_id, "approved")

    with Register(path) as reopened:  # a fresh process would see exactly this
        pending = reopened.approved_unapplied()
        assert [f.finding_id for f in pending] == [finding_id]
        reopened.mark_applied(finding_id)
        assert reopened.approved_unapplied() == []


# ------------------------------------------------------------ concurrency ---


def test_two_sweeps_at_once_do_not_corrupt_the_register(tmp_path: Path) -> None:
    """Behaviour nine of the brief, against the real file rather than a mock.

    Two connections, two threads, overlapping writes of overlapping ids. WAL
    plus busy_timeout is what turns the second writer's `database is locked`
    into a wait; without either pragma this test is where that shows up.

    The barrier only lines the two threads up; it is not the thing under test,
    so a machine too loaded to reach it inside the timeout is a broken *test*,
    not a broken register. It gets its own error so the two cannot be confused
    -- they were, once, and `concurrent sweeps failed: [BrokenBarrierError()]`
    reads exactly like the corruption this test exists to catch.
    """
    path = tmp_path / "register.db"
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def sweep(tag: str) -> None:
        try:
            with Register(path) as reg:
                try:
                    barrier.wait(timeout=60)
                except threading.BrokenBarrierError:
                    raise AssertionError(
                        "the two threads never lined up -- this machine was too busy "
                        "to start both within 60s, and nothing was proved either way"
                    ) from None
                for n in range(40):
                    claim_id = reg.upsert_claim(claim(text_hash=f"{tag}-{n}"))
                    reg.upsert_finding(finding(claim_id))
        except Exception as exc:  # surfaced in the assertion below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=sweep, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)

    # A thread still running here would otherwise be counted as a thread that
    # wrote nothing, and the row count below would fail as though the register
    # had lost writes.
    assert not [t for t in threads if t.is_alive()], "a sweep thread never finished"
    assert not errors, f"concurrent sweeps failed: {errors}"
    with Register(path) as reg:
        assert len(reg.claims_for_page("1001")) == 80
        assert reg._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# --------------------------------------------------------------- counting ---


def test_unverifiable_is_counted_separately_and_never_folded_in(register: Register) -> None:
    register.upsert_finding(finding(register.upsert_claim(claim("a")), verdict="agrees"))
    register.upsert_finding(
        Finding(
            rule_id="rpo",
            kind="threshold",
            subject="dr:payments:rpo",
            verdict="unverifiable",
            evidence_file="fixtures/infra/platform-infra/terraform/payments.tf",
            claim_id=register.upsert_claim(claim("b")),
            page_id="1006",
        )
    )

    summary = register.summary()
    assert summary["agrees"] == 1
    assert summary["unverifiable"] == 1
    assert summary["contradicts"] == 0


def test_unverifiable_findings_stay_out_of_the_review_queue(register: Register) -> None:
    """Counted in every summary, not queued for adjudication.

    Both halves of that matter. A queue holding every RPO nobody can check is a
    queue that stops being read, and a summary that hides them is rule 4.
    """
    register.upsert_finding(
        Finding(
            rule_id="rpo",
            kind="threshold",
            subject="dr:payments:rpo",
            verdict="unverifiable",
            evidence_file="fixtures/infra/platform-infra/terraform/payments.tf",
            claim_id=register.upsert_claim(claim()),
            page_id="1006",
        )
    )
    assert register.review_queue() == []
    assert register.summary()["unverifiable"] == 1


# -------------------------------------------------------------- integrity ---


def test_a_verdict_outside_the_three_is_refused_by_the_database(register: Register) -> None:
    """The CHECK constraint is the backstop for a typo in a rules file.

    A rule that emits `verified` instead of `agrees` should fail loudly at the
    write, not create a fourth bucket nobody counts.
    """
    claim_id = register.upsert_claim(claim())
    bogus = Finding(
        rule_id="typo",
        kind="threshold",
        subject="s",
        verdict="verified",  # type: ignore[arg-type]
        evidence_file="x",
        claim_id=claim_id,
        page_id="1001",
    )
    with pytest.raises(sqlite3.IntegrityError):
        register.upsert_finding(bogus)


def test_forgetting_a_page_takes_its_findings_with_it(register: Register) -> None:
    claim_id = register.upsert_claim(claim())
    register.upsert_finding(finding(claim_id))
    register.forget_page("1001")
    assert register.claims_for_page("1001") == []
    assert register.findings() == []


def test_the_same_subject_across_pages_comes_back_together(register: Register) -> None:
    """The multi-document consistency query, which stage 10 leans on."""
    register.upsert_claim(claim("runbook"))
    slo = Claim(
        page_id="1007",
        kind="threshold",
        subject="alert:PaymentsApiHighLatency:threshold",
        asserted="800ms",
        excerpt="p99 request latency stays below 800ms",
        anchor=Anchor(("Latency",), 2, "slo-hash", 40, 90),
    )
    register.upsert_claim(slo)

    pages = {c.page_id for c in register.claims_for_subject(claim().subject)}
    assert pages == {"1001", "1007"}


# ------------------------------------------------------------- accounting ---


def test_a_run_reports_what_it_spent_and_where_the_time_went(register: Register) -> None:
    run_id = register.start_run(mode="sweep")
    register.record_stage(run_id, "read-ground-truth", seconds=0.4)
    register.record_stage(run_id, "extract-claims", seconds=1.1)
    register.record_stage(run_id, "check", seconds=0.2)
    register.record_stage(run_id, "propose", seconds=31.7, operations=2)
    register.finish_run(run_id)

    cost = register.run_cost(run_id)
    assert cost["operations"] == 2
    assert cost["seconds"] == pytest.approx(33.4)
    assert [s["stage"] for s in cost["stages"]] == [
        "read-ground-truth",
        "extract-claims",
        "check",
        "propose",
    ]


def test_a_sweep_that_found_nothing_reports_a_literal_zero(register: Register) -> None:
    """Not silence. The zero is the product claim, so it has to be printable."""
    run_id = register.start_run(mode="sweep")
    register.record_stage(run_id, "check", seconds=0.3, operations=0)
    register.finish_run(run_id)
    assert register.run_cost(run_id)["operations"] == 0
