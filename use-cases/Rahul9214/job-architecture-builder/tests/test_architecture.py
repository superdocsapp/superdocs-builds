from pathlib import Path

from job_architecture.architecture import build_architecture
from job_architecture.fixtures import load_corpus
from job_architecture.models import FitStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REASONING_FILES = (
    "assess.py",
    "architecture.py",
    "catalog.py",
    "evidence.py",
    "family.py",
    "level.py",
    "scoring.py",
    "track.py",
    "textutil.py",
    "cluster.py",
)

CANONICAL_FAMILY = {
    "engineering": "engineering",
    "platform_engineering": "engineering",
    "product": "product",
    "clinical_product": "product",
    "design": "design",
    "data": "data",
    "analytics": "data",
    "security": "security",
    "customer_success": "customer_success",
    "implementation": "implementation",
    "people": "people",
    "finance": "finance",
    "operations": "operations",
}


def test_same_engine_on_both_corpora() -> None:
    for corpus_id in ("corpus-a", "corpus-b"):
        corpus = load_corpus(corpus_id)
        result = build_architecture(corpus)
        assert len(result.assessments) == len(corpus.manifest.roles)
        assert result.levels
        assert result.tracks
        assert result.clusters
        assert result.clustering.signatures
        assert result.unclustered_role_ids or result.misfit_role_ids


def test_expected_fit_status_and_canonical_families() -> None:
    for corpus_id in ("corpus-a", "corpus-b"):
        corpus = load_corpus(corpus_id)
        result = build_architecture(corpus)
        got = {item.role_id: item for item in result.assessments}
        for expected in corpus.expected.assessments:
            actual = got[expected.role_id]
            if expected.fit_status is FitStatus.MISFIT:
                assert actual.fit_status is FitStatus.MISFIT, expected.role_id
                assert actual.proposed_family is None
            elif expected.adversarial_case in {"hybrid", "sparse_evidence"}:
                assert actual.fit_status is FitStatus.PROVISIONAL, expected.role_id
                assert actual.proposed_family is None
            elif expected.fit_status is FitStatus.STRONG_FIT:
                assert actual.fit_status is FitStatus.STRONG_FIT, expected.role_id
                assert actual.proposed_family == CANONICAL_FAMILY[expected.proposed_family]
                if expected.proposed_track:
                    assert actual.proposed_track == expected.proposed_track, expected.role_id


def test_reasoning_source_has_no_fixture_identifiers() -> None:
    src = PROJECT_ROOT / "src" / "job_architecture"
    forbidden = (
        "corpus-a",
        "corpus-b",
        "northstar",
        "meridian",
        "ns-swe",
        "ns-em",
        "mh-",
        "workplace tools",
        "developer advocate",
        "medical science",
        "program coordinator",
        "solutions architect",
        "patient portal widgets",
    )
    for name in REASONING_FILES:
        text = (src / name).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{name} contains {token!r}"
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                assert "requests" not in stripped
                assert "httpx" not in stripped
                assert "openai" not in stripped


def test_architecture_result_lists_provisional_and_misfits() -> None:
    corpus = load_corpus("corpus-a")
    result = build_architecture(corpus)
    assert "ns-program-coordinator" in result.provisional_role_ids
    assert "ns-developer-advocate" in result.misfit_role_ids
    assert "ns-solutions-architect" in result.provisional_role_ids
    family_ids = {family.id for family in result.families}
    assert "engineering" in family_ids
    assert {level.label for level in result.levels} >= {"IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3"}
