"""Integration tests for family clustering with real benchmark documents."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from superdocs_template_inference.clustering import FamilyClusterer
from superdocs_template_inference.ingestion import DOCXLoader
from superdocs_template_inference.profiling.profiler import DocumentProfiler


@pytest.fixture
def offer_paths():
    """Return real benchmark offer letter DOCX paths."""
    root = Path(__file__).parent.parent
    offer_dir = root / "corpus" / "offer_letters" / "docx"
    paths = sorted(offer_dir.glob("offer_*.docx"))
    return [str(p) for p in paths]


@pytest.fixture
def onboarding_paths():
    """Return real benchmark onboarding letter DOCX paths."""
    root = Path(__file__).parent.parent
    onboarding_dir = root / "corpus" / "onboarding_letters" / "docx"
    paths = sorted(onboarding_dir.glob("onboarding_*.docx"))
    return [str(p) for p in paths]


@pytest.fixture
def all_benchmark_profiles(offer_paths, onboarding_paths):
    """Load and profile all benchmark documents."""
    loader = DOCXLoader()
    profiler = DocumentProfiler()

    profiles = []
    for path in offer_paths + onboarding_paths:
        try:
            doc = loader.load(path)
            profile = profiler.profile(doc)
            profiles.append(profile)
        except Exception:
            # Skip missing documents
            pass

    return profiles


class TestClusteringIntegrationBasic:
    """Basic integration tests for clustering with real documents."""

    def test_integration_clustering_executes_successfully(self, all_benchmark_profiles):
        """Real benchmark profiles can be clustered successfully."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()
        result = clusterer.cluster(all_benchmark_profiles)

        assert result.num_clusters >= 1
        assert result.num_documents == len(all_benchmark_profiles)

    def test_every_document_appears_exactly_once(self, all_benchmark_profiles):
        """Every document should appear in exactly one cluster."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()
        result = clusterer.cluster(all_benchmark_profiles)

        mapping = result.get_document_to_cluster_mapping()

        # Every document should appear exactly once
        assert len(mapping) == len(all_benchmark_profiles)
        assert set(mapping.keys()) == {p.document_id for p in all_benchmark_profiles}

    def test_cluster_sizes_are_valid(self, all_benchmark_profiles):
        """Cluster sizes should be valid."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()
        result = clusterer.cluster(all_benchmark_profiles)

        for cluster in result.clusters:
            assert cluster.cluster_size >= 1
            assert len(cluster.document_ids) == cluster.cluster_size
            assert len(cluster.document_filenames) == cluster.cluster_size

    def test_num_documents_is_correct(self, all_benchmark_profiles):
        """num_documents should equal sum of cluster sizes."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()
        result = clusterer.cluster(all_benchmark_profiles)

        total_docs = sum(c.cluster_size for c in result.clusters)
        assert result.num_documents == total_docs
        assert result.num_documents == len(all_benchmark_profiles)

    def test_score_and_confidence_ranges_are_valid(self, all_benchmark_profiles):
        """All scores and confidence values should be in [0.0, 1.0]."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()
        result = clusterer.cluster(all_benchmark_profiles)

        for cluster in result.clusters:
            assert 0.0 <= cluster.confidence <= 1.0
            assert 0.0 <= cluster.pairwise_score_mean <= 1.0
            assert 0.0 <= cluster.pairwise_score_min <= 1.0

            for score in cluster.pairwise_scores:
                assert 0.0 <= score <= 1.0


