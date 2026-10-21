from pathlib import Path

import pytest

from job_architecture.fixtures import (
    FORBIDDEN_SOURCE_HINT_PATTERNS,
    REQUIRED_SECTION_HEADINGS,
    find_source_classification_hints,
    iter_corpora,
    load_corpus,
)
from job_architecture.models import FitStatus

ALLOWED_CORPORA = {
    "corpus-a": {
        "organization": "Northstar Systems",
        "min_roles": 18,
        "max_roles": 22,
        "required_adversarial": {
            "misleading_senior_title",
            "modest_title_broad_scope",
            "management_title_without_people",
            "hybrid",
            "specialized_misfit",
            "sparse_evidence",
        },
    },
    "corpus-b": {
        "organization": "Meridian HealthTech",
        "min_roles": 10,
        "max_roles": 14,
        "required_adversarial": {
            "misleading_title",
            "hybrid",
            "sparse_evidence",
            "specialized_misfit",
        },
    },
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=sorted(ALLOWED_CORPORA))
def corpus_id(request: pytest.FixtureRequest) -> str:
    return request.param


def test_both_corpora_are_present() -> None:
    loaded = {item.manifest.corpus_id: item for item in iter_corpora()}
    assert set(loaded) == set(ALLOWED_CORPORA)


def test_corpus_parses_and_counts_match(corpus_id: str) -> None:
    spec = ALLOWED_CORPORA[corpus_id]
    corpus = load_corpus(corpus_id)
    assert corpus.manifest.organization == spec["organization"]
    assert corpus.expected.organization == spec["organization"]
    role_count = len(corpus.manifest.roles)
    assert spec["min_roles"] <= role_count <= spec["max_roles"]
    assert len(corpus.expected.assessments) == role_count
    assert len(corpus.job_descriptions) == role_count


def test_manifest_and_expected_role_ids_align(corpus_id: str) -> None:
    corpus = load_corpus(corpus_id)
    manifest_ids = corpus.manifest.role_ids()
    expected_ids = list(corpus.expected.by_role_id())
    assert manifest_ids == expected_ids


def test_markdown_titles_and_teams_match_manifest(corpus_id: str) -> None:
    corpus = load_corpus(corpus_id)
    by_id = {item.role_id: item for item in corpus.job_descriptions}
    for role in corpus.manifest.roles:
        parsed = by_id[role.id]
        assert parsed.title == role.title
        team_line = parsed.section("team").splitlines()[0].strip()
        assert team_line == role.team
        for heading in REQUIRED_SECTION_HEADINGS:
            assert parsed.section(heading).strip()


def test_source_job_descriptions_contain_no_classification_hints(corpus_id: str) -> None:
    corpus = load_corpus(corpus_id)
    for parsed in corpus.job_descriptions:
        hints = find_source_classification_hints(parsed.raw_markdown)
        assert hints == [], f"{parsed.path.name} contains classification hints: {hints}"
        lower = parsed.raw_markdown.lower()
        assert "expected family" not in lower
        assert "expected level" not in lower
        assert "---" not in parsed.raw_markdown.splitlines()[0]


def test_expected_fit_status_values_are_constrained(corpus_id: str) -> None:
    corpus = load_corpus(corpus_id)
    allowed = {status.value for status in FitStatus}
    for assessment in corpus.expected.assessments:
        assert assessment.fit_status.value in allowed
        if assessment.fit_status is FitStatus.STRONG_FIT:
            assert assessment.proposed_family is not None


def test_adversarial_cases_are_represented(corpus_id: str) -> None:
    spec = ALLOWED_CORPORA[corpus_id]
    corpus = load_corpus(corpus_id)
    present = {item.adversarial_case for item in corpus.expected.adversarial_roles()}
    assert spec["required_adversarial"] <= present
    assert set(corpus.expected.adversarial_cases) == present


def test_misfit_and_sparse_cases_do_not_force_a_family(corpus_id: str) -> None:
    corpus = load_corpus(corpus_id)
    for assessment in corpus.expected.assessments:
        if assessment.adversarial_case in {"specialized_misfit", "sparse_evidence", "hybrid"}:
            assert assessment.proposed_family is None
            assert assessment.proposed_level is None
            assert assessment.fit_status in {FitStatus.MISFIT, FitStatus.PROVISIONAL}
        if assessment.adversarial_case in {
            "misleading_senior_title",
            "misleading_title",
            "management_title_without_people",
        }:
            assert assessment.proposed_level is None
            assert assessment.fit_status is FitStatus.PROVISIONAL


def test_corpora_are_not_copies_of_each_other() -> None:
    corpus_a = load_corpus("corpus-a")
    corpus_b = load_corpus("corpus-b")
    assert corpus_a.manifest.organization != corpus_b.manifest.organization
    titles_a = {role.title for role in corpus_a.manifest.roles}
    titles_b = {role.title for role in corpus_b.manifest.roles}
    assert titles_a.isdisjoint(titles_b)
    families_a = {
        item.proposed_family for item in corpus_a.expected.assessments if item.proposed_family
    }
    families_b = {
        item.proposed_family for item in corpus_b.expected.assessments if item.proposed_family
    }
    assert families_a != families_b


def test_python_package_does_not_import_external_clients() -> None:
    src_root = PROJECT_ROOT / "src" / "job_architecture"
    forbidden = ("requests", "httpx", "openai", "anthropic", "superdocs")
    for path in src_root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                lower = stripped.lower()
                for name in forbidden:
                    assert name not in lower, f"{path.name} imports {name}"


def test_forbidden_hint_patterns_are_defined() -> None:
    assert "expected\\s+family" in FORBIDDEN_SOURCE_HINT_PATTERNS
    assert "\\bmisfit\\b" in FORBIDDEN_SOURCE_HINT_PATTERNS
