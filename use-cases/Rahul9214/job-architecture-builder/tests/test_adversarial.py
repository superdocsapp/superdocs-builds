from dataclasses import replace

from job_architecture.architecture import build_architecture
from job_architecture.assess import assess_role
from job_architecture.evidence import extract_role_evidence
from job_architecture.fixtures import load_corpus
from job_architecture.models import FitStatus
from job_architecture.textutil import contains_excerpt


def _assessment(corpus_id: str, role_id: str):
    corpus = load_corpus(corpus_id)
    parsed = corpus.job_description(role_id)
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    assessment = assess_role(evidence, raw_markdown=parsed.raw_markdown)
    return corpus, parsed, evidence, assessment


def test_workplace_tools_not_senior_from_title() -> None:
    _, parsed, _, assessment = _assessment("corpus-a", "ns-senior-swe-internal-tools")
    assert assessment.proposed_family == "engineering"
    assert assessment.proposed_track == "individual_contributor"
    assert assessment.proposed_level in {"IC1", "IC2"}
    assert assessment.fit_status is FitStatus.PROVISIONAL
    assert "senior" not in (assessment.proposed_level or "").lower()
    assert any("Senior" in item or "seniority" in item.lower() for item in assessment.counter_evidence)
    for item in assessment.supporting_evidence:
        assert contains_excerpt(parsed.raw_markdown, item.split("] ", 1)[-1])


def test_payments_recognized_despite_modest_title() -> None:
    _, _, _, assessment = _assessment("corpus-a", "ns-swe-ii-payments")
    assert assessment.proposed_family == "engineering"
    assert assessment.proposed_track == "individual_contributor"
    assert assessment.proposed_level in {"IC4", "IC5"}
    assert assessment.fit_status is FitStatus.STRONG_FIT


def test_engineering_manager_dx_is_not_people_manager() -> None:
    _, _, _, assessment = _assessment("corpus-a", "ns-em-developer-experience")
    assert assessment.proposed_family == "engineering"
    assert assessment.proposed_track == "individual_contributor"
    assert assessment.proposed_track != "people_manager"
    assert assessment.fit_status is FitStatus.PROVISIONAL


def test_genuine_engineering_manager_is_people_manager() -> None:
    _, _, _, assessment = _assessment("corpus-a", "ns-em-platform")
    assert assessment.proposed_family == "engineering"
    assert assessment.proposed_track == "people_manager"
    assert assessment.proposed_level == "M1"
    assert assessment.fit_status is FitStatus.STRONG_FIT


def test_solutions_architect_is_hybrid_provisional() -> None:
    _, parsed, _, assessment = _assessment("corpus-a", "ns-solutions-architect")
    assert assessment.fit_status is FitStatus.PROVISIONAL
    assert assessment.proposed_family is None
    assert assessment.proposed_level is None
    blob = " ".join(assessment.supporting_evidence + assessment.counter_evidence).lower()
    assert "sales" in blob or "hybrid" in " ".join(reason.summary.lower() for reason in assessment.misfit_reasons)
    assert assessment.misfit_reasons
    assert assessment.misfit_reasons[0].code == "hybrid_unresolved"
    for item in assessment.supporting_evidence:
        snippet = item.split("] ", 1)[-1]
        assert contains_excerpt(parsed.raw_markdown, snippet)


def test_developer_advocate_is_misfit() -> None:
    _, _, _, assessment = _assessment("corpus-a", "ns-developer-advocate")
    assert assessment.fit_status is FitStatus.MISFIT
    assert assessment.proposed_family is None
    assert assessment.proposed_level is None
    assert any(reason.code == "outside_architecture" for reason in assessment.misfit_reasons)


def test_program_coordinator_is_sparse_provisional() -> None:
    _, _, _, assessment = _assessment("corpus-a", "ns-program-coordinator")
    assert assessment.fit_status is FitStatus.PROVISIONAL
    assert assessment.proposed_family is None
    assert assessment.proposed_level is None
    assert assessment.confidence <= 0.4
    assert any(reason.code == "insufficient_evidence" for reason in assessment.misfit_reasons)