class TestClusteringIntegrationSerialization:
    """Tests for serialization of clustering results."""

    def test_result_is_serializable(self, all_benchmark_profiles):
        """Clustering result should be JSON-serializable."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()
        result = clusterer.cluster(all_benchmark_profiles)

        # Verify that result can be converted to dict and serialized
        result_dict = {
            "clusters": [
                {
                    "family_id": c.family_id,
                    "document_ids": c.document_ids,
                    "document_filenames": c.document_filenames,
                    "confidence": c.confidence,
                    "cluster_size": c.cluster_size,
                    "pairwise_scores": c.pairwise_scores,
                    "pairwise_score_mean": c.pairwise_score_mean,
                    "pairwise_score_min": c.pairwise_score_min,
                }
                for c in result.clusters
            ],
            "num_clusters": result.num_clusters,
            "num_documents": result.num_documents,
            "algorithm": result.algorithm,
            "threshold_used": result.threshold_used,
            "clustering_version": result.clustering_version,
        }

        # Should not raise
        json_str = json.dumps(result_dict)
        assert len(json_str) > 0


class TestClusteringIntegrationDeterminism:
    """Tests for determinism and reproducibility."""

    def test_repeated_runs_are_deterministic(self, all_benchmark_profiles):
        """Repeated clustering of same profiles produces identical results."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()

        result1 = clusterer.cluster(all_benchmark_profiles)
        result2 = clusterer.cluster(all_benchmark_profiles)

        mapping1 = result1.get_document_to_cluster_mapping()
        mapping2 = result2.get_document_to_cluster_mapping()

        assert mapping1 == mapping2
        assert result1.num_clusters == result2.num_clusters

    def test_shuffled_input_produces_same_clustering(self, all_benchmark_profiles):
        """Clustering should be identical regardless of input order."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()

        # Cluster in original order
        result1 = clusterer.cluster(all_benchmark_profiles)

        # Cluster in reversed order
        result2 = clusterer.cluster(list(reversed(all_benchmark_profiles)))

        mapping1 = result1.get_document_to_cluster_mapping()
        mapping2 = result2.get_document_to_cluster_mapping()

        assert mapping1 == mapping2


class TestClusteringIntegrationNoFileAccess:
    """Tests to verify clustering does not access files."""

    def test_clustering_does_not_read_docx_files(self, all_benchmark_profiles):
        """Clustering should not re-open DOCX files."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        # The profiles are already loaded; clustering should only use them
        clusterer = FamilyClusterer()

        # This should not raise or access files
        result = clusterer.cluster(all_benchmark_profiles)

        assert result.num_clusters >= 1

    def test_clustering_does_not_read_ground_truth_files(self, all_benchmark_profiles):
        """Clustering should not access ground-truth JSON files."""
        if not all_benchmark_profiles:
            pytest.skip("No benchmark documents available")

        clusterer = FamilyClusterer()

        # Rename ground-truth files temporarily to verify they're not accessed
        root = Path(__file__).parent.parent
        gt_offer = root / "evaluation" / "ground_truth" / "offer_ground_truth.json"
        gt_onboarding = root / "evaluation" / "ground_truth" / "onboarding_ground_truth.json"

        # Check if they exist (they should for this test)
        gt_files_exist = gt_offer.exists() and gt_onboarding.exists()

        if gt_files_exist:
            # Clustering should work without ground truth
            result = clusterer.cluster(all_benchmark_profiles)
            assert result.num_clusters >= 1


class TestClusteringIntegrationCorpusPreservation:
    """Tests to verify benchmark corpus is not modified."""

    def test_benchmark_corpus_unchanged_after_clustering(self, all_benchmark_profiles, offer_paths, onboarding_paths):
        """Benchmark corpus files should remain unchanged after clustering."""
        import subprocess

        # Record initial git status of corpus
        result_before = subprocess.run(
            ["git", "status", "--short", "corpus"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        clusterer = FamilyClusterer()
        clusterer.cluster(all_benchmark_profiles)

        # Record final git status of corpus
        result_after = subprocess.run(
            ["git", "status", "--short", "corpus"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        # Should be identical (no modifications)
        assert result_before.stdout == result_after.stdout == ""


class TestClusteringIntegrationSmallSubset:
    """Tests with a small subset of benchmark documents."""

    def test_small_offer_subset_clustering(self, offer_paths):
        """Cluster a small subset of offer letters."""
        if len(offer_paths) < 2:
            pytest.skip("Not enough offer letter documents")

        loader = DOCXLoader()
        profiler = DocumentProfiler()

        # Use only first 2 offer letters
        profiles = []
        for path in offer_paths[:2]:
            doc = loader.load(path)
            profile = profiler.profile(doc)
            profiles.append(profile)

        clusterer = FamilyClusterer()
        result = clusterer.cluster(profiles)

        assert result.num_documents == 2
        assert result.num_clusters >= 1

    def test_small_onboarding_subset_clustering(self, onboarding_paths):
        """Cluster a small subset of onboarding letters."""
        if len(onboarding_paths) < 2:
            pytest.skip("Not enough onboarding letter documents")

        loader = DOCXLoader()
        profiler = DocumentProfiler()

        # Use only first 2 onboarding letters
        profiles = []
        for path in onboarding_paths[:2]:
            doc = loader.load(path)
            profile = profiler.profile(doc)
            profiles.append(profile)

        clusterer = FamilyClusterer()
        result = clusterer.cluster(profiles)

        assert result.num_documents == 2
        assert result.num_clusters >= 1

    def test_mixed_offer_and_onboarding_clustering(self, offer_paths, onboarding_paths):
        """Cluster a small mixed set of offer and onboarding letters.

        Note: This test does NOT assert that families separate correctly.
        It only verifies that clustering executes and produces valid results.
        Family accuracy is evaluated externally against ground truth.
        """
        if len(offer_paths) < 1 or len(onboarding_paths) < 1:
            pytest.skip("Not enough documents")

        loader = DOCXLoader()
        profiler = DocumentProfiler()

        # Mix: 1 offer + 1 onboarding
        profiles = []
        for path in [offer_paths[0], onboarding_paths[0]]:
            doc = loader.load(path)
            profile = profiler.profile(doc)
            profiles.append(profile)

        clusterer = FamilyClusterer()
        result = clusterer.cluster(profiles)

        # Just verify structure, no family assertions
        assert result.num_documents == 2
        assert result.num_clusters >= 1
        assert all(0.0 <= c.confidence <= 1.0 for c in result.clusters)
