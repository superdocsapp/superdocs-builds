"""End-to-end analysis tests on synthetic events. No key, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import corpus_builder as cb  # noqa: E402
from analysis.analyze import (  # noqa: E402
    analyse,
    latest_decisions,
    load_batches,
    render_report,
    write_timings_csv,
)
from corpus.edit_specs import DOC01  # noqa: E402
from ground_truth import build_reviewer_view, make_decision_event  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "job_doc01.json"


def _confirmations(job: dict) -> dict:
    result = cb.match_changes_to_intents(cb.merge_changes([job]), DOC01.intents)
    return {
        lc.change.change_id: {
            "change_id": lc.change.change_id,
            "should_approve": lc.should_approve,
            "reason": lc.reason,
            "error_kind": lc.error_kind,
            "confirmed_by": "test-designer",
            "confirmed_at": "2026-08-14T10:00:00+00:00",
        }
        for lc in result.labelled
    }


@pytest.fixture
def batch() -> dict:
    job = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return cb.build_document(None, DOC01, offline=FIXTURE, confirmations=_confirmations(job))


def make_events(batch: dict, reviewer_id: str, condition: str, *, oracle: bool, ms: int = 5000):
    """Synthesise a reviewer's pass over a batch.

    oracle=True means they always match ground truth; False means they approve
    everything, which is right on the good changes and wrong on the bad ones.
    """
    key = {r["change_id"]: r["should_approve"] for r in batch["ground_truth"]}
    view = build_reviewer_view(batch)
    lookup = {c["id"]: c for c in view["changes"]}
    source = {c["id"]: c["source_change_id"] for c in batch["changes"]}

    events = []
    for i, change_id in enumerate(lookup):
        should = key[source[change_id]]
        decision = ("approve" if should else "reject") if oracle else "approve"
        # Mimic a real client: the batch renders once, the reviewer reaches
        # each change in turn, and decision_ms runs from engagement.
        rendered = 1_000_000
        engaged = rendered + i * 60_000
        events.append(
            make_decision_event(
                reviewer_id=reviewer_id,
                batch_id=batch["batch_id"],
                condition=condition,
                reviewer_change_id=change_id,
                decision=decision,
                shown_at=_iso(rendered),
                engaged_at=_iso(engaged),
                decided_at=_iso(engaged + ms),
            )
        )
    return events


def _iso(ms_since_epoch: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms_since_epoch / 1000, tz=timezone.utc).isoformat()


# -- dedup ----------------------------------------------------------------


def test_a_revision_counts_once_as_the_final_answer():
    """Append-only logging means a mind-changer appears twice; they vote once."""
    common = dict(
        reviewer_id="R1",
        batch_id="b1",
        condition="batch_section",
        reviewer_change_id="abc123",
        shown_at="2026-08-14T10:00:00+00:00",
    )
    events = [
        make_decision_event(**common, decision="approve", decided_at="2026-08-14T10:00:05+00:00"),
        make_decision_event(**common, decision="reject", decided_at="2026-08-14T10:00:20+00:00"),
    ]
    kept = latest_decisions(events)
    assert len(kept) == 1
    assert kept[0]["decision"] == "reject"


def test_different_reviewers_are_not_deduplicated_together():
    common = dict(
        batch_id="b1",
        condition="batch_section",
        reviewer_change_id="abc123",
        decision="approve",
        shown_at="2026-08-14T10:00:00+00:00",
        decided_at="2026-08-14T10:00:05+00:00",
    )
    events = [
        make_decision_event(reviewer_id="R1", **common),
        make_decision_event(reviewer_id="R2", **common),
    ]
    assert len(latest_decisions(events)) == 2


# -- scoring --------------------------------------------------------------


def test_a_perfect_reviewer_scores_100_percent(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True)
    results = analyse(events, {batch["batch_id"]: batch})
    acc = results["conditions"]["batch_section"]["accuracy"]
    assert acc["accuracy"] == 1.0
    assert acc["missed_by_error_kind"] == {}


def test_approve_everything_misses_exactly_the_seeded_bad_changes(batch):
    events = make_events(batch, "R1", "batch_section", oracle=False)
    results = analyse(events, {batch["batch_id"]: batch})
    acc = results["conditions"]["batch_section"]["accuracy"]

    n_bad = sum(1 for r in batch["ground_truth"] if not r["should_approve"])
    assert acc["correct"] == acc["n"] - n_bad
    assert sum(acc["missed_by_error_kind"].values()) == n_bad
    assert "wrong_number" in acc["missed_by_error_kind"]


def test_confidence_interval_is_reported_and_wide_at_small_n(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True)
    results = analyse(events, {batch["batch_id"]: batch})
    low, high = results["conditions"]["batch_section"]["accuracy"]["ci95"]
    assert 0.0 <= low <= high <= 1.0
    assert high - low > 0.20, "8 observations cannot support a tight interval"


# -- agreement ------------------------------------------------------------


def test_kappa_is_none_with_a_single_reviewer(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True)
    results = analyse(events, {batch["batch_id"]: batch})
    agreement = results["conditions"]["batch_section"]["agreement"]
    assert agreement["kappa"] is None
    assert "at least 2" in agreement["note"]


def test_two_identical_reviewers_agree_perfectly(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True) + make_events(
        batch, "R2", "batch_section", oracle=True
    )
    results = analyse(events, {batch["batch_id"]: batch})
    assert results["conditions"]["batch_section"]["agreement"]["kappa"] == pytest.approx(1.0)


def test_two_opposed_reviewers_agree_worse_than_chance(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True) + make_events(
        batch, "R2", "batch_section", oracle=False
    )
    results = analyse(events, {batch["batch_id"]: batch})
    kappa = results["conditions"]["batch_section"]["agreement"]["kappa"]
    assert kappa is not None and kappa < 0.5


# -- timing ---------------------------------------------------------------


def test_median_decision_time_is_recovered(batch):
    events = make_events(batch, "R1", "sequential_whole", oracle=True, ms=7500)
    results = analyse(events, {batch["batch_id"]: batch})
    assert results["conditions"]["sequential_whole"]["timing_ms"]["median"] == 7500


# -- outputs --------------------------------------------------------------


def test_report_warns_when_every_decision_is_the_same_verdict(batch):
    """Both pilot runs: 27 approvals, 0 rejections. Accuracy was the base rate."""
    events = make_events(batch, "R1", "batch_section", oracle=False)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))

    assert "Every decision was" in report
    assert "measures discrimination" in report


def test_accuracy_is_suppressed_when_only_one_verdict_was_used(batch):
    """Printing 86% invites someone to quote 86%. Suppress it like kappa."""
    events = make_events(batch, "R1", "batch_section", oracle=False)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))

    assert "single verdict" in report
    # No percentage may appear in a DATA row. The header legitimately contains
    # "95% CI", so only the rows are checked.
    table = report[report.index("| Condition |"): report.index("## Data quality")]
    data_rows = [
        line for line in table.splitlines() if line.startswith("| `")
    ]
    assert data_rows, "no data rows found in the results table"
    for row in data_rows:
        assert "%" not in row, f"a base rate survived as a percentage: {row}"


def test_accuracy_is_shown_when_the_reviewer_discriminated(batch):
    """The suppression must not swallow a genuine measurement."""
    events = make_events(batch, "R1", "batch_section", oracle=True, ms=30000)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))

    table = report[report.index("| Condition |"): report.index("## Errors")]
    assert "100%" in table
    assert "single verdict" not in table


def test_report_warns_about_click_through_speed(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True, ms=900)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))

    assert "under 2 seconds" in report
    assert "click-through" in report.lower()


def test_quality_warnings_precede_the_findings(batch):
    """A reader must meet the warning before the numbers it undermines."""
    events = make_events(batch, "R1", "batch_section", oracle=False, ms=800)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))

    assert report.index("Data quality warnings") < report.index("Errors that slipped through")


def test_a_clean_run_gets_no_quality_warnings(batch):
    slow = make_events(batch, "R1", "batch_section", oracle=True, ms=30000)
    fast = make_events(batch, "R2", "batch_section", oracle=False, ms=25000)
    report = render_report(analyse(slow + fast, {batch["batch_id"]: batch}))

    assert "Data quality warnings" not in report


def test_engagement_based_timing_is_used_when_present(batch):
    """decision_ms must exclude time spent on other changes in a batch."""
    view = build_reviewer_view(batch)
    event = make_decision_event(
        reviewer_id="R1",
        batch_id=batch["batch_id"],
        condition="batch_section",
        reviewer_change_id=view["changes"][0]["id"],
        decision="approve",
        shown_at="2026-08-14T10:00:00+00:00",
        engaged_at="2026-08-14T10:02:00+00:00",
        decided_at="2026-08-14T10:02:04+00:00",
    )
    results = analyse([event], {batch["batch_id"]: batch})
    timing = results["conditions"]["batch_section"]["timing_ms"]

    assert timing["median"] == 4000, "must time from engagement, not render"
    assert timing["render_median"] == 124000, "batch-level measure retained"


def test_report_flags_a_single_reviewer_as_not_a_result(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))
    assert "not yet a result" in report
    assert "N = 1 reviewer" in report


def test_report_warns_about_small_samples_without_p_values(batch):
    events = []
    for reviewer in ("R1", "R2", "R3"):
        events += make_events(batch, reviewer, "batch_whole", oracle=True)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))

    assert "Small sample" in report
    assert "p-value" in report, "the report must say why no p-value is given"
    assert "p =" not in report and "p<" not in report


def test_report_always_states_the_ground_truth_limitation(batch):
    events = make_events(batch, "R1", "batch_section", oracle=True)
    report = render_report(analyse(events, {batch["batch_id"]: batch}))
    # The phrase wraps across lines in the rendered markdown, so match a
    # contiguous fragment rather than the full sentence.
    assert "independent legal expert" in report
    assert "designer's pre-registered judgment" in report


def test_recommendation_is_injected_into_the_report(batch):
    """The conclusion must survive regenerating the report."""
    events = make_events(batch, "R1", "batch_section", oracle=True, ms=20000)
    report = render_report(
        analyse(events, {batch["batch_id"]: batch}),
        recommendation="## Recommendation\n\nUse sequential presentation.",
    )
    assert "Use sequential presentation." in report
    assert report.index("## Per condition") < report.index("## Recommendation")


def test_a_missing_recommendation_is_stated_not_hidden(batch, tmp_path):
    """A report that silently omits its conclusion reads like one that has it."""
    from analysis.analyze import load_recommendation

    text = load_recommendation(tmp_path / "nope.md")
    assert "Not yet written" in text

    events = make_events(batch, "R1", "batch_section", oracle=True, ms=20000)
    report = render_report(analyse(events, {batch["batch_id"]: batch}), recommendation=text)
    assert "Not yet written" in report


def test_the_real_recommendation_file_is_present_and_substantive():
    """Guards against shipping the placeholder."""
    from analysis.analyze import RECOMMENDATION_PATH, load_recommendation

    assert RECOMMENDATION_PATH.exists(), "RECOMMENDATION.md is missing"
    text = load_recommendation()
    assert "Not yet written" not in text
    assert len(text) > 2000, "the recommendation should say something"
    # the five things the recommendation has to cover
    for heading in ("cannot rank", "harness", "SuperDocs", "instrumentation", "requires next"):
        assert heading.lower() in text.lower(), f"recommendation does not cover {heading!r}"


def test_timings_csv_has_a_row_per_decision(batch, tmp_path):
    events = make_events(batch, "R1", "batch_section", oracle=True)
    results = analyse(events, {batch["batch_id"]: batch})

    path = tmp_path / "raw_timings.csv"
    write_timings_csv(results["scored_rows"], path)

    rows = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == len(events) + 1  # + header
    assert rows[0].startswith("reviewer_id,condition")


def test_load_batches_refuses_a_tampered_answer_key(batch, tmp_path):
    from ground_truth import GroundTruthTampered

    batch["ground_truth"][0]["should_approve"] = not batch["ground_truth"][0]["should_approve"]
    path = tmp_path / "batches.json"
    path.write_text(json.dumps({"batches": [batch]}), encoding="utf-8")

    with pytest.raises(GroundTruthTampered):
        load_batches(path)
