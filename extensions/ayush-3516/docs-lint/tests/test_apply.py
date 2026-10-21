"""Tests for the applier — the only code that writes to a document.

The properties under test are the promises the card makes: nothing lands without approval, a
rejected finding leaves its text byte-identical, and anything that could not be applied is named
rather than glossed over.
"""

from __future__ import annotations

from docs_lint.apply import apply_to_results
from docs_lint.cache import VerdictCache
from docs_lint.config import Config, parse_config
from docs_lint.model import Decision, Decisions, FileResult, Source, Verdict
from docs_lint.parser import parse_document
from docs_lint.rules import run_local_rules
from docs_lint.runner import Runner
from docs_lint.state import RunStore
from docs_lint.superdocs.client import RetryPolicy, SuperDocsClient
from docs_lint.superdocs.lint_pass import STYLE_GUIDE_RULE
from docs_lint.targets import select_targets
from tests.fake_superdocs.server import DEFAULT_API_KEY

DOC = """# Getting started

We utilise the API in order to fetch results.

This sentence must never be touched by anything at all.
"""


def local_result(tmp_path, name="a.md", text=DOC):
    (tmp_path / name).write_text(text)
    config = Config(root=tmp_path)
    document = parse_document(name, text)
    findings = tuple(run_local_rules(document, config))
    return FileResult(path=name, verdict=Verdict.findings(checks_run=("local",)), findings=findings)


def decide(result, **approvals) -> Decisions:
    """Approve findings by their `original` text; anything unnamed is rejected."""
    return Decisions(
        run_id="r1",
        decisions=tuple(
            Decision(finding_id=f.finding_id, approved=approvals.get(_key(f), False))
            for f in result.findings
        ),
    )


def _key(finding) -> str:
    return (finding.original or "").replace(" ", "_").replace("'", "")


# -- nothing lands without approval -------------------------------------------------


def test_an_empty_decision_set_changes_nothing(tmp_path):
    result = local_result(tmp_path)
    before = (tmp_path / "a.md").read_bytes()

    outcome = apply_to_results([result], Decisions(run_id="r1"), root=tmp_path)

    assert (tmp_path / "a.md").read_bytes() == before
    assert outcome.applied == []
    assert outcome.files_written == []


def test_decisions_that_all_say_no_change_nothing(tmp_path):
    result = local_result(tmp_path)
    before = (tmp_path / "a.md").read_bytes()

    outcome = apply_to_results([result], decide(result), root=tmp_path)

    assert (tmp_path / "a.md").read_bytes() == before
    assert outcome.rejected == len(result.findings)


def test_only_the_approved_fix_lands(tmp_path):
    result = local_result(tmp_path)
    outcome = apply_to_results([result], decide(result, utilise=True), root=tmp_path)

    text = (tmp_path / "a.md").read_text()
    assert "We use the API" in text
    assert "in order to" in text, "an unapproved fix must not ride along"
    assert len(outcome.applied) == 1


def test_a_rejected_finding_leaves_its_text_byte_identical(tmp_path):
    """The card's central promise, tested directly."""
    result = local_result(tmp_path)
    outcome = apply_to_results(
        [result], decide(result, utilise=True, in_order_to=False), root=tmp_path
    )

    text = (tmp_path / "a.md").read_text()
    assert "in order to fetch results." in text
    assert "This sentence must never be touched by anything at all." in text
    assert outcome.rejected >= 1


def test_untouched_regions_are_preserved_exactly(tmp_path):
    result = local_result(tmp_path)
    apply_to_results([result], decide(result, utilise=True), root=tmp_path)

    lines = (tmp_path / "a.md").read_text().splitlines()
    assert lines[0] == "# Getting started"
    assert lines[-1] == "This sentence must never be touched by anything at all."


def test_two_approved_fixes_in_one_line_both_land(tmp_path):
    result = local_result(tmp_path)
    apply_to_results([result], decide(result, utilise=True, in_order_to=True), root=tmp_path)

    assert "We use the API to fetch results." in (tmp_path / "a.md").read_text()


# -- honesty about what did not happen ----------------------------------------------


def test_overlapping_fixes_are_reported_as_superseded_not_as_a_mystery(tmp_path):
    """Two rules can target one heading. The first wins; the rest say so plainly."""
    text = "# Getting Started With The Widget.\n\nBody text.\n"
    result = local_result(tmp_path, text=text)
    approvals = {f.finding_id: True for f in result.findings if f.rule_id.startswith("heading-")}
    decisions = Decisions(
        run_id="r1",
        decisions=tuple(
            Decision(finding_id=f.finding_id, approved=approvals.get(f.finding_id, False))
            for f in result.findings
        ),
    )

    outcome = apply_to_results([result], decisions, root=tmp_path)

    assert len(outcome.applied) == 1
    assert any("superseded" in s.reason for s in outcome.skipped)


def test_a_rule_that_offers_no_correction_is_reported_not_silently_dropped(tmp_path):
    text = "```\nno language on this fence\n```\n"
    result = local_result(tmp_path, text=text)
    decisions = Decisions(
        run_id="r1",
        decisions=tuple(Decision(finding_id=f.finding_id, approved=True) for f in result.findings),
    )

    outcome = apply_to_results([result], decisions, root=tmp_path)
    assert any("does not propose a correction" in s.reason for s in outcome.skipped)
    assert outcome.applied == []


