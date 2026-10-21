from dataclasses import replace

from job_architecture.architecture import build_architecture
from job_architecture.assess import assess_role
from job_architecture.evidence import extract_role_evidence
from job_architecture.fixtures import load_corpus
from job_architecture.models import FitStatus, TitleConflictKind


def _assessment(corpus_id: str, role_id: str):
    corpus = load_corpus(corpus_id)
    parsed = corpus.job_description(role_id)
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    assessment = assess_role(evidence, raw_markdown=parsed.raw_markdown)
    return evidence, assessment


def test_senior_style_title_overstates_junior_ic_evidence() -> None:
    _, assessment = _assessment("corpus-a", "ns-senior-swe-internal-tools")
    assert assessment.title_conflict is not None
    assert assessment.title_conflict.kind is TitleConflictKind.TITLE_SENIORITY_OVERSTATES_EVIDENCE
    assert assessment.proposed_level in {"IC1", "IC2"}
    assert assessment.proposed_track == "individual_contributor"


def test_modest_title_understates_high_scope_ic() -> None:
    _, assessment = _assessment("corpus-a", "ns-swe-ii-payments")
    assert assessment.fit_status is FitStatus.STRONG_FIT
    assert assessment.proposed_level in {"IC4", "IC5"}
    assert assessment.title_conflict is not None
    assert assessment.title_conflict.kind is TitleConflictKind.TITLE_UNDERSTATES_SCOPE


def test_manager_title_conflicts_when_track_is_ic() -> None:
    _, assessment = _assessment("corpus-a", "ns-em-developer-experience")
    assert assessment.proposed_track == "individual_contributor"
    assert assessment.title_conflict is not None
    assert assessment.title_conflict.kind is TitleConflictKind.TITLE_MANAGEMENT_CONFLICT


def test_genuine_manager_title_is_not_a_management_conflict() -> None:
    _, assessment = _assessment("corpus-a", "ns-em-platform")
    assert assessment.proposed_track == "people_manager"
    assert assessment.title_conflict is None


def test_aligned_engineering_ic_has_no_title_conflict() -> None:
    _, assessment = _assessment("corpus-a", "ns-swe-backend")
    assert assessment.proposed_track == "individual_contributor"
    assert assessment.title_conflict is None


def test_corpus_b_principal_title_uses_same_overstatement_rule() -> None:
    _, assessment = _assessment("corpus-b", "mh-principal-engineer-widgets")
    assert assessment.proposed_level in {"IC1", "IC2"}
    assert assessment.title_conflict is not None
    assert assessment.title_conflict.kind is TitleConflictKind.TITLE_SENIORITY_OVERSTATES_EVIDENCE


def test_title_only_mutation_changes_conflict_metadata_not_assignment() -> None:
    evidence, baseline = _assessment("corpus-a", "ns-swe-ii-payments")
    distinguished = assess_role(replace(evidence, title="Distinguished Fellow"), raw_markdown="unused")
    intern = assess_role(replace(evidence, title="Intern"), raw_markdown="unused")
    managerish = assess_role(
        replace(evidence, title="Engineering Manager, Payments"),
        raw_markdown="unused",
    )
    for mutated in (distinguished, intern, managerish):
        assert mutated.proposed_family == baseline.proposed_family
        assert mutated.proposed_track == baseline.proposed_track
        assert mutated.proposed_level == baseline.proposed_level
    assert intern.title_conflict is not None
    assert intern.title_conflict.kind is TitleConflictKind.TITLE_UNDERSTATES_SCOPE
    assert managerish.title_conflict is not None
    assert managerish.title_conflict.kind is TitleConflictKind.TITLE_MANAGEMENT_CONFLICT
    assert distinguished.title_conflict is None


def test_removing_manager_title_clears_management_conflict_only() -> None:
    evidence, baseline = _assessment("corpus-a", "ns-em-developer-experience")
    assert baseline.title_conflict is not None
    mutated = assess_role(
        replace(evidence, title="Software Engineer, Developer Experience"),
        raw_markdown="unused",
    )
    assert mutated.proposed_family == baseline.proposed_family
    assert mutated.proposed_track == baseline.proposed_track
    assert mutated.proposed_level == baseline.proposed_level
    assert mutated.title_conflict is None or mutated.title_conflict.kind is not TitleConflictKind.TITLE_MANAGEMENT_CONFLICT


def test_architecture_summary_lists_only_typed_conflicts() -> None:
    result = build_architecture(load_corpus("corpus-a"))
    conflicts = {item.role_id: item.title_conflict for item in result.assessments if item.title_conflict}
    assert "ns-senior-swe-internal-tools" in conflicts
    assert "ns-swe-ii-payments" in conflicts
    assert "ns-em-developer-experience" in conflicts
    assert "ns-em-platform" not in conflicts
    assert "ns-swe-backend" not in conflicts
