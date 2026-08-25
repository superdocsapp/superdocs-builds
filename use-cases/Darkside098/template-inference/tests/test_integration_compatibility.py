"""Integration tests for pairwise document compatibility."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from superdocs_template_inference.compatibility import CompatibilityScorer
from superdocs_template_inference.ingestion import DOCXLoader
from superdocs_template_inference.profiling.profiler import DocumentProfiler


@pytest.fixture
def offer_paths():
    """Return a small set of real benchmark DOCX file paths."""
    root = Path(__file__).parent.parent
    offer_dir = root / "corpus" / "offer_letters" / "docx"
    return [str(offer_dir / "offer_001.docx"), str(offer_dir / "offer_002.docx")]


@pytest.fixture
def onboarding_paths():
    """Return a small set of real benchmark DOCX file paths."""
    root = Path(__file__).parent.parent
    onboarding_dir = root / "corpus" / "onboarding_letters" / "docx"
    return [str(onboarding_dir / "onboarding_001.docx"), str(onboarding_dir / "onboarding_002.docx")]


def test_integration_pairwise_comparison_is_serializable(offer_paths):
    """Real benchmark profiles can be compared and serialized."""
    loader = DOCXLoader()
    profiler = DocumentProfiler()
    scorer = CompatibilityScorer()

    profile_a = profiler.profile(loader.load(offer_paths[0]))
    profile_b = profiler.profile(loader.load(offer_paths[1]))

    result = scorer.compare(profile_a, profile_b)

    assert 0.0 <= result.score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.evidence) == 9
    assert len(result.signal_scores) == 9
    assert json.loads(json.dumps(asdict(result)))


def test_integration_comparison_is_deterministic_and_symmetric(offer_paths):
    """Repeated comparisons on the same profiles are stable across orderings."""
    loader = DOCXLoader()
    profiler = DocumentProfiler()
    scorer = CompatibilityScorer()

    profile_a = profiler.profile(loader.load(offer_paths[0]))
    profile_b = profiler.profile(loader.load(offer_paths[1]))

    result1 = scorer.compare(profile_a, profile_b)
    result2 = scorer.compare(profile_a, profile_b)
    result_swap = scorer.compare(profile_b, profile_a)

    assert result1.score == result2.score
    assert result1.confidence == result2.confidence
    assert result1.score == pytest.approx(result_swap.score)
    assert result1.confidence == pytest.approx(result_swap.confidence)


def test_integration_comparison_handles_cross_family_profiles(onboarding_paths, offer_paths):
    """Cross-family comparisons succeed without family-specific assertions."""
    loader = DOCXLoader()
    profiler = DocumentProfiler()
    scorer = CompatibilityScorer()

    onboarding_profile = profiler.profile(loader.load(onboarding_paths[0]))
    offer_profile = profiler.profile(loader.load(offer_paths[0]))

    result = scorer.compare(onboarding_profile, offer_profile)

    assert 0.0 <= result.score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.evidence) == 9
    assert set(result.signal_scores.keys()) == {
        "block_structure_similarity",
        "block_sequence_similarity",
        "heading_distribution_similarity",
        "section_count_similarity",
        "section_structure_similarity",
        "vocabulary_overlap",
        "heading_vocabulary_similarity",
        "table_structure_similarity",
        "document_length_similarity",
    }