def test_a_fix_whose_target_vanished_is_skipped_rather_than_guessed(tmp_path):
    result = local_result(tmp_path)
    # Rewrite the file behind the applier's back.
    (tmp_path / "a.md").write_text("# Something else entirely\n\nNothing matches now.\n")

    outcome = apply_to_results([result], decide(result, utilise=True), root=tmp_path)

    assert outcome.applied == []
    assert any("no longer present" in s.reason for s in outcome.skipped)
    assert not outcome.ok


def test_the_summary_line_states_rejections_and_failures(tmp_path):
    result = local_result(tmp_path)
    outcome = apply_to_results([result], decide(result, utilise=True), root=tmp_path)
    line = outcome.summary_line()
    assert "applied" in line and "rejected" in line


def test_a_file_with_no_approvals_is_never_rewritten(tmp_path):
    """Not even rewritten with identical content: an untouched file keeps its mtime."""
    result = local_result(tmp_path)
    before = (tmp_path / "a.md").stat().st_mtime_ns

    apply_to_results([result], decide(result), root=tmp_path)
    assert (tmp_path / "a.md").stat().st_mtime_ns == before


# -- the SuperDocs half of the gate -------------------------------------------------


def test_approving_a_model_proposal_applies_it_and_rejecting_one_does_not(tmp_path, base_url):
    """End to end through the real approval API: one approved, one rejected."""
    (tmp_path / "styleguide.md").write_text("# Style\nUse plain words.\n")
    # Two separate paragraphs, so the review produces two independently decidable proposals.
    (tmp_path / "a.md").write_text(
        "# Getting started\n\n"
        "We utilise the API.\n\n"
        "You can leverage the client.\n\n"
        "This sentence must never be touched by anything at all.\n"
    )
    config = parse_config(
        {"styleguide": {"path": "styleguide.md", "content_sha256": "pinned"}}, root=tmp_path
    )
    client = SuperDocsClient(
        api_key=DEFAULT_API_KEY,
        base_url=base_url,
        retry=RetryPolicy(max_attempts=2, base_delay=0.0, jitter=False),
        sleep=lambda _s: None,
    )
    store = RunStore(tmp_path)
    runner = Runner(
        config=config,
        store=store,
        cache=VerdictCache(tmp_path, config_fingerprint=config.fingerprint(), enabled=False),
        client=client,
        sleep=lambda _s: None,
    )
    targets, _ = select_targets(config, paths=["a.md"])
    summary = runner.check(targets)

    model = [f for f in summary.all_findings if f.rule_id == STYLE_GUIDE_RULE]
    assert len(model) >= 2, "need at least two proposals to reject one and keep another"

    state = store.load(summary.run_id)
    decisions = Decisions(
        run_id=summary.run_id,
        decisions=(
            Decision(finding_id=model[0].finding_id, approved=True),
            *(Decision(finding_id=f.finding_id, approved=False) for f in model[1:]),
        ),
    )

    outcome = apply_to_results(
        [r for r in summary.results],
        decisions,
        root=tmp_path,
        client=client,
        sessions={f.path: f.session_id for f in state.files if f.session_id},
        job_ids={f.path: f.job_id for f in state.files if f.job_id},
    )

    assert outcome.applied, "the approved proposal did not land"
    text = (tmp_path / "a.md").read_text()
    assert "This sentence must never be touched by anything at all." in text


def test_model_fixes_are_skipped_when_no_session_was_recorded(tmp_path):
    """Better to refuse than to invent a session and apply something unreviewed."""
    result = local_result(tmp_path)
    model = result.findings[0].model_copy(update={"source": Source.SUPERDOCS, "change_id": "ch_1"})
    result = result.model_copy(update={"findings": (model,)})

    outcome = apply_to_results(
        [result],
        Decisions(run_id="r1", decisions=(Decision(finding_id="ch_1", approved=True),)),
        root=tmp_path,
        client=None,
    )
    assert any("no SuperDocs session" in s.reason for s in outcome.skipped)
    assert outcome.applied == []


# -- guarding against the platform changing what nobody approved --------------------


def test_drift_detection_notices_a_block_the_export_altered_without_approval(tmp_path):
    """BUGS.md #11: the Markdown export is not byte-preserving for untouched regions."""
    from docs_lint.apply import detect_drift

    before = "# Title\n\nApproved paragraph.\n\n```\npip install widget\n```\n"
    # The export added a blank line inside the fenced block, which nobody asked for.
    after = "# Title\n\nCorrected paragraph.\n\n```\npip install widget\n\n```\n"

    drift = detect_drift(before, after, approved_originals={"Approved paragraph."}, path="a.md")

    assert len(drift) == 1
    assert "pip install widget" in drift[0].before


def test_drift_detection_is_silent_when_only_approved_text_changed(tmp_path):
    from docs_lint.apply import detect_drift

    before = "# Title\n\nWe utilise it.\n\nUntouched.\n"
    after = "# Title\n\nWe use it.\n\nUntouched.\n"

    assert detect_drift(before, after, approved_originals={"We utilise it."}, path="a.md") == []


def test_a_run_with_drift_is_not_reported_as_ok(tmp_path):
    from docs_lint.apply import ApplyResult, Drift

    outcome = ApplyResult(drift=[Drift(path="a.md", before="x", after=None)])
    assert not outcome.ok
    assert "unapproved change" in outcome.summary_line()
