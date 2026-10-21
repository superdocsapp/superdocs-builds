"""Tests for the core model.

Mostly these test the two invariants the types exist to enforce: that a clean verdict cannot be
manufactured for a file nobody checked, and that a missing decision means "no".
"""

from __future__ import annotations

import pytest

from docs_lint.model import (
    Anchor,
    Decision,
    Decisions,
    FileResult,
    Finding,
    RunSummary,
    Severity,
    Source,
    Verdict,
    VerdictKind,
)


def anchor(path="docs/guide.md", start=1, end=1, char=0, headings=()) -> Anchor:
    return Anchor(
        path=path,
        start_line=start,
        end_line=end,
        start_char=char,
        end_char=char + 5,
        heading_path=headings,
    )


def finding(rule="banned-terms", severity=Severity.ERROR, **kwargs) -> Finding:
    return Finding(
        rule_id=rule,
        severity=severity,
        message=kwargs.pop("message", "avoid 'utilise'"),
        anchor=kwargs.pop("anchor", anchor()),
        **kwargs,
    )


# -- never bluff --------------------------------------------------------------------


def test_a_clean_verdict_must_name_the_checks_that_ran():
    """The whole point: you cannot claim a file is clean without saying how you know."""
    with pytest.raises(ValueError, match="a file nobody checked is skipped, not clean"):
        Verdict.clean(checks_run=())


def test_clean_verdict_records_which_passes_examined_the_file():
    verdict = Verdict.clean(checks_run=("local", "superdocs"))
    assert verdict.kind is VerdictKind.CLEAN
    assert verdict.checks_run == ("local", "superdocs")
    assert verdict.is_trustworthy


@pytest.mark.parametrize(
    ("verdict", "trustworthy"),
    [
        (Verdict.clean(checks_run=("local",)), True),
        (Verdict.findings(checks_run=("local",)), True),
        (Verdict.skipped("over budget"), False),
        (Verdict.failed("SuperDocs unreachable"), False),
    ],
)
def test_only_examined_files_are_trustworthy(verdict, trustworthy):
    assert verdict.is_trustworthy is trustworthy


def test_skipped_and_failed_verdicts_carry_their_reason():
    assert Verdict.skipped("over budget").reason == "over budget"
    assert Verdict.failed("job timed out").reason == "job timed out"


def test_a_failed_file_outranks_findings_in_the_exit_code():
    """ "I could not check this" is worse news than "this has problems"."""
    summary = RunSummary(
        run_id="r1",
        results=(
            FileResult(
                path="a.md",
                verdict=Verdict.findings(checks_run=("local",)),
                findings=(finding(),),
            ),
            FileResult(path="b.md", verdict=Verdict.failed("SuperDocs unreachable")),
        ),
    )
    assert summary.exit_code(frozenset({Severity.ERROR})) == 2


def test_findings_at_gating_severity_exit_one():
    summary = RunSummary(
        run_id="r1",
        results=(
            FileResult(
                path="a.md",
                verdict=Verdict.findings(checks_run=("local",)),
                findings=(finding(severity=Severity.ERROR),),
            ),
        ),
    )
    assert summary.exit_code(frozenset({Severity.ERROR})) == 1


def test_findings_below_gating_severity_exit_zero():
    """Configurable severity means a warning-only run can still pass the build."""
    summary = RunSummary(
        run_id="r1",
        results=(
            FileResult(
                path="a.md",
                verdict=Verdict.findings(checks_run=("local",)),
                findings=(finding(severity=Severity.WARNING),),
            ),
        ),
    )
    assert summary.exit_code(frozenset({Severity.ERROR})) == 0


def test_headline_never_calls_unchecked_files_clean():
    summary = RunSummary(
        run_id="r1",
        results=(
            FileResult(path="a.md", verdict=Verdict.clean(checks_run=("local",))),
            FileResult(path="b.md", verdict=Verdict.skipped("unchanged since last run")),
        ),
    )
    headline = summary.headline(frozenset({Severity.ERROR}))
    assert headline == "1 files checked, no findings (1 skipped)"
    assert summary.is_partial