def test_principal_widgets_title_independence() -> None:
    _, _, _, assessment = _assessment("corpus-b", "mh-principal-engineer-widgets")
    assert assessment.proposed_family == "engineering"
    assert assessment.proposed_track == "individual_contributor"
    assert assessment.proposed_level in {"IC1", "IC2"}
    assert assessment.fit_status is FitStatus.PROVISIONAL


def test_clinical_implementation_architect_is_hybrid() -> None:
    _, _, _, assessment = _assessment("corpus-b", "mh-clinical-implementation-architect")
    assert assessment.fit_status is FitStatus.PROVISIONAL
    assert assessment.proposed_family is None
    assert any(reason.code == "hybrid_unresolved" for reason in assessment.misfit_reasons)


def test_associate_special_programs_is_sparse() -> None:
    _, _, _, assessment = _assessment("corpus-b", "mh-associate-special-programs")
    assert assessment.fit_status is FitStatus.PROVISIONAL
    assert assessment.proposed_family is None
    assert any(reason.code == "insufficient_evidence" for reason in assessment.misfit_reasons)


def test_medical_science_liaison_is_misfit() -> None:
    _, _, _, assessment = _assessment("corpus-b", "mh-medical-science-liaison")
    assert assessment.fit_status is FitStatus.MISFIT
    assert assessment.proposed_family is None
    assert any(reason.code == "outside_architecture" for reason in assessment.misfit_reasons)


def test_payments_outranks_workplace_tools() -> None:
    _, _, _, juniorish = _assessment("corpus-a", "ns-senior-swe-internal-tools")
    _, _, _, seniorish = _assessment("corpus-a", "ns-swe-ii-payments")
    rank = {"IC1": 1, "IC2": 2, "IC3": 3, "IC4": 4, "IC5": 5}
    assert rank[seniorish.proposed_level] >= rank[juniorish.proposed_level] + 2


def test_supporting_evidence_is_traceable_not_fabricated() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    by_id = {parsed.role_id: parsed.raw_markdown for parsed in corpus.job_descriptions}
    for assessment in result.assessments:
        source = by_id[assessment.role_id]
        for item in assessment.supporting_evidence:
            snippet = item.split("] ", 1)[-1]
            assert contains_excerpt(source, snippet), snippet
        for reason in assessment.misfit_reasons:
            for ref in reason.source_references:
                if ref.excerpt:
                    assert contains_excerpt(source, ref.excerpt)


def test_title_swap_does_not_change_family_track_level() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-swe-ii-payments")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    baseline = assess_role(evidence, raw_markdown=parsed.raw_markdown)
    for title in (
        "Distinguished Fellow",
        "Intern",
        "Vice President of Engineering",
        "Engineering Manager, Payments",
        "Principal Staff Software Architect",
    ):
        mutated = assess_role(replace(evidence, title=title), raw_markdown=parsed.raw_markdown)
        assert mutated.proposed_family == baseline.proposed_family, title
        assert mutated.proposed_track == baseline.proposed_track, title
        assert mutated.proposed_level == baseline.proposed_level, title


def test_manager_title_swap_cannot_create_people_manager() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-em-developer-experience")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    baseline = assess_role(evidence, raw_markdown=parsed.raw_markdown)
    mutated = assess_role(
        replace(evidence, title="Software Engineer, Developer Experience"),
        raw_markdown=parsed.raw_markdown,
    )
    assert baseline.proposed_track == "individual_contributor"
    assert mutated.proposed_track == "individual_contributor"
    assert mutated.proposed_family == baseline.proposed_family
    assert mutated.proposed_level == baseline.proposed_level
    # Removing the misleading manager title may clear the conflict flag.
    assert mutated.fit_status in {FitStatus.STRONG_FIT, FitStatus.PROVISIONAL}


def test_people_manager_survives_ic_title() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-em-platform")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    mutated = assess_role(
        replace(evidence, title="Software Engineer, Platform Services"),
        raw_markdown=parsed.raw_markdown,
    )
    assert mutated.proposed_track == "people_manager"
    assert mutated.proposed_level == "M1"
