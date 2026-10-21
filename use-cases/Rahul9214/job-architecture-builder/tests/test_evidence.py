from job_architecture.evidence import extract_role_evidence, is_sparse_evidence
from job_architecture.fixtures import load_corpus
from job_architecture.textutil import UNSTATED, contains_excerpt


def test_extraction_copies_source_language_not_labels() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-swe-backend")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    assert evidence.title == "Software Engineer, Backend"
    assert evidence.organization == "Northstar Systems"
    assert any("on-call" in item.lower() for item in evidence.responsibilities)
    assert "two to three services" in evidence.scope.lower()
    for ref in evidence.source_references:
        assert ref.document_id == evidence.role_id
        assert contains_excerpt(parsed.raw_markdown, ref.excerpt or "")


def test_sparse_role_does_not_invent_rich_dimensions() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-program-coordinator")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    assert is_sparse_evidence(evidence, parsed.raw_markdown)
    assert evidence.complexity == UNSTATED or len(evidence.complexity) < 80
    combined = " ".join([evidence.scope, evidence.autonomy, evidence.complexity, evidence.impact])
    assert "company-wide" not in combined.lower()
    assert "org-wide" not in combined.lower()
    for ref in evidence.source_references:
        assert contains_excerpt(parsed.raw_markdown, ref.excerpt or "")


def test_people_management_split_preserves_negation() -> None:
    corpus = load_corpus("corpus-a")
    parsed = corpus.job_description("ns-em-developer-experience")
    evidence = extract_role_evidence(parsed, corpus.manifest.organization)
    blob = f"{evidence.people_management} {evidence.leadership}".lower()
    assert "does not include people management" in blob or "no direct reports" in blob
    assert "hire, unassign, coach" not in blob