def test_headline_when_nothing_could_be_checked_says_so():
    summary = RunSummary(
        run_id="r1",
        results=(FileResult(path="a.md", verdict=Verdict.skipped("over budget")),),
    )
    assert "nothing was checked" in summary.headline(frozenset({Severity.ERROR}))


def test_a_run_with_a_degraded_stage_is_partial_even_if_every_file_was_checked():
    summary = RunSummary(
        run_id="r1",
        results=(FileResult(path="a.md", verdict=Verdict.clean(checks_run=("local",))),),
        degraded=("SuperDocs unreachable; local rules only",),
    )
    assert summary.is_partial


# -- never write without approval ---------------------------------------------------


def test_an_absent_decision_is_a_rejection():
    """Silence is not consent."""
    decisions = Decisions(run_id="r1", decisions=(Decision(finding_id="f_a", approved=True),))
    assert decisions.is_approved("f_a")
    assert not decisions.is_approved("f_b")
    assert not decisions.is_approved("")


def test_rejecting_one_finding_does_not_disturb_the_others():
    decisions = Decisions(
        run_id="r1",
        decisions=(
            Decision(finding_id="f_a", approved=True),
            Decision(finding_id="f_b", approved=False),
            Decision(finding_id="f_c", approved=True),
        ),
    )
    assert decisions.approved_ids() == frozenset({"f_a", "f_c"})


def test_covers_reports_findings_the_review_never_saw():
    """A finding that appeared after the review was written has not been reviewed."""
    reviewed = finding(message="one")
    unreviewed = finding(message="two", anchor=anchor(start=9))
    decisions = Decisions(
        run_id="r1", decisions=(Decision(finding_id=reviewed.finding_id, approved=True),)
    )
    assert decisions.covers((reviewed, unreviewed)) == (unreviewed.finding_id,)


# -- finding identity ---------------------------------------------------------------


def test_finding_ids_are_stable_across_runs_for_the_same_problem():
    assert finding().finding_id == finding().finding_id


def test_finding_ids_differ_when_the_problem_differs():
    ids = {
        finding().finding_id,
        finding(message="different message").finding_id,
        finding(anchor=anchor(start=42)).finding_id,
        finding(rule="heading-case").finding_id,
    }
    assert len(ids) == 4


def test_a_superdocs_finding_uses_the_change_id_the_approval_api_expects_back():
    proposed = finding(source=Source.SUPERDOCS, change_id="ch_abc123")
    assert proposed.finding_id == "ch_abc123"


def test_a_finding_without_a_replacement_is_reportable_but_not_fixable():
    assert not finding().is_fixable
    assert finding(replacement="use").is_fixable


# -- anchors ------------------------------------------------------------------------


def test_anchor_location_reads_the_way_an_editor_expects():
    assert anchor(start=12, end=12).location == "docs/guide.md:12"
    assert anchor(start=12, end=15).location == "docs/guide.md:12-15"


def test_anchor_section_uses_the_heading_path():
    assert anchor(headings=("Getting Started", "Install")).section == "Getting Started > Install"
    assert anchor().section == "(document root)"


def test_anchors_overlap_only_within_the_same_file():
    a = anchor(start=1, end=5)
    assert a.overlaps(anchor(start=4, end=8))
    assert not a.overlaps(anchor(start=6, end=8))
    assert not a.overlaps(anchor(path="other.md", start=1, end=5))


def test_worst_severity_is_reported_across_a_files_findings():
    result = FileResult(
        path="a.md",
        verdict=Verdict.findings(checks_run=("local",)),
        findings=(finding(severity=Severity.INFO), finding(severity=Severity.ERROR)),
    )
    assert result.worst_severity is Severity.ERROR
